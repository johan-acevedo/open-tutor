"""The session's voice: a fixed greeting without the LLM, a warm-up race, a short leash.

Pinned here, in order of the three problems the child hit on 2026-11-14:
- the greeting is spoken by TTS alone and still lands in the chat history;
- the route for the whole session comes from the warm-up race (`choose_route`);
- a slow or dead route loses within seconds and the other one answers.
"""

import asyncio
import dataclasses
import json
import time

import httpx2
import pytest
from livekit.agents import llm
from livekit.agents.types import APIConnectOptions

from open_tutor import prompt
from open_tutor.agent import Tutor, greet
from open_tutor.config import LLMRoute, llm_fallback_route, llm_route
from open_tutor.session_llm import FALLBACK, PREFERRED, SessionLLM, choose_route

# ---- the choice rule (pure) -----------------------------------------------------------

PREFER = 1.5


@pytest.mark.parametrize(
    "preferred_ttft, fallback_ttft, expected",
    [
        (0.4, 2.0, PREFERRED),      # preferred answered within the window
        (0.4, None, PREFERRED),     # the other route errored or never answered
        (2.6, 3.1, PREFERRED),      # both slow, but the preferred one was faster
        (3.4, 1.2, FALLBACK),       # preferred answered, the other was faster
        (2.0, 0.9, FALLBACK),       # preferred outside the window, other faster
        (None, 1.9, FALLBACK),      # preferred errored or timed out; the other answered
        (None, None, PREFERRED),    # neither answered: keep it, normal errors apply
    ],
)
def test_choice_rule(preferred_ttft, fallback_ttft, expected):
    assert choose_route(preferred_ttft, fallback_ttft, PREFER) == expected


def test_choice_rule_without_a_fallback_route():
    assert choose_route(0.1, None, PREFER, has_fallback=False) == PREFERRED
    assert choose_route(None, 0.1, PREFER, has_fallback=False) == PREFERRED
    assert choose_route(None, None, PREFER, has_fallback=False) == PREFERRED


def test_prefer_within_is_the_boundary():
    assert choose_route(PREFER, 0.1, PREFER) == PREFERRED
    assert choose_route(PREFER + 0.01, 0.1, PREFER) == FALLBACK


# ---- routes from the environment ------------------------------------------------------


def test_no_fallback_configured_keeps_todays_single_route():
    assert llm_fallback_route({"OPENCODE_GO_API_KEY": "k"}) is None
    assert llm_fallback_route({"OPENCODE_GO_API_KEY": "k", "TUTOR_LLM_FALLBACK": "  "}) is None


def test_fallback_route_is_built_from_its_own_name_and_key():
    route = llm_fallback_route(
        {
            "TUTOR_LLM": "gemini",
            "GEMINI_API_KEY": "g",
            "OPENCODE_GO_API_KEY": "k",
            "TUTOR_LLM_FALLBACK": "go-deepseek",
        }
    )
    assert route is not None
    assert route.name == "go-deepseek" and route.model == "deepseek-v4.1-flash"
    assert route.thought_signatures is False


def test_fallback_base_url_can_move_alone():
    env = {
        "TUTOR_LLM": "gemini",
        "GEMINI_API_KEY": "g",
        "OPENCODE_GO_API_KEY": "k",
        "TUTOR_LLM_FALLBACK": "go-deepseek",
        "TUTOR_LLM_BASE_URL": "http://127.0.0.1:9/dead",
        "TUTOR_LLM_FALLBACK_BASE_URL": "https://live.example/v1",
    }
    assert llm_route(env).base_url == "http://127.0.0.1:9/dead"
    fallback = llm_fallback_route(env)
    assert fallback is not None and fallback.base_url == "https://live.example/v1"


def test_fallback_must_differ_from_the_preferred_route():
    with pytest.raises(ValueError):
        llm_fallback_route(
            {"TUTOR_LLM": "gemini", "GEMINI_API_KEY": "g", "TUTOR_LLM_FALLBACK": "gemini"}
        )


# ---- the greeting ---------------------------------------------------------------------


@pytest.mark.parametrize("index", range(len(prompt.GREETING_VARIANTS)))
def test_every_greeting_variant_uses_the_name_and_two_sentences(index):
    line, chosen = prompt.greeting_line({"name": "Kian"}, index=index)
    assert chosen == index
    assert "Kian" in line
    # Two sentences, warm, no emoji, and it asks what the child is working on.
    assert line.count("?") + line.count("!") + line.count(".") >= 2
    assert "Räven" in line
    assert "?" in line
    assert not any(ord(char) > 0x2100 for char in line)
    for word in ("läxor", "skol"):
        assert word in line


def test_greeting_without_a_name_still_reads():
    line, _ = prompt.greeting_line({}, index=0)
    assert "None" not in line and "du" in line


def test_greeting_note_keeps_what_the_greeting_instruction_carried():
    line, _ = prompt.greeting_line({"name": "Kian"}, index=0)
    note = prompt.greeting_note({"name": "Kian"}, line)
    assert line in note
    assert "Do not greet again" in note
    # A returning learner hears about last time in the model's first reply.
    returning = prompt.greeting_note(
        {"name": "Kian", "notes": [{"topic": "Ekvationer"}]}, line
    )
    assert "earlier sessions" in returning


def test_greeting_note_reaches_the_instructions():
    line, _ = prompt.greeting_line({"name": "Kian"}, index=0)
    note = prompt.greeting_note({"name": "Kian"}, line)
    plain = Tutor({"name": "Kian"}, room=None)
    greeted = Tutor({"name": "Kian"}, room=None, greeting_note=note)
    assert note not in plain.instructions
    assert greeted.instructions.endswith(note)
    # The line is fixed text, so the model never sees the old "greet the child" prompt.
    assert "Never call `save_note` at the greeting" in greeted.instructions


class FakeHandle:
    def __init__(self) -> None:
        self.interrupted = False
        self.played = asyncio.Event()

    async def wait_for_playout(self) -> None:
        self.played.set()


class FakeSession:
    """The parts of AgentSession that `greet` and the greeting tests touch."""

    def __init__(self) -> None:
        self.said: list[tuple[str, dict]] = []
        self.history: list[tuple[str, str]] = []
        self.replies: list[str] = []
        self.handle = FakeHandle()
        self.running = True

    def say(self, text, **kwargs):
        if not self.running:
            raise RuntimeError("AgentSession isn't running")
        self.said.append((text, kwargs))
        # LiveKit's say() adds the line as the assistant's turn when add_to_chat_ctx.
        if kwargs.get("add_to_chat_ctx", True):
            self.history.append(("assistant", text))
        return self.handle

    def generate_reply(self, user_input=None, **kwargs):
        self.replies.append(user_input or "")
        return self.handle


class FakeDebug:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def record(self, event, data=None) -> None:
        self.events.append((event, data or {}))


async def test_greeting_is_spoken_by_tts_alone_and_enters_the_history():
    session, debug = FakeSession(), FakeDebug()
    line, variant = prompt.greeting_line({"name": "Kian"}, index=1)

    await greet(session, debug, line, variant, {"name": "Kian"})
    await asyncio.sleep(0)

    assert session.said == [(line, {"allow_interruptions": False})]
    assert session.replies == []  # no LLM turn, so nothing waits on a provider
    assert session.history == [("assistant", line)]  # the model knows it has greeted
    assert any(event == "greeting" and data["variant"] == variant for event, data in debug.events)
    assert any(event == "greeting_done" for event, _ in debug.events)


async def test_greeting_falls_back_to_the_model_when_the_session_is_gone():
    session, debug = FakeSession(), FakeDebug()
    session.running = False
    line, variant = prompt.greeting_line({"name": "Kian"}, index=0)

    await greet(session, debug, line, variant, {"name": "Kian"})

    assert session.said == []
    assert session.replies and "Greet the child" in session.replies[0]
    assert any(event == "greeting" and data.get("kind") == "generated" for event, data in debug.events)


# ---- the race and the failover -------------------------------------------------------


class FakeLLM(llm.LLM):
    """An LLM whose answer per call is scripted: a delay, and an error from call N."""

    def __init__(
        self, model: str, *, ttft: float = 0.01, error: Exception | None = None, error_from: int = 1
    ) -> None:
        super().__init__()
        self._model = model
        self.ttft = ttft
        self.error = error
        self.error_from = error_from
        self.calls = 0
        self.warm_up_requests: list[dict] = []

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "fake"

    def chat(self, *, chat_ctx=None, tools=None, conn_options=None, **kwargs):
        self.calls += 1
        self.warm_up_requests.append({"chat_ctx": chat_ctx, "tools": list(tools or [])})
        fail = self.error if self.error is not None and self.calls >= self.error_from else None
        return _FakeStream(self, chat_ctx or llm.ChatContext(), tools or [], conn_options,
                           ttft=self.ttft, error=fail)


class _FakeStream(llm.LLMStream):
    def __init__(self, owner, chat_ctx, tools, conn_options, *, ttft, error) -> None:
        super().__init__(owner, chat_ctx=chat_ctx, tools=tools,
                         conn_options=conn_options or APIConnectOptions())
        self._owner = owner
        self._ttft = ttft
        self._error = error
        self._failed = False

    async def _run(self) -> None:
        if self._ttft:
            await asyncio.sleep(self._ttft)
        if self._error is not None and not self._failed:
            self._failed = True
            raise self._error
        await self._event_ch.send(
            llm.ChatChunk(id="c1", delta=llm.ChoiceDelta(role="assistant", content="Hej"))
        )


def route(name: str, *, signatures: bool = False) -> LLMRoute:
    return LLMRoute(
        name=name, api="chat", base_url="http://fake", model=f"{name}-model",
        api_key="k", reasoning_effort=None, thought_signatures=signatures,
    )


async def test_race_picks_the_preferred_route_when_it_is_fast_enough():
    preferred, fallback = FakeLLM("preferred", ttft=0.02), FakeLLM("fallback", ttft=0.02)
    model = SessionLLM(preferred, route("preferred"), fallback, route("fallback"), prefer_within=1.5)

    result = await model.warm_up(instructions="Du är Räven.", tools=[])
    picked = await model.pick()

    assert result["route"] == "preferred"
    assert picked is preferred
    assert result["preferred_s"] is not None and result["preferred_s"] < 1.0
    assert model.route_name == "preferred"


async def test_race_picks_the_other_route_when_the_preferred_one_is_slow():
    preferred = FakeLLM("preferred", ttft=0.6)
    fallback = FakeLLM("fallback", ttft=0.02)
    model = SessionLLM(preferred, route("slow"), fallback, route("quick"), prefer_within=0.1)

    result = await model.warm_up(instructions="Du är Räven.", tools=[])

    assert result["route"] == "quick" and result["choice"] == FALLBACK
    assert result["preferred_s"] >= 0.5 and result["fallback_s"] < 0.5
    assert await model.pick() is fallback


async def test_race_keeps_the_preferred_route_when_the_other_one_errors():
    preferred = FakeLLM("preferred", ttft=0.02)
    fallback = FakeLLM("fallback", ttft=0.01, error=RuntimeError("boom"))
    model = SessionLLM(preferred, route("preferred"), fallback, route("broken"), prefer_within=0.1)

    result = await model.warm_up(instructions="Du är Räven.", tools=[])

    assert result["route"] == "preferred"
    assert result["fallback_s"] is None  # an error loses the race, it does not win it


async def test_race_keeps_the_preferred_route_when_neither_answers():
    preferred = FakeLLM("preferred", ttft=0.01, error=RuntimeError("boom"))
    fallback = FakeLLM("fallback", ttft=0.01, error=RuntimeError("boom"))
    model = SessionLLM(preferred, route("preferred"), fallback, route("broken"), prefer_within=1.5)

    result = await model.warm_up(instructions="Du är Räven.", tools=[])

    # Keeping the preferred route means normal error handling applies (apology, log).
    assert result["route"] == "preferred"
    assert result["preferred_s"] is None and result["fallback_s"] is None
    assert "neither" in result["reason"]


async def test_no_fallback_configured_means_no_race():
    preferred = FakeLLM("preferred", ttft=0.01)
    model = SessionLLM(preferred, route("go"))

    result = await model.warm_up(instructions="Du är Räven.", tools=[])

    assert result["route"] == "go" and result["choice"] == PREFERRED
    assert preferred.calls == 0  # nothing was sent: a single route needs no warm-up


async def test_warm_up_uses_the_real_system_prompt_and_the_real_tools():
    preferred, fallback = FakeLLM("preferred", ttft=0.01), FakeLLM("fallback", ttft=0.2)
    model = SessionLLM(preferred, route("preferred"), fallback, route("other"), prefer_within=1.5)
    tools = list(Tutor({"name": "Kian"}, room=None).tools)

    await model.warm_up(instructions="Du är Räven. Detta är den riktiga instruktionen.", tools=tools)

    request = preferred.warm_up_requests[0]
    system = [item for item in request["chat_ctx"].items if item.role == "system"]
    assert system and "riktiga instruktionen" in system[0].text_content
    assert [tool.id for tool in request["tools"]] == [tool.id for tool in tools]


async def test_a_request_waits_for_the_decision_only_while_it_runs():
    preferred = FakeLLM("preferred", ttft=0.25)
    fallback = FakeLLM("fallback", ttft=0.01)
    model = SessionLLM(preferred, route("slow"), fallback, route("quick"), prefer_within=0.0)

    async def run_request():
        stream = model.chat(chat_ctx=llm.ChatContext())
        try:
            async for _ in stream:
                pass
        finally:
            await stream.aclose()

    race = asyncio.create_task(model.warm_up(instructions="Du är Räven.", tools=[]))
    await asyncio.sleep(0.05)  # the child's turn arrives before the race decided
    await run_request()
    await race

    assert await model.pick() is fallback
    assert fallback.calls >= 2  # the warm-up plus the real request


async def test_failover_moves_the_session_to_a_route_without_signatures():
    error = RuntimeError("provider 500")
    preferred = FakeLLM("preferred", ttft=0.01, error=error, error_from=2)
    fallback = FakeLLM("fallback", ttft=0.01)
    model = SessionLLM(preferred, route("gemini", signatures=True), fallback, route("go-deepseek"))
    await model.warm_up(instructions="Du är Räven.", tools=[])
    assert model.route_name == "gemini"  # the warm-up itself answered

    text = ""
    stream = model.chat(chat_ctx=llm.ChatContext())
    try:
        async for chunk in stream:
            text += (chunk.delta.content if chunk.delta else "") or ""
    finally:
        await stream.aclose()

    assert text == "Hej"  # the child heard the answer from the other route
    assert model.route_name == "go-deepseek"
    assert await model.pick() is fallback


async def test_no_failover_to_a_route_that_needs_thought_signatures():
    error = RuntimeError("provider 500")
    preferred = FakeLLM("preferred", ttft=0.01, error=error, error_from=2)
    fallback = FakeLLM("fallback", ttft=0.01)
    model = SessionLLM(preferred, route("go-deepseek"), fallback, route("gemini", signatures=True))
    await model.warm_up(instructions="Du är Räven.", tools=[])

    stream = model.chat(chat_ctx=llm.ChatContext())
    with pytest.raises(RuntimeError):
        async for _ in stream:
            pass
    await stream.aclose()

    # The existing apology path owns this case: the route did not switch.
    assert model.route_name == "go-deepseek"


async def test_no_failover_once_the_child_has_heard_something():
    class _PartlyThenFails(FakeLLM):
        def chat(self, **kwargs):
            return _PartialStream(self, kwargs.get("chat_ctx") or llm.ChatContext(),
                                  kwargs.get("tools") or [], kwargs.get("conn_options"))

    preferred = _PartlyThenFails("preferred")
    fallback = FakeLLM("fallback", ttft=0.01)
    model = SessionLLM(preferred, route("preferred"), fallback, route("go-deepseek"))
    await model.warm_up(instructions="Du är Räven.", tools=[])

    heard = ""
    stream = model.chat(chat_ctx=llm.ChatContext())
    with pytest.raises(RuntimeError):
        async for chunk in stream:
            heard += (chunk.delta.content if chunk.delta else "") or ""
    await stream.aclose()

    assert heard == "Hej"  # half a sentence was spoken; repeating it would be worse
    assert model.route_name == "preferred"
    assert fallback.calls < 2  # only the warm-up, never the failed turn


class _PartialStream(llm.LLMStream):
    def __init__(self, owner, chat_ctx, tools, conn_options) -> None:
        super().__init__(owner, chat_ctx=chat_ctx, tools=tools,
                         conn_options=conn_options or APIConnectOptions())
        self._failed = False

    async def _run(self) -> None:
        await self._event_ch.send(
            llm.ChatChunk(id="c1", delta=llm.ChoiceDelta(role="assistant", content="Hej"))
        )
        if not self._failed:
            self._failed = True
            raise RuntimeError("connection dropped mid-reply")


def test_session_connect_options_are_short():
    """The worker gives each attempt 5 s and one retry (agent.entrypoint)."""
    import inspect

    from open_tutor import agent

    source = inspect.getsource(agent.entrypoint)
    assert "TUTOR_LLM_TIMEOUT_S" in source and "max_retry=1" in source


# ---- the fixed greeting and a message typed before it ---------------------------------


async def test_typed_before_the_greeting_uses_its_own_instruction(tmp_path):
    """A message typed before the room was ready replaces the line, in one reply."""
    from open_tutor.agent import TYPED_BEFORE_GREETING
    from open_tutor.text_input import GREET_AND_ANSWER, TypedChat

    class Session:
        def __init__(self) -> None:
            self.replies: list[dict] = []

        async def interrupt(self, *, force: bool = False):
            return None

        def generate_reply(self, **kwargs):
            self.replies.append(kwargs)
            return object()

    class Reader:
        info = type("Info", (), {"topic": "lk.chat"})()

        async def read_all(self) -> str:
            return "Hej! Jag ska räkna 3/4 + 1/8"

    typed = TypedChat()
    typed.expect("learner-1")
    session = Session()
    typed.attach_session(session)
    typed.on_stream(Reader(), "learner-1")
    await asyncio.gather(*list(typed._tasks))

    line, _ = prompt.greeting_line({"name": "Kian"}, index=0)
    spoken: list[str] = []
    await typed.start(
        prompt.greeting_instruction({"name": "Kian"}),
        lambda text: spoken.append(text),
        greet_instruction=TYPED_BEFORE_GREETING.format(line=line),
    )

    assert spoken == [], "the line is not spoken over the child's own words"
    assert len(session.replies) == 1
    instructions = session.replies[0]["instructions"]
    assert line in instructions and instructions != GREET_AND_ANSWER
    assert session.replies[0]["user_input"] == "Hej! Jag ska räkna 3/4 + 1/8"
