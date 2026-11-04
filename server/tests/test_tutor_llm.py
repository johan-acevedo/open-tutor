"""The Go route through LiveKit's Responses adapter, replaying a recorded Go stream.

The fixture is a real OpenCode Go response (fictional prompt) with spoken text, a
structured `show_steps` call and a usage block without `cache_write_tokens`.
"""

import json
from pathlib import Path

import httpx2
import pytest
from livekit.agents.llm import ChatContext, FunctionCall, FunctionCallOutput

from open_tutor.agent import Tutor
from open_tutor.board import StepsItem
from open_tutor.tutor_llm import GoResponsesLLM, build_llm

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
    text, calls, usage = await run(model, context(), Tutor({"name": "Leo"}, room=None))

    # The words are speech; the call is a call. Nothing of the call leaks into the text.
    assert text.strip() == "Visar lösningen på tavlan."
    assert [call.name for call in calls] == ["show_steps"]
    for fragment in ("show_steps", "{", '"tex"', "3x"):
        assert fragment not in text
    # Arguments are complete JSON and pass the board's own validation.
    arguments = json.loads(calls[0].arguments)
    StepsItem(id="b1", title=arguments["title"], steps=arguments["steps"])
    # Go's usage lacks cache_write_tokens; the turn still completes with usage.
    assert usage is not None and usage.prompt_tokens == 666

    await model.aclose()


async def test_requests_identify_the_app_and_carry_no_server_state(go_env):
    requests = []
    model = build_llm("tutor-room-1", http_client=recorded_go(requests))
    tutor = Tutor({"name": "Leo"}, room=None)
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
    await run(a, context(), Tutor({"name": "Leo"}, room=None))
    await run(b, context(), Tutor({"name": "Leo"}, room=None))
    assert first[0].headers["x-opencode-session"] == "tutor-room-1"
    assert second[0].headers["x-opencode-session"] == "tutor-room-2"
    await a.aclose()
    await b.aclose()


def test_warm_up_builds_the_event_models():
    from open_tutor.tutor_llm import warm_up

    warm_up()  # runs in every job process before the first session; must not raise
