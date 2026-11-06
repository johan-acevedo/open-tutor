"""A malformed tool call must not wedge the session, and shutdown must be safe.

On 2026-11-06 Go emitted a `show_text` call with empty arguments. The tool runner
read it as `{}` (so the model got a useful argument error), but the empty string
stayed in history and Go rejected every follow-up request carrying it with
`400 `arguments` must be valid JSON`. After consecutive rejections the AgentSession
closed, a later `session.interrupt()` crashed the job, and the browser sat silent
in the dead room. These tests pin the fixes with synthetic history only.
"""

import json
from pathlib import Path

import httpx2
import pytest
from livekit.agents.llm import ChatContext, ChatMessage, FunctionCall, FunctionCallOutput

from open_tutor.agent import Tutor, safe_interrupt
from open_tutor.tutor_llm import GoResponsesLLM, build_llm, heal_tool_arguments

FIXTURE = (Path(__file__).parent / "fixtures" / "go_responses_tool_call.sse").read_bytes()


@pytest.fixture
def go_env(monkeypatch):
    for name in ("TUTOR_LLM", "TUTOR_LLM_MODEL", "TUTOR_LLM_BASE_URL", "TUTOR_LLM_REASONING"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")


def recorded_go(requests):
    def handler(request):
        requests.append(request)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=FIXTURE)

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def poisoned_context() -> ChatContext:
    """Synthetic equivalent of the real failure: a call with empty arguments plus its error."""
    ctx = ChatContext()
    ctx.add_message(role="system", content="Svensk läxhjälp.")
    ctx.add_message(role="user", content="Visa något på tavlan.")
    ctx.items.append(FunctionCall(call_id="call_empty", name="show_text", arguments=""))
    ctx.items.append(FunctionCallOutput(
        call_id="call_empty", name="show_text",
        output=("Error parsing arguments for `show_text`: 2 validation errors for "
                "ShowTextArgs (title and markdown are required)"),
        is_error=True,
    ))
    return ctx


def test_empty_arguments_heal_to_empty_object():
    assert heal_tool_arguments(poisoned_context()) == 1


def test_healed_history_serializes_to_valid_json_arguments():
    ctx = poisoned_context()
    heal_tool_arguments(ctx)
    items, _ = ctx.to_provider_format("openai.responses")
    calls = [i for i in items if i.get("type") == "function_call"]
    assert len(calls) == 1 and calls[0]["call_id"] == "call_empty"
    # The exact wire value the tool runner assumed; Go accepts it (probed live 2026-11-06).
    assert calls[0]["arguments"] == "{}"
    json.loads(calls[0]["arguments"])
    # The error survives so the model still sees what went wrong and can retry.
    outputs = [i for i in items if i.get("type") == "function_call_output"]
    assert outputs[0]["call_id"] == "call_empty" and "show_text" in outputs[0]["output"]


def test_unhealed_history_would_replay_the_poison():
    """Pins the failure mode: without healing, the empty string goes on the wire."""
    ctx = poisoned_context()
    items, _ = ctx.to_provider_format("openai.responses")
    calls = [i for i in items if i.get("type") == "function_call"]
    assert calls[0]["arguments"] == ""
    with pytest.raises(ValueError):
        json.loads(calls[0]["arguments"])


def test_valid_arguments_are_left_byte_identical():
    ctx = ChatContext()
    exact = '{"title": "Ekvationer", "markdown": "- $3x + 5 = 20$"}'
    ctx.items.append(FunctionCall(call_id="call_ok", name="show_text", arguments=exact))
    assert heal_tool_arguments(ctx) == 0
    assert ctx.items[0].arguments == exact


def test_repaired_arguments_use_the_framework_canonical_form():
    ctx = ChatContext()
    ctx.items.append(FunctionCall(call_id="call_trailing", name="show_text",
                                 arguments='{"title": "Hej",}'))
    assert heal_tool_arguments(ctx) == 1
    assert ctx.items[0].arguments == '{"title": "Hej"}'
    json.loads(ctx.items[0].arguments)


def test_unrepairable_garbage_is_left_untouched():
    ctx = ChatContext()
    ctx.items.append(FunctionCall(call_id="call_garbage", name="show_text", arguments="!!!"))
    assert heal_tool_arguments(ctx) == 0
    assert ctx.items[0].arguments == "!!!"


async def test_healed_turn_sends_provider_valid_history(go_env):
    """End to end through the adapter: the poisoned turn goes out as valid JSON."""
    requests = []
    model = build_llm("tutor-room-9", http_client=recorded_go(requests))
    assert isinstance(model, GoResponsesLLM)
    tutor = Tutor({"name": "Leo"}, room=None)
    async with model.chat(chat_ctx=poisoned_context(), tools=list(tutor.tools)) as stream:
        async for _ in stream:
            pass
    body = json.loads(requests[0].content)
    sent = {i.get("call_id"): i for i in body["input"] if i.get("type") == "function_call"}
    assert sent["call_empty"]["arguments"] == "{}"
    json.loads(sent["call_empty"]["arguments"])
    await model.aclose()


async def test_streamed_valid_call_still_draws(go_env):
    """A normal tool call is untouched by healing and passes the board's validation."""
    from open_tutor.board import StepsItem

    requests = []
    model = build_llm("tutor-room-9", http_client=recorded_go(requests))
    tutor = Tutor({"name": "Leo"}, room=None)
    ctx = ChatContext()
    ctx.add_message(role="system", content="Svensk läxhjälp.")
    ctx.add_message(role="user", content="Visa hur man löser 3x + 5 = 20 på tavlan.")
    calls = []
    async with model.chat(chat_ctx=ctx, tools=list(tutor.tools)) as stream:
        async for chunk in stream:
            if chunk.delta:
                calls += chunk.delta.tool_calls or []
    assert [c.name for c in calls] == ["show_steps"]
    raw = calls[0].arguments
    assert heal_tool_arguments(ctx) == 0  # nothing to heal on a clean turn
    assert calls[0].arguments == raw  # streamed arguments retained exactly
    arguments = json.loads(raw)
    StepsItem(id="b1", title=arguments["title"], steps=arguments["steps"])
    await model.aclose()


def test_safe_interrupt_tolerates_a_closed_session():
    class Closed:
        def interrupt(self):
            from livekit.agents.voice.agent_session import AgentSession
            raise RuntimeError("AgentSession isn't running")

    safe_interrupt(Closed(), "ending")  # must not raise


def test_safe_interrupt_passes_through_on_a_live_session():
    seen = []

    class Live:
        def interrupt(self):
            seen.append(True)
            return "handle"

    safe_interrupt(Live(), "ending")
    assert seen == [True]
