"""The Gemini 4 Hydrogen route: route config, thought signatures and parallel calls.

The fixture is a real Gemini 4 Hydrogen OpenAI-compatible stream (fictional prompt),
trimmed to two function calls with `index: null` and a placeholder signature. On
2026-11-13 a live session failed with
``400 Function call is missing a thought_signature in functionCall parts``: the
response called two tools, LiveKit kept only the last (unsigned) one, and the
follow-up request replayed it alone.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest
from livekit.agents import Agent, APIStatusError, function_tool, llm
from livekit.agents.llm import ChatContext, FunctionCall, FunctionCallOutput

from open_tutor import prompt
from open_tutor.agent import (
    Tutor,
    PROVIDER_FAILED_APOLOGY,
    is_fatal_llm_error,
    prompt_event,
    say_provider_failed,
)
from open_tutor.config import llm_route
from open_tutor.tutor_llm import GeminiChatLLM, build_llm

FIXTURE = (Path(__file__).parent / "fixtures" / "gemini_parallel_calls.sse").read_bytes()
SIGNATURE = "sig-one"


class TwoTools(Agent):
    def __init__(self) -> None:
        super().__init__(instructions="Du är en lärare. Svara kort på svenska.")

    @function_tool()
    async def show_page(self, page_id: str) -> str:
        """Show a page on screen.

        Args:
            page_id: The page id.
        """
        return f"Page {page_id} is now visible."

    @function_tool()
    async def start_quiet_work(self) -> str:
        """Start quiet work: the child works alone."""
        return "Quiet work started."


@pytest.fixture
def gemini_env(monkeypatch):
    for name in ("TUTOR_LLM", "TUTOR_LLM_MODEL", "TUTOR_LLM_BASE_URL", "TUTOR_LLM_REASONING"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TUTOR_LLM", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def recorded(requests):
    def handler(request):
        requests.append(request)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=FIXTURE)

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def context() -> ChatContext:
    ctx = ChatContext()
    ctx.add_message(role="system", content="Svensk läxhjälp.")
    ctx.add_message(role="user", content="Sidan p1 är klar. Anropa båda verktygen.")
    return ctx


async def run(model, ctx, agent):
    calls = []
    async with model.chat(chat_ctx=ctx, tools=list(agent.tools)) as stream:
        async for chunk in stream:
            if chunk.delta:
                calls += chunk.delta.tool_calls or []
    return calls


def test_gemini_route_is_hydrogen_with_low_thinking():
    route = llm_route({"TUTOR_LLM": "gemini", "GEMINI_API_KEY": "k"})
    assert route.api == "chat"
    assert route.model == "gemini-4-hydrogen"
    assert route.reasoning_effort == "low"
    assert route.thought_signatures is True


async def test_every_parallel_call_and_its_signature_survive(gemini_env):
    requests = []
    model = build_llm("tutor-room-gemini", http_client=recorded(requests))
    assert isinstance(model, GeminiChatLLM)
    try:
        calls = await run(model, context(), TwoTools())
    finally:
        await model.aclose()

    # Without the index fix LiveKit kept only start_quiet_work: the second call
    # overwrote the first because both arrived with index=None.
    assert [call.name for call in calls] == ["show_page", "start_quiet_work"]
    assert calls[0].extra == {"google": {"thought_signature": SIGNATURE}}
    assert calls[1].extra in (None, {})


async def test_follow_up_sends_the_signed_call_back(gemini_env):
    requests = []
    model = build_llm("tutor-room-gemini", http_client=recorded(requests))
    ctx = context()
    try:
        calls = await run(model, ctx, TwoTools())
        for index, call in enumerate(calls):
            # LiveKit gives calls from one response a shared id prefix; the formatter
            # then groups them into one assistant message.
            ctx.items.append(FunctionCall(id=f"item_test/fnc_{index}", call_id=call.call_id,
                                          name=call.name, arguments=call.arguments,
                                          extra=call.extra or {}))
            ctx.items.append(FunctionCallOutput(call_id=call.call_id, name=call.name,
                                                output="ok", is_error=False))
        await run(model, ctx, TwoTools())
    finally:
        await model.aclose()

    body = json.loads(requests[1].content)
    # The route's thinking level travels as reasoning_effort on this endpoint.
    assert body["reasoning_effort"] == "low"
    assistant = next(m for m in body["messages"] if m.get("tool_calls"))
    assert [tc["function"]["name"] for tc in assistant["tool_calls"]] == [
        "show_page", "start_quiet_work"
    ]
    assert assistant["tool_calls"][0]["extra_content"] == {
        "google": {"thought_signature": SIGNATURE}
    }


def test_prompt_bans_save_note_at_the_greeting():
    """Gemini called save_note on the greeting turn (live, 2026-11-13).

    The ban lives in the memory instructions and the tool description, not in the
    greeting event: `tool_choice="none"` was tried first and is worse (Gemini still
    emitted a call, LiveKit ignored it, and the turn produced no text at all).
    """
    instructions = prompt.instructions({"name": "Testbarn", "grade": 5})
    assert "Never call `save_note` at the greeting" in instructions
    tool_doc = Tutor.save_note.__doc__ or ""
    assert "never at the greeting" in tool_doc


def test_prompt_event_is_a_bracketed_user_turn():
    class FakeSession:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def generate_reply(self, **kwargs):
            self.calls.append(kwargs)
            return "handle"

    session = FakeSession()
    assert prompt_event(session, "Hälsa barnet.") == "handle"
    assert session.calls[0]["user_input"].startswith("[Session event, not the child's words:")


def test_only_non_retryable_llm_errors_are_fatal():
    def error_event(error):
        return SimpleNamespace(error=error)

    fatal = llm.LLMError(timestamp=0, label="x", error=ValueError("400"), recoverable=False)
    retryable = llm.LLMError(timestamp=0, label="x", error=ValueError("timeout"), recoverable=True)
    assert is_fatal_llm_error(error_event(fatal))
    assert not is_fatal_llm_error(error_event(retryable))
    assert not is_fatal_llm_error(error_event(ValueError("not an LLM error")))


async def test_provider_failure_apology_uses_tts_only():
    class FakeHandle:
        async def wait_for_playout(self) -> None:
            return None

    class FakeSession:
        def __init__(self) -> None:
            self.said = ""
            self.allow_interruptions = None

        def say(self, text, *, allow_interruptions=True):
            self.said = text
            self.allow_interruptions = allow_interruptions
            return FakeHandle()

    session = FakeSession()
    await say_provider_failed(session)
    assert session.said == PROVIDER_FAILED_APOLOGY
    assert session.allow_interruptions is False
