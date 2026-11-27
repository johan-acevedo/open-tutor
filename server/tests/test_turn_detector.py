"""Holding the turn while a child trails off (2026-11-27).

A child who paused mid-thought on a filler or an open "att" was cut off 0.6 s
after the recogniser's endpoint. These tests pin which turns are held (and
which are not, so a complete short answer stays snappy), the event gate that
holds Soniox's end-of-speech back, and -- against the installed livekit-agents
in its unchanged ``stt`` mode -- that a real ``AudioRecognition`` commits a
hesitation only after the hold, a complete answer at ``min_delay``, and joins
the words that follow a hesitation into the same turn.
"""

import asyncio
import time
from types import SimpleNamespace

import pytest
from livekit.agents import AgentSession, TurnHandlingOptions, llm, stt
from livekit.agents.voice.audio_recognition import AudioRecognition
from livekit.agents.voice.endpointing import create_endpointing

from open_tutor import debug_log
from open_tutor.agent import Tutor, hesitation_hold_s, turn_detection_options
from open_tutor.turn_detector import hesitation_reason, hold_hesitations, is_filler

S = stt.SpeechEventType


# ---- which turns are held --------------------------------------------------

@pytest.mark.parametrize("text, reason", [
    ("Eh", "filler"),
    ("Eh.", "filler"),
    ("Öh,", "filler"),
    ("Hmm...", "filler"),
    ("Ehum", "filler"),
    ("Eeeh", "filler"),
    ("Ööhm.", "filler"),
    ("Asså", "filler"),
    ("Det är typ", "filler"),
    ("Jag tror att, eh.", "filler"),
    ("Öh, för att", "open_word"),
    ("Öh, för att...", "trailing"),
    ("Triangeln har tre hörn och", "open_word"),
    ("Jag vet inte om", "open_word"),
    ("Det blir fem eller", "open_word"),
    ("En kvadrat är en form som.", "open_word"),
    ("Det är", "open_word"),
    ("Jag tror den", "open_word"),
    ("Fem gånger", "open_word"),
    ("Det är sex,", "trailing"),
    ("Det är sex…", "trailing"),
    ("Det är sex -", "trailing"),
    ("Det är sex –", "trailing"),
    ("...", "trailing"),
])
def test_unfinished_turns_are_held(text, reason):
    assert hesitation_reason(text) == reason


@pytest.mark.parametrize("text", [
    "Ja.", "Nej.", "Ja", "Nej", "Noa.", "Det är fyra hörn.", "Nej, jag vet inte.",
    "Sex.", "42", "Mm.", "Mhm", "En.", "Ett", "Jag.", "Det kan jag.", "En till.",
    "Stäng av.", "Jag sitter fast.", "Minus.", "När?", "Ja, eller?", "Varför då?",
    "Vilken typ?", "Eh?", "Okej, jag fattar!", "Hej", "", "   ",
])
def test_complete_answers_are_not(text):
    assert hesitation_reason(text) is None


@pytest.mark.parametrize("word, filler", [
    ("eh", True), ("ehm", True), ("ehum", True), ("öhh", True), ("äh", True), ("hmmm", True),
    ("um", True), ("uhm", True), ("mmh", True), ("typ", True),
    ("hej", False), ("en", False), ("men", False), ("eller", False), ("mhm", False),
])
def test_filler_sounds(word, filler):
    assert is_filler(word) is filler


# ---- configuration -----------------------------------------------------------

def test_turn_detection_stays_exactly_stt():
    for env in ({}, {"TUTOR_TURN_DETECTION": "stt"}, {"TUTOR_TURN_DETECTION": "hesitation"}):
        assert turn_detection_options(env) == {
            "turn_detection": "stt", "endpointing": {"min_delay": 0.6, "max_delay": 4.0}}
    assert turn_detection_options({"TUTOR_MIN_ENDPOINT": "0.8"})["endpointing"]["min_delay"] == 0.8


def test_the_hold_is_on_by_default_and_off_in_stt_mode():
    assert hesitation_hold_s({}) == pytest.approx(2.2)
    assert hesitation_hold_s({"TUTOR_TURN_DETECTION": "STT"}) == 0.0
    assert hesitation_hold_s({"TUTOR_MIN_ENDPOINT": "0.5", "TUTOR_MAX_ENDPOINT": "3.5"}) == 3.0
    assert hesitation_hold_s({"TUTOR_MAX_ENDPOINT": "0.1"}) == 0.0  # never below min
    assert hesitation_hold_s({"TUTOR_MAX_ENDPOINT": "lång"}) == pytest.approx(2.2)


def test_an_unknown_mode_fails_at_startup():
    with pytest.raises(ValueError, match="TUTOR_TURN_DETECTION"):
        turn_detection_options({"TUTOR_TURN_DETECTION": "vad"})


def test_both_settings_reach_the_debug_log_config():
    assert "TUTOR_TURN_DETECTION" in debug_log.SAFE_CONFIG_KEYS
    assert "TUTOR_MAX_ENDPOINT" in debug_log.SAFE_CONFIG_KEYS


def test_the_tutor_wraps_its_stt_node_only_when_holding(monkeypatch):
    from livekit.agents import Agent

    sentinel = object()
    monkeypatch.setattr(Agent.default, "stt_node", lambda agent, audio, settings: sentinel)
    monkeypatch.setenv("TUTOR_TURN_DETECTION", "stt")
    assert Tutor.stt_node(SimpleNamespace(), None, None) is sentinel
    monkeypatch.setenv("TUTOR_TURN_DETECTION", "hesitation")
    wrapped = Tutor.stt_node(SimpleNamespace(), None, None)
    assert wrapped is not sentinel and hasattr(wrapped, "__anext__")


async def test_agent_session_accepts_the_options():
    session = AgentSession(turn_handling=TurnHandlingOptions(**turn_detection_options({})))
    assert session.turn_detection == "stt"


# ---- the event gate -----------------------------------------------------------

def start():
    return stt.SpeechEvent(type=S.START_OF_SPEECH)


def final(text, language="sv"):
    return stt.SpeechEvent(type=S.FINAL_TRANSCRIPT, alternatives=[
        stt.SpeechData(language=language, text=text, confidence=0.9)])


def interim(text):
    return stt.SpeechEvent(type=S.INTERIM_TRANSCRIPT, alternatives=[
        stt.SpeechData(language="sv", text=text, confidence=0.5)])


def end():
    return stt.SpeechEvent(type=S.END_OF_SPEECH)


class Source:
    """A Soniox-shaped event stream the test pushes into."""

    def __init__(self):
        self.queue = asyncio.Queue()
        self.closed = False

    def push(self, *events):
        for event in events:
            self.queue.put_nowait(event)

    async def events(self):
        try:
            while True:
                event = await self.queue.get()
                if event is None:
                    return
                if isinstance(event, BaseException):
                    raise event
                yield event
        finally:
            self.closed = True


async def collect(gate, out):
    try:
        async for event in gate:
            out.append((time.monotonic(), event))
    except Exception as error:  # noqa: BLE001
        out.append((time.monotonic(), error))


async def test_a_complete_answer_passes_straight_through():
    source, out = Source(), []
    task = asyncio.create_task(collect(hold_hesitations(source.events(), hold_s=1.0), out))
    source.push(start(), final("Sex."), end(), None)
    await asyncio.wait_for(task, 1.0)
    assert [e.type for _, e in out] == [S.START_OF_SPEECH, S.FINAL_TRANSCRIPT, S.END_OF_SPEECH]


async def test_a_hesitation_holds_the_end_event_for_the_hold():
    source, out, recorded = Source(), [], []
    gate = hold_hesitations(source.events(), hold_s=0.3,
                            record=lambda kind, data: recorded.append((kind, data)))
    task = asyncio.create_task(collect(gate, out))
    t0 = time.monotonic()
    source.push(start(), final("Jag tror att"), end())
    await asyncio.sleep(0.15)
    assert [e.type for _, e in out] == [S.START_OF_SPEECH, S.FINAL_TRANSCRIPT]
    await asyncio.sleep(0.25)
    assert out[-1][1].type == S.END_OF_SPEECH and out[-1][0] - t0 >= 0.3
    assert recorded == [("turn_hold", {"reason": "open_word", "words": 3})]
    source.push(None)
    await asyncio.wait_for(task, 1.0)


async def test_carrying_on_drops_the_held_end_and_judges_the_whole_turn():
    source, out, recorded = Source(), [], []
    gate = hold_hesitations(source.events(), hold_s=0.5,
                            record=lambda kind, data: recorded.append((kind, data)))
    task = asyncio.create_task(collect(gate, out))
    source.push(start(), final("Öh, för att"), end())
    await asyncio.sleep(0.1)
    source.push(start(), interim("den"), final("den har fyra hörn."), end(), None)
    await asyncio.wait_for(task, 1.0)
    types = [e.type for _, e in out]
    assert types.count(S.END_OF_SPEECH) == 1 and types[-1] == S.END_OF_SPEECH
    assert [kind for kind, _ in recorded] == ["turn_hold", "turn_hold_resumed"]


async def test_usage_events_do_not_cancel_a_hold():
    source, out = Source(), []
    task = asyncio.create_task(collect(hold_hesitations(source.events(), hold_s=0.2), out))
    source.push(start(), final("Eh"), end(),
                stt.SpeechEvent(type=S.RECOGNITION_USAGE))
    await asyncio.sleep(0.35)
    assert [e.type for _, e in out][-2:] == [S.RECOGNITION_USAGE, S.END_OF_SPEECH]
    source.push(None)
    await asyncio.wait_for(task, 1.0)


async def test_a_stream_that_ends_or_fails_never_swallows_a_held_end():
    source, out = Source(), []
    task = asyncio.create_task(collect(hold_hesitations(source.events(), hold_s=5.0), out))
    source.push(start(), final("Eh"), end(), None)
    await asyncio.wait_for(task, 1.0)
    assert out[-1][1].type == S.END_OF_SPEECH

    source, out = Source(), []
    task = asyncio.create_task(collect(hold_hesitations(source.events(), hold_s=5.0), out))
    source.push(start(), final("Eh"), end(), RuntimeError("socket closed"))
    await asyncio.wait_for(task, 1.0)
    assert out[-2][1].type == S.END_OF_SPEECH and isinstance(out[-1][1], RuntimeError)


async def test_closing_the_gate_closes_the_inner_stream():
    source = Source()
    gate = hold_hesitations(source.events(), hold_s=1.0)
    source.push(start())
    assert (await anext(gate)).type == S.START_OF_SPEECH
    reader = asyncio.ensure_future(anext(gate))  # waits on the inner stream
    await asyncio.sleep(0.01)
    reader.cancel()
    await asyncio.wait({reader})
    await gate.aclose()
    assert source.closed


# ---- a real AudioRecognition in stt mode, fed through the gate -----------------

class Hooks:
    """The RecognitionHooks AgentActivity provides, reduced to a recorder."""

    interruption_by_audio_activity_enabled = True

    def __init__(self):
        self.turns = []

    def retrieve_chat_ctx(self):
        chat = llm.ChatContext.empty()
        chat.add_message(role="assistant", content=["Hur många hörn har en kvadrat?"])
        return chat

    def on_end_of_turn(self, info):
        self.turns.append((time.monotonic(), info.new_transcript))
        return True

    def __getattr__(self, name):  # every other hook is a no-op here
        if name.startswith("on_"):
            return lambda *args, **kwargs: None
        raise AttributeError(name)


async def recognition(hold_s=0.5, min_delay=0.05):
    session = AgentSession(turn_handling=TurnHandlingOptions(
        turn_detection="stt", endpointing={"min_delay": min_delay, "max_delay": 4.0}))
    hooks = Hooks()

    async def stt_node(audio, model_settings):  # never pulled: no start()
        yield

    rec = AudioRecognition(
        session, hooks=hooks, stt=stt_node, vad=None, interruption_detection=None,
        endpointing=create_endpointing(session.options.turn_handling["endpointing"]),
        turn_detection=session.turn_detection)
    assert rec._turn_detection_mode == "stt"
    source = Source()

    async def pump():
        async for event in hold_hesitations(source.events(), hold_s=hold_s):
            await rec._on_stt_event(event)

    return source, hooks, asyncio.create_task(pump())


async def wait_for_turn(hooks, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not hooks.turns and time.monotonic() < deadline:
        await asyncio.sleep(0.01)


@pytest.mark.parametrize("language", ["sv", "sv-SE", ""])
async def test_real_recognition_commits_a_hesitation_after_the_hold(language):
    source, hooks, task = await recognition()
    t0 = time.monotonic()
    source.push(start(), final("Öh, för att", language), end())
    await asyncio.sleep(0.3)
    assert hooks.turns == []  # min_delay alone would have ended it by now
    await wait_for_turn(hooks)
    assert hooks.turns and hooks.turns[0][0] - t0 >= 0.5
    source.push(None)
    await asyncio.wait_for(task, 1.0)


async def test_real_recognition_ends_a_complete_answer_at_min_delay():
    source, hooks, task = await recognition()
    t0 = time.monotonic()
    source.push(start(), final("Sex."), end())
    await wait_for_turn(hooks)
    assert hooks.turns and hooks.turns[0][0] - t0 < 0.3
    assert hooks.turns[0][1] == "Sex."
    source.push(None)
    await asyncio.wait_for(task, 1.0)


async def test_real_recognition_joins_the_words_after_a_hesitation():
    source, hooks, task = await recognition()
    source.push(start(), final("Öh, för att"), end())
    await asyncio.sleep(0.2)
    source.push(start(), final("den har fyra hörn."), end())
    await wait_for_turn(hooks)
    await asyncio.sleep(0.2)
    assert [text for _, text in hooks.turns] == ["Öh, för att den har fyra hörn."]
    source.push(None)
    await asyncio.wait_for(task, 1.0)
