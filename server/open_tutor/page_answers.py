"""One reply for what the child sends from a page.

A page can hold several answer boxes, and a child often says the answer aloud while
pressing Skicka. On 2026-11-13 three boxes sent within a second became three prompts and
two overlapping replies, and an answer spoken and sent at the same moment got the same
praise twice. Answers are collected for a short moment and then become one prompt, or,
when the child's own words have just started a reply, only a note in the history.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Awaitable, Callable

SETTLE_S = 1.2  # wait for more boxes from the same page
SPOKEN_WINDOW_S = 4.0  # a spoken turn this close to the answers already gets the reply


def _norm(text: str) -> str:
    """Lower-case words and numbers, decimal comma as point, punctuation dropped."""
    text = re.sub(r"(\d),(\d)", r"\1.\2", (text or "").lower())
    return " ".join(re.findall(r"\d+(?:\.\d+)?|\w+", text))


def answers_text(answers: list[tuple[str, str, str]]) -> str:
    if len(answers) == 1:
        page, part, value = answers[0]
        return f"The child answered on page {page}, part {part}: {value[:500]}"
    lines = "; ".join(f"page {page}, part {part}: {value[:300]}" for page, part, value in answers)
    return f"The child answered several parts at once: {lines}"


class PageAnswers:
    def __init__(
        self,
        prompt: Callable[[str], Any],
        note: Callable[[str], Awaitable[None]],
        record: Callable[[str, dict[str, Any]], None] = lambda *_: None,
        settle_s: float = SETTLE_S,
        spoken_window_s: float = SPOKEN_WINDOW_S,
        clock: Callable[[], float] = time.monotonic,
        wait_free: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._prompt, self._note, self._record = prompt, note, record
        # Waits until neither the tutor nor the child is speaking. A reply
        # requested mid-sentence cuts the tutor off ("the voice interrupted
        # itself", real call 2026-11-19), so the answer waits its turn.
        self._wait_free = wait_free
        self._settle_s, self._spoken_window_s, self._clock = settle_s, spoken_window_s, clock
        self._pending: list[tuple[str, str, str]] = []
        self._task: asyncio.Task | None = None
        # The child's own recent turns (time committed, words) and when the
        # pending batch was first sent. An answer counts as "said aloud" only
        # when a spoken turn since shortly before that send contains it: timing
        # alone mixed up unrelated questions, resends and long turns.
        self._spoken: list[tuple[float, str]] = []
        self._first_add: float | None = None

    def child_spoke(self, text: str = "") -> None:
        """The child's own words were just committed as a turn (they get a reply)."""
        now = self._clock()
        self._spoken = [(t, w) for t, w in self._spoken if now - t <= 120.0] + [(now, text)]

    def _said_aloud(self, answers: list[tuple[str, str, str]]) -> bool:
        """Every sent value appears in the child's spoken turns since just before
        the first send (e.g. "16" typed and "det blir 16" said)."""
        if self._first_add is None:
            return False
        since = self._first_add - self._spoken_window_s
        heard = " ".join(_norm(w) for t, w in self._spoken if t >= since)
        if not heard:
            return False
        padded = f" {heard} "
        return all(_norm(v) and f" {_norm(v)} " in padded for _, _, v in answers)

    def add(self, page: str, part: str, value: str) -> None:
        # A second send from the same box replaces the first.
        self._pending = [a for a in self._pending if (a[0], a[1]) != (page, part)]
        self._pending.append((page, part, value))
        if self._first_add is None:
            self._first_add = self._clock()
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = asyncio.create_task(self._settle(), name="page-answers")

    def close(self) -> None:
        """The session ended: drop pending answers and stop a waiting reply."""
        self._pending = []
        self._first_add = None
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def _settle(self) -> None:
        await asyncio.sleep(self._settle_s)
        if self._wait_free is not None:
            await self._wait_free()
        answers, self._pending = self._pending, []
        if not answers:
            self._first_add = None
            return
        spoken = self._said_aloud(answers)
        self._first_add = None
        text = answers_text(answers)
        self._record("prompt", {"kind": "page_answer", "parts": len(answers),
                                "page": answers[0][0], "reply": not spoken})
        if spoken:
            # The reply to what they said is already on its way: add the answer to the
            # history so the tutor knows it, without asking for a second reply.
            await self._note(f"[{text}. They also said it aloud; one reply is enough.]")
        else:
            self._prompt(f"{text} Respond briefly to what they wrote, in one reply.")
