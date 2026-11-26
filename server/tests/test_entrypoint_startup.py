"""The real entrypoint starts with stubbed providers.

Regression for the 2026-11-18 startup crash (``tutor.end_event = ending``
ran before ``ending`` existed, so every worker session died with NameError
before saying hello). This drives the real ``entrypoint`` with a fake room
and stubbed providers into the end path via the tutor's own end event, and
checks the lesson ends like Avsluta: greeting spoken, A's note saved, room
deleted. A startup crash raises here instead of hanging.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from open_tutor import agent as agent_module
from open_tutor.agent import entrypoint


class FakeHandle:
    async def wait_for_playout(self):
        return None


class FakeParticipant:
    def __init__(self, identity, metadata):
        self.identity = identity
        self.metadata = metadata


class FakeLocalParticipant:
    def __init__(self):
        self.attributes: dict = {}
        self.sent: list[tuple[str, str]] = []

    async def set_attributes(self, attributes):
        self.attributes.update(attributes)

    async def send_text(self, payload, *, topic, destination_identities=None):
        self.sent.append((topic, payload))


class FakeRoom:
    def __init__(self):
        self.name = "tutor-test"
        self.handlers: dict = {}
        self.local_participant = FakeLocalParticipant()

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def register_text_stream_handler(self, topic, handler):
        self.handlers.setdefault(f"text:{topic}", []).append(handler)

    def register_byte_stream_handler(self, topic, handler):
        self.handlers.setdefault(f"bytes:{topic}", []).append(handler)


class FakeSession:
    def __init__(self, *args, **kwargs):
        self.handlers: dict = {}
        self.started = False
        self.agent = None
        self.said: list[str] = []
        self.closed = False

    def on(self, event, handler=None):
        # Used both as session.on(event, fn) and as @session.on(event).
        if handler is None:
            def decorator(fn):
                self.handlers.setdefault(event, []).append(fn)
                return fn
            return decorator
        self.handlers.setdefault(event, []).append(handler)
        return handler

    async def start(self, *, agent, room, **kwargs):
        self.started = True
        self.agent = agent

    def say(self, text, **kwargs):
        self.said.append(text)
        return FakeHandle()

    def interrupt(self):
        pass

    def generate_reply(self, **kwargs):
        return FakeHandle()

    async def aclose(self):
        self.closed = True


class FakeScreen:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.pane_source = None

    def set_pane_source(self, source):
        self.pane_source = source

    async def warmup(self):
        return None

    def screen_stats_summary(self):
        return {}


def make_ctx(learner):
    room = FakeRoom()
    participant = FakeParticipant(
        "learner-1",
        json.dumps({"learner": learner, "board": {"w": 1920, "h": 1080}, "device_id": "0b9e2c4a-1f3d-4e5a-9b7c-2d4e6f8a1c3e"}),
    )

    async def connect():
        return None

    async def wait_for_participant():
        return participant

    async def delete_room():
        return None

    def shutdown(message):
        ctx.shutdown_message = message

    ctx = SimpleNamespace(
        connect=connect,
        room=room,
        wait_for_participant=wait_for_participant,
        proc=SimpleNamespace(userdata={"vad": object()}),
        job=None,
        delete_room=delete_room,
        shutdown=shutdown,
        shutdown_message=None,
    )
    return ctx


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_module, "build_stt", lambda: object())
    monkeypatch.setattr(agent_module, "build_tts",
                        lambda: SimpleNamespace(provider="stub", model="stub"))
    monkeypatch.setattr(agent_module, "build_session_llm", lambda room: object())
    monkeypatch.setattr(agent_module, "AgentSession", FakeSession)
    monkeypatch.setattr("open_tutor.screen.Screen", FakeScreen)
    monkeypatch.setattr("open_tutor.screen.session_pages_dir",
                        lambda room, debug_dir=None: tmp_path / "pages")
    return tmp_path


async def wait_until(predicate, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_entrypoint_starts_greets_and_ends_like_avsluta(stubbed):
    session_holder: dict = {}

    original_start = FakeSession.start

    async def start_and_capture(self, **kwargs):
        session_holder["session"] = self
        await original_start(self, **kwargs)

    stubbed_session = FakeSession
    stubbed_session.start = start_and_capture  # type: ignore[method-assign]
    try:
        ctx = make_ctx({"id": "pA", "name": "Leo", "grade": 7, "notes": []})
        task = asyncio.create_task(entrypoint(ctx))
        # Startup must reach the session (no NameError, providers stubbed).
        await wait_until(lambda: session_holder.get("session") is not None
                         and session_holder["session"].started)
        tutor = session_holder["session"].agent
        # The tutor's end trigger is the same event the entrypoint waits on.
        assert tutor.end_event is not None
        # The greeting went out through TTS with the learner's name.
        await wait_until(lambda: len(session_holder["session"].said) > 0)
        assert "Leo" in session_holder["session"].said[0]
        # End the lesson: the normal path saves A's note and deletes the room.
        tutor.end_event.set()
        await asyncio.wait_for(task, timeout=10)
        assert tutor.notes_saved == 1
        topics = [topic for topic, _ in ctx.room.local_participant.sent]
        assert "note" in topics
        assert ctx.shutdown_message == "session ended"
        assert session_holder["session"].closed
    finally:
        stubbed_session.start = original_start  # type: ignore[method-assign]
