"""The Swedish hesitation turn detector (2026-11-27).

A child who paused mid-thought on a filler or an open "att" was cut off 0.6 s after the recogniser's
endpoint. These tests pin which turns are held (and which are not, so a
complete short answer stays snappy), how the detector meets LiveKit's
``_TurnDetector`` protocol, and -- against the installed livekit-agents --
that a real ``AudioRecognition`` fed Soniox-shaped final transcripts waits
``max_delay`` on a hesitation and ``min_delay`` on a complete answer.
"""

import asyncio
import time

import pytest
from livekit.agents import AgentSession, TurnHandlingOptions, llm, stt
from livekit.agents.voice.audio_recognition import AudioRecognition
from livekit.agents.voice.endpointing import create_endpointing
from livekit.agents.voice.turn import _StreamingTurnDetector

from open_tutor import debug_log
from open_tutor.agent import turn_detection_options
from open_tutor.turn_detector import (
    DONE_PROBABILITY,
    HOLD_PROBABILITY,
    UNLIKELY_THRESHOLD,
    SwedishHesitationTurnDetector,
    hesitation_reason,
    latest_user_text,
)


def ctx(*messages):
    chat = llm.ChatContext.empty()
    for role, text in messages:
        chat.add_message(role=role, content=[text])
    return chat


# ---- which turns are held --------------------------------------------------

@pytest.mark.parametrize("text, reason", [
    ("Eh", "filler"),
    ("Eh.", "filler"),
    ("Öh,", "filler"),
    ("Hmm...", "filler"),
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
    "Okej, jag fattar!", "", "   ",
])
def test_complete_answers_are_not(text):
    assert hesitation_reason(text) is None


def test_latest_user_text_reads_only_a_trailing_learner_message():
    assert latest_user_text(ctx(("assistant", "Vad tror du?"), ("user", "Öh, för att"))) == "Öh, för att"
    assert latest_user_text(ctx(("user", "Eh"), ("assistant", "Mm?"))) == ""
    assert latest_user_text(ctx()) == ""
    assert latest_user_text(object()) == ""


# ---- the _TurnDetector protocol --------------------------------------------

@pytest.mark.parametrize("language", [None, "", "sv", "sv-SE", "en"])
async def test_every_language_is_supported_with_one_threshold(language):
    detector = SwedishHesitationTurnDetector()
    assert await detector.supports_language(language) is True
    assert await detector.unlikely_threshold(language) == UNLIKELY_THRESHOLD


async def test_predictions_fall_on_either_side_of_the_threshold():
    detector = SwedishHesitationTurnDetector()
    held = await detector.predict_end_of_turn(ctx(("assistant", "Hur många?"), ("user", "Öh, för att")))
    done = await detector.predict_end_of_turn(ctx(("assistant", "Hur många?"), ("user", "Sex.")),
                                              timeout=1.0)
    assert held == HOLD_PROBABILITY < UNLIKELY_THRESHOLD < DONE_PROBABILITY == done


async def test_a_hold_is_logged_without_the_childs_words():
    recorded = []
    detector = SwedishHesitationTurnDetector(record=lambda kind, data: recorded.append((kind, data)))
    await detector.predict_end_of_turn(ctx(("user", "Jag tror att")))
    await detector.predict_end_of_turn(ctx(("user", "Sex.")))
    assert recorded == [("turn_hold", {"reason": "open_word", "words": 3})]


async def test_a_broken_logger_never_changes_the_turn():
    def boom(kind, data):
        raise RuntimeError("log down")

    detector = SwedishHesitationTurnDetector(record=boom)
    assert await detector.predict_end_of_turn(ctx(("user", "Eh"))) == HOLD_PROBABILITY


def test_it_is_a_plain_turn_detector_not_a_streaming_one():
    detector = SwedishHesitationTurnDetector()
    assert not isinstance(detector, _StreamingTurnDetector)
    assert detector.model and detector.provider


# ---- configuration -----------------------------------------------------------

def test_hesitation_is_the_default():
    options = turn_detection_options({})
    assert isinstance(options["turn_detection"], SwedishHesitationTurnDetector)
    assert options["endpointing"] == {"min_delay": 0.6, "max_delay": 2.8}
    assert options["preemptive_generation"] == {"enabled": False}


def test_stt_restores_the_exact_old_settings():
    assert turn_detection_options({"TUTOR_TURN_DETECTION": "stt"}) == {
        "turn_detection": "stt", "endpointing": {"min_delay": 0.6, "max_delay": 4.0}}
    assert turn_detection_options({"TUTOR_TURN_DETECTION": "STT", "TUTOR_MIN_ENDPOINT": "0.8"})[
        "endpointing"] == {"min_delay": 0.8, "max_delay": 4.0}


def test_the_endpoints_are_configurable_and_sane():
    options = turn_detection_options({"TUTOR_MIN_ENDPOINT": "0.5", "TUTOR_MAX_ENDPOINT": "3.5"})
    assert options["endpointing"] == {"min_delay": 0.5, "max_delay": 3.5}
    # A max below the min would end a hesitation sooner than an answer.
    assert turn_detection_options({"TUTOR_MAX_ENDPOINT": "0.1"})["endpointing"]["max_delay"] == 0.6
    assert turn_detection_options({"TUTOR_MAX_ENDPOINT": "lång"})["endpointing"]["max_delay"] == 2.8


def test_an_unknown_mode_fails_at_startup():
    with pytest.raises(ValueError, match="TUTOR_TURN_DETECTION"):
        turn_detection_options({"TUTOR_TURN_DETECTION": "vad"})


def test_both_settings_reach_the_debug_log_config():
    assert "TUTOR_TURN_DETECTION" in debug_log.SAFE_CONFIG_KEYS
    assert "TUTOR_MAX_ENDPOINT" in debug_log.SAFE_CONFIG_KEYS


async def test_agent_session_accepts_the_options():
    options = turn_detection_options({})
    session = AgentSession(turn_handling=TurnHandlingOptions(
        **options,
        interruption={"enabled": True, "mode": "vad", "min_duration": 0.4}))
    turn = session.options.turn_handling
    assert session.turn_detection is options["turn_detection"]
    assert turn["endpointing"]["min_delay"] == 0.6 and turn["endpointing"]["max_delay"] == 2.8
    assert turn["preemptive_generation"]["enabled"] is False


# ---- a real AudioRecognition, fed the way Soniox feeds it --------------------

class Hooks:
    """The RecognitionHooks AgentActivity provides, reduced to a recorder."""

    interruption_by_audio_activity_enabled = True

    def __init__(self, history):
        self.history = history
        self.turns = []
        self.predictions = []

    def retrieve_chat_ctx(self):
        return self.history

    def on_end_of_turn(self, info):
        self.turns.append((time.monotonic(), info.new_transcript))
        return True

    def on_eot_prediction(self, ev):
        self.predictions.append((ev.probability, ev.threshold))

    def __getattr__(self, name):  # every other hook is a no-op here
        if name.startswith("on_"):
            return lambda *args, **kwargs: None
        raise AttributeError(name)


def final(text, language="sv"):
    return stt.SpeechEvent(type=stt.SpeechEventType.FINAL_TRANSCRIPT, alternatives=[
        stt.SpeechData(language=language, text=text, confidence=0.9)])


async def recognition(min_delay=0.05, max_delay=0.6):
    detector = SwedishHesitationTurnDetector()
    session = AgentSession(turn_handling=TurnHandlingOptions(
        turn_detection=detector,
        endpointing={"min_delay": min_delay, "max_delay": max_delay},
        preemptive_generation={"enabled": False}))
    hooks = Hooks(ctx(("assistant", "Hur många hörn har en kvadrat?")))

    async def stt_node(audio, model_settings):  # never pulled: no start()
        yield

    rec = AudioRecognition(
        session, hooks=hooks, stt=stt_node, vad=None, interruption_detection=None,
        endpointing=create_endpointing(session.options.turn_handling["endpointing"]),
        turn_detection=session.turn_detection)
    return rec, hooks


async def wait_for_turn(hooks, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not hooks.turns and time.monotonic() < deadline:
        await asyncio.sleep(0.01)


@pytest.mark.parametrize("language", ["sv", "sv-SE", ""])
async def test_real_recognition_holds_a_hesitation_for_max_delay(language):
    rec, hooks = await recognition()
    assert rec._turn_detection_mode is None  # VAD/final-transcript based, see turn_detector.py
    t0 = time.monotonic()
    await rec._on_stt_event(final("Öh, för att", language))
    await asyncio.sleep(0.25)
    assert hooks.turns == []  # still waiting: min_delay alone would have ended it
    await wait_for_turn(hooks)
    assert hooks.turns and hooks.turns[0][0] - t0 >= 0.5
    assert hooks.predictions == [(HOLD_PROBABILITY, UNLIKELY_THRESHOLD)]


async def test_real_recognition_ends_a_complete_answer_at_min_delay():
    rec, hooks = await recognition()
    t0 = time.monotonic()
    await rec._on_stt_event(final("Sex."))
    await wait_for_turn(hooks)
    assert hooks.turns and hooks.turns[0][0] - t0 < 0.4
    assert hooks.turns[0][1] == "Sex."
    assert hooks.predictions == [(DONE_PROBABILITY, UNLIKELY_THRESHOLD)]


async def test_real_recognition_joins_the_words_after_a_hesitation():
    rec, hooks = await recognition()
    await rec._on_stt_event(final("Öh, för att"))
    await asyncio.sleep(0.2)
    await rec._on_stt_event(final("den har fyra hörn."))
    await wait_for_turn(hooks)
    assert [text for _, text in hooks.turns] == ["Öh, för att den har fyra hörn."]
    assert hooks.predictions[-1] == (DONE_PROBABILITY, UNLIKELY_THRESHOLD)
