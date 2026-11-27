"""Hold the turn open while a child trails off mid-thought (2026-11-27).

With ``turn_detection="stt"`` the tutor answered 0.6 s after the recogniser's
endpoint, whatever the child had said. A child who paused on a filler or an open "att" to
think was cut off. This detector reads the words of the turn so far and tells
LiveKit how likely it is that the turn is over:

* clearly unfinished (only filler sounds, ends on a filler, on a word that
  cannot end a Swedish sentence, or on a comma, dash or ellipsis): 0.05, below
  the 0.5 threshold, so LiveKit waits ``max_delay`` (``TUTOR_MAX_ENDPOINT``,
  2.8 s) of silence before the tutor speaks;
* anything else: 0.95, so a complete answer still gets the fast ``min_delay``.

Pure Python, no model, no network: one call costs microseconds.

How LiveKit uses it (livekit-agents 1.8.10, ``voice/audio_recognition.py``):
an object passed as ``TurnHandlingOptions(turn_detection=...)`` that is not a
string and not a streaming detector is the ``_TurnDetector`` protocol. It turns
the recognition into VAD-based turn detection (``_turn_detection_mode`` is
None): the turn can end once Silero has heard silence and Soniox has sent its
final transcript (Soniox only finalises at its own endpoint, so that endpoint
still gates the turn). ``_run_eou_detection`` then calls
``supports_language(last_language)``, ``predict_end_of_turn(chat_ctx)`` with
the turn's transcript appended as the last user message, and
``unlikely_threshold(last_language)``; a probability below the threshold swaps
``min_delay`` for ``max_delay``, counted from the end of the child's speech.
Speech that resumes cancels the wait and the new words join the same turn.
``model`` and ``provider`` only label metrics. Soniox reports languages as
ISO codes ("sv"), and the language can also be empty before the first final
transcript, so every language is accepted: the word lists are Swedish, and a
non-Swedish turn simply ends as fast as before.
"""

from __future__ import annotations

import re
from typing import Any

# Below LiveKit's threshold: wait max_delay. Above it: min_delay.
UNLIKELY_THRESHOLD = 0.5
HOLD_PROBABILITY = 0.05
DONE_PROBABILITY = 0.95

# Hesitation sounds as Soniox writes them (lower case, letters only).
FILLERS = frozenset({
    "eh", "ehh", "ehm", "öh", "öhh", "öhm", "äh", "ähh", "ähm", "hm", "hmm", "hmmm",
    "mm", "mmm", "um", "umm", "uh", "uhm", "asså", "alltså", "liksom", "typ",
})
# "Mm" / "Mhm" said alone is a Swedish yes, not a hesitation: a lone one is an
# answer. After other words ("det är, mm") it is a filler again.
AFFIRMATIVE_ALONE = frozenset({"mm", "mmm", "mhm", "mhmm"})

# Words that cannot end a Swedish statement: a turn that stops on one is
# unfinished even when the recogniser put a full stop after it. A question
# mark still ends it ("När?", "Ja, eller?").
OPEN_ALWAYS = frozenset({
    "att", "och", "men", "eller", "som", "eftersom", "när", "medan", "samt",
})
# Words that usually leave a sentence open but can end one: "En till." (one
# more), "Stäng av.", "Det kan jag.", "Jag vet det.", and a lone "Ett." is a
# number. They hold only when the turn has more than one word and the
# recogniser did not close it with a full stop, question or exclamation mark.
OPEN_UNLESS_CLOSED = frozenset({
    "så", "för", "om", "med", "på", "i", "av", "till", "från", "vid", "under", "över",
    "mellan", "efter", "innan", "utan", "hos", "mot", "genom", "då", "sen", "sedan",
    "är", "var", "har", "hade", "kan", "kunde", "ska", "skulle", "vill", "måste",
    "blir", "blev", "heter", "får", "brukar", "tror", "tänker",
    "jag", "du", "det", "den", "de", "vi", "ni", "han", "hon", "man",
    "en", "ett", "min", "mitt", "mina", "din", "ditt", "sin", "sitt", "fast",
    "plus", "minus", "gånger", "delat",
})

_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*|\d+")
_TRAILING_OPEN_PUNCT = re.compile(r"(?:,|;|:|…|\.\.|-|–|—)\s*$")
_CLOSED = re.compile(r"[.!?]\s*$")


def latest_user_text(chat_ctx: Any) -> str:
    """The text of the newest message when it is the learner's, else ''."""
    try:
        items = list(chat_ctx.items)
    except Exception:  # noqa: BLE001 - no context: nothing to hold on
        return ""
    for item in reversed(items):
        if getattr(item, "type", None) != "message":
            continue
        if getattr(item, "role", None) != "user":
            return ""
        return (getattr(item, "text_content", None) or "").strip()
    return ""


def hesitation_reason(text: str) -> str | None:
    """Why this turn looks unfinished, or None when it looks complete.

    Reasons are fixed words (``filler``, ``open_word``, ``trailing``), safe for
    the debug log; the text itself never leaves this function."""
    text = (text or "").strip()
    if not text:
        return None
    words = [w.lower() for w in _WORD.findall(text)]
    if not words:
        return "trailing" if _TRAILING_OPEN_PUNCT.search(text) else None
    last = words[-1]
    if len(words) == 1 and last in AFFIRMATIVE_ALONE and not _TRAILING_OPEN_PUNCT.search(text):
        return None
    if all(w in FILLERS for w in words) or last in FILLERS:
        return "filler"
    if _TRAILING_OPEN_PUNCT.search(text):
        return "trailing"
    if last in OPEN_ALWAYS and not text.endswith("?"):
        return "open_word"
    if last in OPEN_UNLESS_CLOSED and len(words) > 1 and not _CLOSED.search(text):
        return "open_word"
    return None


class SwedishHesitationTurnDetector:
    """LiveKit ``_TurnDetector``: holds the turn on a Swedish hesitation.

    ``record`` (optional) gets ``("turn_hold", {"reason", "words"})`` for every
    held prediction: counts and a fixed reason word, never the child's words.
    """

    def __init__(self, record: Any = None) -> None:
        self._record = record

    @property
    def model(self) -> str:
        return "swedish-hesitation"

    @property
    def provider(self) -> str:
        return "open-tutor"

    async def unlikely_threshold(self, language: Any = None) -> float | None:
        return UNLIKELY_THRESHOLD

    async def supports_language(self, language: Any = None) -> bool:
        return True

    async def predict_end_of_turn(self, chat_ctx: Any, *, timeout: float | None = None) -> float:
        text = latest_user_text(chat_ctx)
        reason = hesitation_reason(text)
        if reason is None:
            return DONE_PROBABILITY
        if self._record is not None:
            try:
                self._record("turn_hold", {"reason": reason,
                                           "words": len(_WORD.findall(text))})
            except Exception:  # noqa: BLE001 - logging never changes the turn
                pass
        return HOLD_PROBABILITY
