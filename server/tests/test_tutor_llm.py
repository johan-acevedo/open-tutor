"""The Go route through LiveKit's Responses adapter, replaying a recorded Go stream.

The fixture replays the recorded shape of a real OpenCode Go response (fictional
prompt): spoken text, a structured `ask_screen` call whose arguments stream in two
deltas, and a usage block without `cache_write_tokens`.
"""

import json
from pathlib import Path

import httpx2
import pytest
from livekit.agents.llm import ChatContext, FunctionCall, FunctionCallOutput

from open_tutor.agent import SmartTutor
from open_tutor.config import llm_route
from open_tutor.tutor_llm import GoResponsesLLM, build_llm, build_route_llm

FIXTURE = (Path(__file__).parent / "fixtures" / "go_responses_tool_call.sse").read_bytes()


@pytest.fixture
def go_env(monkeypatch):
    for name in ("TUTOR_LLM", "TUTOR_LLM_MODEL", "TUTOR_LLM_BASE_URL", "TUTOR_LLM_REASONING"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key")


class StubScreen:
    """The tutor only needs a screen object it can point at the pane size."""

    def set_pane_source(self, source):
        self.pane_source = source


def smart_tutor(learner=None):
    return SmartTutor(learner or {"name": "Leo"}, room=None, screen=StubScreen())


def recorded_go(requests):
    def handler(request):
        requests.append(request)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=FIXTURE)

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


async def run(model, ctx, tutor):
    text, calls, usage = "", [], None
    async with model.chat(chat_ctx=ctx, tools=list(tutor.tools)) as stream:
        async for chunk in stream:
            if chunk.delta:
                text += chunk.delta.content or ""
                calls += chunk.delta.tool_calls or []
            usage = chunk.usage or usage
    return text, calls, usage


def context():
    ctx = ChatContext()
    ctx.add_message(role="system", content="Svensk läxhjälp.")
    ctx.add_message(role="user", content="Visa hur man löser 3x + 5 = 20 på tavlan.")
    return ctx


async def test_tool_call_is_structured_and_never_in_the_text(go_env):
    requests = []
    model = build_llm("tutor-room-1", http_client=recorded_go(requests))
    assert isinstance(model, GoResponsesLLM)
    text, calls, usage = await run(model, context(), smart_tutor())

    # The words are speech; the call is a call. Nothing of the call leaks into the text.
    assert text.strip() == "Jag fixar en sida om ekvationen."
    assert [call.name for call in calls] == ["ask_screen"]
    for fragment in ("ask_screen", "{", '"ask"', "3x"):
        assert fragment not in text
    # Streamed argument deltas are reassembled into complete JSON.
    arguments = json.loads(calls[0].arguments)
    assert arguments["show"] == "auto" and "3x + 5 = 20" in arguments["ask"]
    # Go's usage lacks cache_write_tokens; the turn still completes with usage.
    assert usage is not None and usage.prompt_tokens == 666

    await model.aclose()


async def test_requests_identify_the_app_and_carry_no_server_state(go_env):
    requests = []
    model = build_llm("tutor-room-1", http_client=recorded_go(requests))
    tutor = smart_tutor()
    ctx = context()
    _, calls, _ = await run(model, ctx, tutor)
    ctx.items.append(FunctionCall(call_id=calls[0].call_id, name=calls[0].name, arguments=calls[0].arguments))
    ctx.items.append(FunctionCallOutput(call_id=calls[0].call_id, name=calls[0].name,
                                        output="Item b1 is now visible on the board.", is_error=False))
    await run(model, ctx, tutor)  # the follow-up step after the tool result

    assert str(requests[0].url) == "https://opencode.ai/inference/go/openai/v1/responses"
    for request in requests:
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.headers["user-agent"].startswith("open-tutor/")
        assert request.headers["x-opencode-session"] == "tutor-room-1"
        body = json.loads(request.content)
        assert body["model"] == "muse-spark-1.3-contributor" and body["stream"] is True
        assert body["store"] is False and "previous_response_id" not in body
        assert body["reasoning"]["effort"] == "minimal"
        assert "temperature" not in body  # Muse runs at its tuned default
    # The follow-up sends the whole turn: the structured call and its result, in order.
    follow_up = json.loads(requests[1].content)["input"]
    kinds = [item.get("type") for item in follow_up]
    assert kinds[-2:] == ["function_call", "function_call_output"]
    assert follow_up[-1]["call_id"] == follow_up[-2]["call_id"] == calls[0].call_id

    await model.aclose()


async def test_each_session_gets_its_own_model_and_session_id(go_env):
    first, second = [], []
    a = build_llm("tutor-room-1", http_client=recorded_go(first))
    b = build_llm("tutor-room-2", http_client=recorded_go(second))
    assert a is not b
    await run(a, context(), smart_tutor())
    await run(b, context(), smart_tutor())
    assert first[0].headers["x-opencode-session"] == "tutor-room-1"
    assert second[0].headers["x-opencode-session"] == "tutor-room-2"
    await a.aclose()
    await b.aclose()


async def test_cc_route_calls_command_code_responses_with_the_session_header():
    """The backup route is the same Responses shape as Go, on Command Code's endpoint.

    Command Code tolerates Go's `x-opencode-session` header, so the route reuses it."""
    requests = []
    route = llm_route({"TUTOR_LLM": "cc", "COMMAND_CODE_API_KEY": "cc-key"})
    model = build_route_llm(route, "tutor-room-9", http_client=recorded_go(requests))
    try:
        assert isinstance(model, GoResponsesLLM)
        text, calls, _ = await run(model, context(), smart_tutor())
        assert text.strip() == "Jag fixar en sida om ekvationen."
        assert [call.name for call in calls] == ["ask_screen"]
        assert str(requests[0].url) == "https://api.commandcode.ai/provider/v1/responses"
        assert requests[0].headers["authorization"] == "Bearer cc-key"
        assert requests[0].headers["x-opencode-session"] == "tutor-room-9"
        body = json.loads(requests[0].content)
        assert body["model"] == "meta/muse-spark-1.3-contributor"
        assert body["reasoning"]["effort"] == "minimal"
        assert body["store"] is False
    finally:
        await model.aclose()


def test_warm_up_builds_the_event_models():
    from open_tutor.tutor_llm import warm_up

    warm_up()  # runs in every job process before the first session; must not raise


async def test_progress_reply_omits_tools_without_sending_unsupported_none(go_env):
    requests = []
    model = build_llm("tutor-progress", http_client=recorded_go(requests))
    tutor = smart_tutor()
    tools = list(tutor.tools)
    ctx = context()
    ctx.items.append(FunctionCall(call_id="page", name="ask_screen",
                                  arguments='{"ask":"En sida om bråk","show":"auto"}'))
    ctx.items.append(FunctionCallOutput(call_id="page", name="ask_screen",
                                        output="The screen is working on it now (job s1).",
                                        is_error=False))
    try:
        async with model.chat(chat_ctx=ctx, tools=tools, tool_choice="none") as stream:
            async for _ in stream:
                pass
        body = json.loads(requests[0].content)
        assert not body.get("tools")
        assert body.get("tool_choice", "auto") == "auto"
        assert body["input"][-1]["call_id"] == "page"
        assert body["input"][-1]["type"] == "function_call_output"
        # Only the progress reply loses tools. The next turn can use them again.
        await run(model, ctx, tutor)
        assert json.loads(requests[1].content)["tools"]
        assert tools == list(tutor.tools)
    finally:
        await model.aclose()
