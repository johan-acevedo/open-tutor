"""A typed chat message must never vanish.

On 2026-11-12/13 a child's typed message was sometimes never answered and left no
``chat_item`` in the session trail. Two holes did it, both silent:

1. the message was published before the agent participant was in the room, so the
   room had nobody to deliver it to (the browser still reported a successful send);
2. the message reached the worker's room after it joined but before any text stream
   handler was registered (RoomIO registers ``lk.chat`` inside
   ``AgentSession.start()``), and the RTC layer disposes a stream whose topic has no
   handler — only an INFO line on the ``livekit`` logger, silenced to WARN in our
   worker.

``TypedChat`` closes hole 2 (registered right after the room connects, messages
queued until the session can answer) and records every message, so a message that
still fails is an event instead of nothing at all.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from open_tutor.debug_log import DebugLog, clear_active, set_active
from open_tutor.text_input import GREET_AND_ANSWER, TOPIC_CHAT, TypedChat


class FakeReader:
    def __init__(self, text: str = "", *, error: Exception | None = None,
                 hang: bool = False) -> None:
        self.text = text
        self.error = error
        self.hang = hang
        self.info = type("Info", (), {"topic": TOPIC_CHAT})()

    async def read_all(self) -> str:
        if self.hang:
            await asyncio.sleep(3600)
        if self.error is not None:
            raise self.error
        return self.text


class FakeSession:
    """Just the surface TypedChat uses: interrupt() and generate_reply()."""

    def __init__(self, *, interrupt_error: Exception | None = None,
                 reply_error: Exception | None = None) -> None:
        self.interrupts = 0
        self.replies: list[dict] = []
        self.interrupt_error = interrupt_error
        self.reply_error = reply_error
        self.loop = asyncio.get_event_loop()

    async def interrupt(self, *, force: bool = False):
        self.interrupts += 1
        if self.interrupt_error is not None:
            raise self.interrupt_error
        return None

    def generate_reply(self, **kwargs):
        if self.reply_error is not None:
            raise self.reply_error
        self.replies.append(kwargs)
        return object()


@pytest.fixture
def debug(tmp_path: Path):
    log = DebugLog.create("tutor-typed-test", {"name": "Testbarn", "grade": 5}, "AJ_test",
                          environ={"TUTOR_DEBUG_LOG": "1"}, base_dir=tmp_path)
    set_active(log)
    yield log
    clear_active()


def events(log: DebugLog, name: str) -> list[dict]:
    return [entry for entry in log.events if entry["event"] == name]


def make(debug_log: DebugLog, session: FakeSession | None = None) -> TypedChat:
    typed = TypedChat()
    typed.attach_record(debug_log.record)
    typed.expect("learner-1")
    if session is not None:
        typed.attach_session(session)
    return typed


async def deliver(typed: TypedChat, text: str, *, identity: str = "learner-1") -> None:
    typed.on_stream(FakeReader(text), identity)
    await asyncio.gather(*list(typed._tasks))


async def test_message_typed_before_the_session_is_ready_is_answered(debug):
    """Hole 2: the message arrives before the session can answer. It waits, then answers."""
    session = FakeSession()
    typed = make(debug, session)
    await deliver(typed, "Hej! Jag ska räkna 3/4 + 1/8")
    await asyncio.sleep(0.05)
    assert session.replies == [], "nothing may be generated before the session runs"

    prompts: list[str] = []
    await typed.start("Hälsa på barnet.", lambda text: prompts.append(text))

    assert prompts == [], "the waiting message replaces the standalone greeting"
    assert len(session.replies) == 1
    assert session.replies[0]["user_input"] == "Hej! Jag ska räkna 3/4 + 1/8"
    assert session.replies[0]["instructions"] == GREET_AND_ANSWER
    # The trail has the message even though LiveKit never got to commit a chat item.
    arrival = events(debug, "chat_typed")
    assert [entry["text"] for entry in arrival] == ["Hej! Jag ska räkna 3/4 + 1/8"]
    assert arrival[0]["queued"] is True
    assert events(debug, "prompt")[-1]["kind"] == "typed_chat"


async def test_greeting_is_prompted_when_nothing_was_typed(debug):
    session = FakeSession()
    typed = make(debug, session)
    prompts: list[str] = []
    await typed.start("Hälsa på barnet.", lambda text: prompts.append(text))
    assert prompts == ["Hälsa på barnet."]
    assert session.replies == []
    assert [entry["kind"] for entry in events(debug, "prompt")] == ["greeting"]


async def test_message_during_greeting_generation_is_interrupted_and_answered(debug):
    """The greeting has not been heard yet: one reply greets and answers."""
    session = FakeSession()
    typed = make(debug, session)
    await typed.start("Hälsa på barnet.", lambda text: None)
    await deliver(typed, "Vad är 3/4 + 1/8?")
    assert session.interrupts == 1, "the pending greeting must not keep generating"
    assert session.replies[-1]["user_input"] == "Vad är 3/4 + 1/8?"
    assert session.replies[-1]["instructions"] == GREET_AND_ANSWER


async def test_message_while_the_tutor_speaks_interrupts_and_answers_without_greeting(debug):
    session = FakeSession()
    typed = make(debug, session)
    await typed.start("Hälsa på barnet.", lambda text: None)
    typed.mark_heard()  # the tutor is speaking
    await deliver(typed, "Kan du visa på skärmen?")
    assert session.interrupts == 1
    assert session.replies[-1]["user_input"] == "Kan du visa på skärmen?"
    assert "instructions" not in session.replies[-1]


async def test_uninterruptible_speech_still_gets_an_answer(debug):
    """RoomIO's default callback would raise here and drop the message."""
    session = FakeSession(interrupt_error=RuntimeError("This generation handle does not allow interruptions"))
    typed = make(debug, session)
    await typed.start("Hälsa på barnet.", lambda text: None)
    await deliver(typed, "Vänta, jag fattar inte")
    assert session.replies[-1]["user_input"] == "Vänta, jag fattar inte"
    assert events(debug, "chat_typed")


async def test_a_stream_that_never_completes_is_recorded_not_awaited_forever(debug, monkeypatch):
    monkeypatch.setattr("open_tutor.text_input.READ_TIMEOUT_S", 0.05)
    typed = make(debug, FakeSession())
    typed.on_stream(FakeReader(hang=True), "learner-1")
    await asyncio.gather(*list(typed._tasks))
    failed = events(debug, "chat_typed_failed")
    assert failed and failed[0]["stage"] == "read" and failed[0]["error"] == "timeout"


async def test_a_read_error_is_recorded(debug):
    typed = make(debug, FakeSession())
    typed.on_stream(FakeReader(error=RuntimeError("stream reset")), "learner-1")
    await asyncio.gather(*list(typed._tasks))
    failed = events(debug, "chat_typed_failed")
    assert failed and failed[0]["stage"] == "read" and "stream reset" in failed[0]["error"]


async def test_a_failed_reply_is_recorded(debug):
    session = FakeSession(reply_error=RuntimeError("AgentSession isn't running"))
    typed = make(debug, session)
    await typed.start("Hälsa på barnet.", lambda text: None)
    await deliver(typed, "Hej")
    failed = events(debug, "chat_typed_failed")
    assert failed and failed[0]["stage"] == "reply"
    assert "AgentSession isn't running" in failed[0]["error"]
    # And the message itself is still in the trail.
    assert [entry["text"] for entry in events(debug, "chat_typed")] == ["Hej"]


async def test_messages_from_other_participants_are_ignored(debug):
    session = FakeSession()
    typed = make(debug, session)
    await typed.start("Hälsa på barnet.", lambda text: None)
    await deliver(typed, "Hej från någon annan", identity="observer-1")
    assert session.replies == []
    assert events(debug, "chat_typed") == []


async def test_a_second_message_while_interrupting_joins_the_same_reply(debug):
    session = FakeSession()
    typed = make(debug, session)
    await typed.start("Hälsa på barnet.", lambda text: None)

    async def slow_interrupt(*, force: bool = False):
        session.interrupts += 1
        await asyncio.sleep(0.02)
        return None

    session.interrupt = slow_interrupt  # type: ignore[method-assign]
    first = asyncio.create_task(deliver(typed, "Första frågan"))
    await asyncio.sleep(0.005)
    second = asyncio.create_task(deliver(typed, "Andra frågan"))
    await asyncio.gather(first, second)

    assert len(session.replies) == 1, session.replies
    assert session.replies[0]["user_input"] == "Första frågan\nAndra frågan"
    assert len(events(debug, "chat_typed")) == 2


async def test_the_debug_trail_can_be_read_back_as_json(tmp_path):
    """The regression is visible in the session report, not only in memory."""
    log = DebugLog.create("tutor-typed-json", {"name": "Testbarn"}, "AJ_json",
                          environ={"TUTOR_DEBUG_LOG": "1"}, base_dir=tmp_path)
    set_active(log)
    try:
        session = FakeSession()
        typed = make(log, session)
        await typed.start("Hälsa på barnet.", lambda text: None)
        await deliver(typed, "Hej!")
        report = log.finalize("test")
        assert report is not None
        data = json.loads(Path(report).read_text(encoding="utf-8"))
        kinds = [entry["event"] for entry in data["events"]]
        assert "chat_typed" in kinds and "prompt" in kinds
        typed_entries = [entry for entry in data["events"] if entry["event"] == "chat_typed"]
        assert typed_entries[0]["text"] == "Hej!"
    finally:
        clear_active()


async def test_typed_listener_fires_once_per_message_with_no_text(debug):
    """Analytics counts typed turns from this hook: one call per message that
    arrives (no text, never stored), none for ignored senders or empty reads."""
    session = FakeSession()
    typed = make(debug, session)
    calls: list[None] = []
    typed.attach_typed_listener(lambda: calls.append(None))
    await typed.start("Hälsa på barnet.", lambda text: None)
    await deliver(typed, "Första frågan")
    await deliver(typed, "Andra frågan")
    await deliver(typed, "   ")  # empty: recorded as failed, not a turn
    await deliver(typed, "Från någon annan", identity="observer-1")
    assert len(calls) == 2
    assert len(events(debug, "chat_typed")) == 2


async def test_typed_listener_failure_never_breaks_the_turn(debug):
    """A throwing analytics listener must not lose the child's message."""
    session = FakeSession()
    typed = make(debug, session)

    def explode() -> None:
        raise RuntimeError("analytics is down")

    typed.attach_typed_listener(explode)
    await typed.start("Hälsa på barnet.", lambda text: None)
    await deliver(typed, "Hej")
    assert len(session.replies) == 1
    assert [entry["text"] for entry in events(debug, "chat_typed")] == ["Hej"]
