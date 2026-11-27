"""Hold the turn open while a child trails off mid-thought (2026-11-27).

With ``turn_detection="stt"`` the tutor answered ``min_delay`` (0.6 s) after
Soniox's endpoint, whatever the child had said. A child who paused on a filler
or an open "att" to think was cut off.

How it works: turn detection stays exactly ``"stt"``. ``hold_hesitations``
wraps the Soniox event stream (``Tutor.stt_node``). Soniox sends one
``FINAL_TRANSCRIPT`` at its endpoint, immediately followed by
``END_OF_SPEECH``, and in ``stt`` mode that end event is what lets LiveKit
close the turn. When the words of the turn so far look unfinished
(``hesitation_reason``), the end event is held back for ``hold_s`` seconds
(``TUTOR_MAX_ENDPOINT - TUTOR_MIN_ENDPOINT``, 2.2 s by default):

* the child carries on (Soniox sends ``START_OF_SPEECH`` or more words): the
  held end event is dropped, the new words join the same turn, and the next
  endpoint is judged again on the whole turn;
* the child stays silent: the end event goes out and LiveKit ends the turn as
  before, ``min_delay`` after the speech ended (already elapsed by then).

So a hesitation always gets at least ``hold_s`` after Soniox's endpoint, more
than ``main`` ever gave it, and a complete answer is untouched.

Why not a LiveKit ``_TurnDetector`` (the first take, reviewed and dropped the
same day): passing one switches ``AudioRecognition`` (livekit-agents 1.8.10)
from ``stt`` to VAD-based turn detection, which ignores Soniox's start and end
events. A replay showed an answer that was never committed while Silero still
heard "speech", a fragment committed while Soniox was transcribing the
continuation, and the max delay counted from Silero's last speech, so a slow
Soniox endpoint left a hesitation *less* time than ``main``.

Pure Python, no model, no network.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterable, AsyncIterator, Callable
from typing import Any

from livekit.agents import stt

# Hesitation sounds as Soniox writes them: eh, eeh, ehm, ehum, öh, ööhm, äh,
# hm, hmmm, um, uh, uhm (lower case, letters only).
_FILLER_SOUND = re.compile(r"^(?:[eöä]+h+(?:u?m+)?|e+m+|ö+m+|h+m+|m{2,}h*|u+h*m*|u+h+)$")
FILLER_WORDS = frozenset({"asså", "alltså", "liksom", "typ"})
# "Mm" / "Mhm" said alone is a Swedish yes, not a hesitation: a lone one is an
# answer. After other words ("det är, mm") it is a filler again.
AFFIRMATIVE_ALONE = frozenset({"mm", "mmm", "mhm", "mhmm", "mmh"})

# Words that cannot end a Swedish statement: a turn that stops on one is
# unfinished even when the recogniser put a full stop after it.
OPEN_ALWAYS = frozenset({
    "att", "och", "men", "eller", "som", "eftersom", "när", "medan", "samt",
})
# Words that usually leave a sentence open but can end one: "En till." (one
# more), "Stäng av.", "Det kan jag.", "Jag vet det.", and a lone "Ett." is a
# number. They hold only when the turn has more than one word and the
# recogniser did not close it with a full stop or an exclamation mark.
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
_CLOSED = re.compile(r"[.!]\s*$")
_QUESTION = re.compile(r"\?[\s\"'»«”“’‘)\]]*$")


def is_filler(word: str) -> bool:
    return word in FILLER_WORDS or bool(_FILLER_SOUND.match(word))


def hesitation_reason(text: str) -> str | None:
    """Why this turn looks unfinished, or None when it looks complete.

    Reasons are fixed words (``filler``, ``open_word``, ``trailing``), safe for
    the debug log; the text itself never leaves this function. A turn that
    ends with a question mark is a question, never a hesitation."""
    text = (text or "").strip()
    if not text or _QUESTION.search(text):
        return None
    words = [w.lower() for w in _WORD.findall(text)]
    if not words:
        return "trailing" if _TRAILING_OPEN_PUNCT.search(text) else None
    last = words[-1]
    if len(words) == 1 and last in AFFIRMATIVE_ALONE and not _TRAILING_OPEN_PUNCT.search(text):
        return None
    if is_filler(last):
        return "filler"
    if _TRAILING_OPEN_PUNCT.search(text):
        return "trailing"
    if last in OPEN_ALWAYS:
        return "open_word"
    if last in OPEN_UNLESS_CLOSED and len(words) > 1 and not _CLOSED.search(text):
        return "open_word"
    return None


def _words(event: Any) -> str:
    alternatives = getattr(event, "alternatives", None) or []
    return (getattr(alternatives[0], "text", "") or "").strip() if alternatives else ""


_RESUME = (stt.SpeechEventType.START_OF_SPEECH, stt.SpeechEventType.INTERIM_TRANSCRIPT,
           stt.SpeechEventType.PREFLIGHT_TRANSCRIPT, stt.SpeechEventType.FINAL_TRANSCRIPT)


async def hold_hesitations(events: AsyncIterable[Any], *, hold_s: float,
                           record: Callable[[str, dict[str, Any]], None] | None = None
                           ) -> AsyncIterator[Any]:
    """Pass STT events through, holding back an ``END_OF_SPEECH`` that closes
    an unfinished-sounding turn for up to ``hold_s`` seconds (see the module
    docstring). ``record`` gets ``turn_hold`` / ``turn_hold_resumed`` events
    with a reason word and counts only, never the words."""

    def log(kind: str, data: dict[str, Any]) -> None:
        if record is None:
            return
        try:
            record(kind, data)
        except Exception:  # noqa: BLE001 - logging never changes the turn
            pass

    iterator = aiter(events)
    pending: asyncio.Future[Any] | None = None
    finals: list[str] = []
    held: Any = None
    held_until = 0.0
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(anext(iterator))
            timeout = max(0.0, held_until - time.monotonic()) if held is not None else None
            done, _ = await asyncio.wait({pending}, timeout=timeout)
            if not done:
                # Silence through the whole hold: the turn ends now.
                yield held
                held = None
                finals.clear()
                continue
            future, pending = pending, None
            try:
                event = future.result()
            except StopAsyncIteration:
                if held is not None:
                    yield held
                return
            except BaseException:
                # A stream error must not swallow the end of a held turn:
                # LiveKit recreates the stream and would wait for an end
                # event that never comes.
                if held is not None:
                    yield held
                raise
            kind = getattr(event, "type", None)
            if held is not None and kind in _RESUME and (
                    kind == stt.SpeechEventType.START_OF_SPEECH or _words(event)):
                # The child carried on: this turn is not over. The next
                # endpoint closes it, judged on all of its words.
                log("turn_hold_resumed", {"held_s": round(hold_s - (held_until - time.monotonic()), 2)})
                held = None
            if kind == stt.SpeechEventType.FINAL_TRANSCRIPT and _words(event):
                finals.append(_words(event))
            elif kind == stt.SpeechEventType.END_OF_SPEECH:
                text = " ".join(finals)
                reason = hesitation_reason(text) if hold_s > 0 else None
                if reason is not None:
                    held, held_until = event, time.monotonic() + hold_s
                    log("turn_hold", {"reason": reason, "words": len(_WORD.findall(text))})
                    continue
                finals.clear()
            yield event
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            # The generator must not be running when it is closed.
            await asyncio.wait({pending})
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:  # noqa: BLE001 - the inner stream is closing anyway
                pass
