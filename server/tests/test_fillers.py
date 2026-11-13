"""The fox's filler sounds: when one plays, when it must not, and what it leaves behind.

Everything here runs against fakes: no TTS call, no LiveKit room, no audio. The
decision logic is the part worth pinning; the real playback is checked by the
e2e run against a live worker.
"""

from __future__ import annotations

import asyncio
import random
import struct
from pathlib import Path

import pytest

from open_tutor.fillers import (
    Clip,
    Fillers,
    FillerClips,
    clip_duration,
    clip_problem,
    energy_segments,
    trim_silence,
    voice_fingerprint,
)


# ---- fakes -----------------------------------------------------------------------


class FakeClipSet:
    """A ready clip set on disk-free paths."""

    def __init__(self, names: tuple[str, ...] = ("mm", "hmm", "aha", "ska-vi-se")) -> None:
        self.clips = [Clip(name, Path(f"/clips/{name}.wav"),
                           "phrase" if "-" in name else "sound") for name in names]
        self.directory = Path("/clips")

    @property
    def ready(self) -> bool:
        return bool(self.clips)


class FakeHandle:
    def __init__(self) -> None:
        self.stopped = False
        self._done = False

    def done(self) -> bool:
        return self._done

    def stop(self) -> None:
        self.stopped = True
        self._done = True


class FakePlayer:
    """Records what was played; stands in for BackgroundAudioPlayer."""

    def __init__(self) -> None:
        self.played: list[tuple[str, float]] = []
        self.handles: list[FakeHandle] = []
        self.cleared = 0
        self._audio_source = self

    def play(self, config) -> FakeHandle:
        self.played.append((Path(config.source).stem, config.volume))
        handle = FakeHandle()
        self.handles.append(handle)
        return handle

    def clear_queue(self) -> None:
        self.cleared += 1

    @property
    def last_handle(self) -> FakeHandle:
        return self.handles[-1]


class FakeSession:
    """Just enough AgentSession: handlers, states, and a chat context to inspect."""

    def __init__(self) -> None:
        self.handlers: dict[str, list] = {}
        self.agent_state = "listening"
        self.user_state = "listening"
        self.chat_ctx: list[dict[str, str]] = []
        self.said: list[str] = []

    def on(self, name: str, handler) -> None:
        self.handlers.setdefault(name, []).append(handler)

    def emit(self, name: str, event) -> None:
        for handler in self.handlers.get(name, []):
            handler(event)

    # Anything that would put words in the transcript or the history is a failure.
    def say(self, *args, **kwargs):
        self.said.append(str(args[0]) if args else "")
        raise AssertionError("a filler must never go through session.say()")

    def generate_reply(self, *args, **kwargs):
        raise AssertionError("a filler must never request a reply")


class Item:
    def __init__(self, role: str, text: str, kind: str = "message") -> None:
        self.type = kind
        self.role = role
        self.text_content = text


class Event:
    def __init__(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


def item_added(item: Item) -> Event:
    return Event(type="conversation_item_added", item=item)


def agent_state(state: str) -> Event:
    return Event(type="agent_state_changed", new_state=state, old_state="listening")


def user_state(state: str) -> Event:
    return Event(type="user_state_changed", new_state=state, old_state="listening")


def make_fillers(player: FakePlayer, session: FakeSession, mode: str = "talking",
                 delay: float = 0.05, names: tuple[str, ...] = ("mm", "hmm", "aha", "ska-vi-se"),
                 seed: int = 7) -> Fillers:
    fillers = Fillers(clips=FakeClipSet(names), player=player, delay=delay,
                      rng=random.Random(seed), mode=lambda: mode)
    fillers.attach(session, lambda: mode)
    return fillers


async def settle(seconds: float = 0.2) -> None:
    await asyncio.sleep(seconds)


# ---- the decision ----------------------------------------------------------------


async def test_filler_plays_when_the_reply_is_late():
    player, session = FakePlayer(), FakeSession()
    fillers = make_fillers(player, session)

    session.agent_state = "thinking"
    session.emit("conversation_item_added", item_added(Item("user", "Vad är 3/4?")))
    assert player.played == []
    await settle()
    assert len(player.played) == 1
    name, volume = player.played[0]
    assert name in {"mm", "hmm", "aha", "ska-vi-se"}
    assert 0.4 <= volume <= 0.7  # a little below the fox's normal speech


async def test_no_filler_when_the_reply_starts_in_time():
    player, session = FakePlayer(), FakeSession()
    fillers = make_fillers(player, session, delay=0.2)

    session.agent_state = "thinking"
    session.emit("conversation_item_added", item_added(Item("user", "Vad är 3/4?")))
    await asyncio.sleep(0.05)
    session.agent_state = "speaking"
    session.emit("agent_state_changed", agent_state("speaking"))
    await settle(0.3)
    assert player.played == []


async def test_a_filler_that_already_plays_stops_when_the_reply_starts():
    player, session = FakePlayer(), FakeSession()
    fillers = make_fillers(player, session)

    session.agent_state = "thinking"
    session.emit("conversation_item_added", item_added(Item("user", "Vad är 3/4?")))
    await settle()
    assert len(player.played) == 1
    assert player.last_handle.stopped is False

    session.agent_state = "speaking"
    session.emit("agent_state_changed", agent_state("speaking"))
    assert player.last_handle.stopped is True
    assert player.cleared == 1  # the player's 400 ms queue is emptied too


async def test_child_speaking_stops_the_filler_at_once():
    player, session = FakePlayer(), FakeSession()
    fillers = make_fillers(player, session)

    session.agent_state = "thinking"
    session.emit("conversation_item_added", item_added(Item("user", "Vad är 3/4?")))
    await settle()
    assert len(player.played) == 1

    session.user_state = "speaking"
    session.emit("user_state_changed", user_state("speaking"))
    assert player.last_handle.stopped is True


async def test_child_speaking_before_the_delay_cancels_it():
    player, session = FakePlayer(), FakeSession()
    fillers = make_fillers(player, session, delay=0.2)

    session.agent_state = "thinking"
    session.emit("conversation_item_added", item_added(Item("user", "Vad är 3/4?")))
    session.user_state = "speaking"
    session.emit("user_state_changed", user_state("speaking"))
    await settle(0.3)
    assert player.played == []


async def test_at_most_one_filler_per_turn():
    player, session = FakePlayer(), FakeSession()
    fillers = make_fillers(player, session)

    session.agent_state = "thinking"
    session.emit("conversation_item_added", item_added(Item("user", "Vad är 3/4?")))
    await settle()
    # A second event for the same turn (the screen forwards turns too) must not
    # produce a second sound.
    fillers.arm()
    await settle()
    assert len(player.played) == 1


async def test_never_the_same_clip_twice_in_a_row():
    player, session = FakePlayer(), FakeSession()
    fillers = make_fillers(player, session, names=("mm", "hmm"))

    for _ in range(4):
        session.agent_state = "thinking"
        session.emit("conversation_item_added", item_added(Item("user", "Och sen?")))
        await settle()
        session.agent_state = "listening"
        session.emit("agent_state_changed", agent_state("listening"))

    names = [name for name, _ in player.played]
    assert len(names) == 4
    assert all(a != b for a, b in zip(names, names[1:]))


async def test_nothing_in_quiet_work_mode():
    player, session = FakePlayer(), FakeSession()
    mode = {"value": "quiet"}
    fillers = Fillers(clips=FakeClipSet(), player=player, delay=0.05,
                      rng=random.Random(1), mode=lambda: mode["value"])
    fillers.attach(session, lambda: mode["value"])

    session.agent_state = "thinking"
    session.emit("conversation_item_added", item_added(Item("user", "Jag räknar själv nu")))
    await settle()
    assert player.played == []

    # ... and a filler never plays into a mode the tutor switched to in the meantime.
    mode["value"] = "talking"
    session.emit("conversation_item_added", item_added(Item("user", "Klart")))
    await asyncio.sleep(0.02)
    mode["value"] = "resource"
    await settle()
    assert player.played == []


@pytest.mark.parametrize("text", [
    "[Session event, not the child's words: greeting]",
    "[Screen page p1 ('Bråk') is ready but NOT visible. Source: ...]",
])
async def test_session_events_and_greeting_get_no_filler(text):
    player, session = FakePlayer(), FakeSession()
    fillers = make_fillers(player, session)

    session.agent_state = "thinking"
    session.emit("conversation_item_added", item_added(Item("user", text)))
    await settle()
    assert player.played == []


async def test_nothing_before_the_clips_exist():
    player, session = FakePlayer(), FakeSession()
    empty = FillerClips.__new__(FillerClips)
    empty.clips = []
    empty.directory = Path("/clips")
    fillers = Fillers(clips=empty, player=player, delay=0.05, mode=lambda: "talking")
    fillers.attach(session, lambda: "talking")

    session.agent_state = "thinking"
    session.emit("conversation_item_added", item_added(Item("user", "Hej")))
    await settle()
    assert player.played == []


async def test_no_reply_pending_means_no_sound():
    """The reply already finished (agent back to listening): stay silent."""
    player, session = FakePlayer(), FakeSession()
    fillers = make_fillers(player, session)

    session.agent_state = "listening"
    session.emit("conversation_item_added", item_added(Item("user", "Hej")))
    await settle()
    assert player.played == []


# ---- what it leaves behind -------------------------------------------------------


async def test_a_filler_never_enters_history_transcript_or_caption():
    player, session = FakePlayer(), FakeSession()
    fillers = make_fillers(player, session)
    clip_texts = {"Mm.", "Hmm.", "Aha.", "Ska vi se..."}

    session.agent_state = "thinking"
    session.emit("conversation_item_added", item_added(Item("user", "Vad är 3/4?")))
    await settle()

    assert len(player.played) == 1
    assert session.said == []                                # no session.say()
    assert session.chat_ctx == []                            # no message added
    assert all(text not in clip_texts for text in session.chat_ctx)


async def test_closing_stops_the_sound_and_the_timer():
    player, session = FakePlayer(), FakeSession()
    fillers = make_fillers(player, session)

    session.agent_state = "thinking"
    session.emit("conversation_item_added", item_added(Item("user", "Vad är 3/4?")))
    await settle()
    await fillers.aclose()
    assert player.last_handle.stopped is True

    session.emit("conversation_item_added", item_added(Item("user", "Och sen?")))
    await settle()
    assert len(player.played) == 1


# ---- clips -----------------------------------------------------------------------


def pcm(*, seconds: float = 0.5, sample_rate: int = 24000, amplitude: int = 8000,
        silence_head: float = 0.2, silence_tail: float = 0.2, channels: int = 1) -> bytes:
    head = int(silence_head * sample_rate)
    body = int(seconds * sample_rate)
    tail = int(silence_tail * sample_rate)
    samples = [0] * head
    for index in range(body):
        samples.append(amplitude if index % 2 else -amplitude)
    samples.extend([0] * tail)
    if channels == 2:
        samples = [value for value in samples for _ in range(2)]
    return struct.pack(f"<{len(samples)}h", *samples)


def test_trim_silence_keeps_only_the_sound():
    trimmed = trim_silence(pcm(seconds=0.4, silence_head=0.3, silence_tail=0.3), 24000, 1)
    duration = clip_duration(trimmed, 24000, 1)
    assert 0.35 <= duration <= 0.5  # the 0.4 s sound plus a little air


def test_clip_problem_rejects_silence_and_wrong_lengths():
    assert clip_problem(b"", 24000, 1) == "empty"
    silent = struct.pack("<24000h", *([0] * 24000))  # one second of nothing
    assert clip_problem(silent, 24000, 1) == "too quiet (peak 0)"
    short = pcm(seconds=0.05, silence_head=0, silence_tail=0)
    assert clip_problem(short, 24000, 1).startswith("too short")
    long = pcm(seconds=2.0, silence_head=0, silence_tail=0)
    assert clip_problem(long, 24000, 1).startswith("too long")
    assert clip_problem(pcm(seconds=0.5, silence_head=0, silence_tail=0), 24000, 1) is None


def test_clip_duration_handles_stereo():
    stereo = pcm(seconds=0.5, silence_head=0, silence_tail=0, channels=2)
    assert clip_duration(stereo, 24000, 2) == pytest.approx(0.5, abs=0.01)


def test_energy_segments_separate_one_hum_from_two_parts():
    hum = pcm(seconds=0.4, silence_head=0.05, silence_tail=0.05)
    assert len(energy_segments(hum, 24000, 1)) == 1
    two_parts = (pcm(seconds=0.15, silence_head=0, silence_tail=0.12)
                 + pcm(seconds=0.2, silence_head=0, silence_tail=0))
    assert len(energy_segments(two_parts, 24000, 1)) == 2
    assert energy_segments(b"", 24000, 1) == []


def test_voice_fingerprint_changes_with_the_voice():
    class Engine:
        provider = "deepgram"
        model = "flux-ludvig-sv"
        expressivity = 1

    other = type("Other", (Engine,), {"model": "flux-other-sv"})
    louder = type("Louder", (Engine,), {"expressivity": 2})
    assert voice_fingerprint(Engine()) == voice_fingerprint(Engine())
    assert voice_fingerprint(Engine()) != voice_fingerprint(other())
    assert voice_fingerprint(Engine()) != voice_fingerprint(louder())
