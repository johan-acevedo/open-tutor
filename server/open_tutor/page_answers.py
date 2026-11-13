"""One reply for what the child sends from a page.

A page can hold several answer boxes, and a child often says the answer aloud while
pressing Skicka. On 2026-11-13 three boxes sent within a second became three prompts and
two overlapping replies, and an answer spoken and sent at the same moment got the same
praise twice. Answers are collected for a short moment and then become one prompt, or,
when the child's own words have just started a reply, only a note in the history.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

SETTLE_S = 1.2  # wait for more boxes from the same page
SPOKEN_WINDOW_S = 4.0  # a spoken turn this close to the answers already gets the reply


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
    ) -> None:
        self._prompt, self._note, self._record = prompt, note, record
        self._settle_s, self._spoken_window_s, self._clock = settle_s, spoken_window_s, clock
        self._pending: list[tuple[str, str, str]] = []
        self._task: asyncio.Task | None = None
        self._last_spoken: float | None = None

    def child_spoke(self) -> None:
        """The child's own words were just committed as a turn (they get a reply)."""
        self._last_spoken = self._clock()

    def add(self, page: str, part: str, value: str) -> None:
        # A second send from the same box replaces the first.
        self._pending = [a for a in self._pending if (a[0], a[1]) != (page, part)]
        self._pending.append((page, part, value))
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = asyncio.create_task(self._settle(), name="page-answers")

    async def _settle(self) -> None:
        await asyncio.sleep(self._settle_s)
        answers, self._pending = self._pending, []
        if not answers:
            return
        text = answers_text(answers)
        spoken = self._last_spoken is not None and (
            self._clock() - self._last_spoken <= self._spoken_window_s + self._settle_s
        )
        self._record("prompt", {"kind": "page_answer", "parts": len(answers),
                                "page": answers[0][0], "reply": not spoken})
        if spoken:
            # The reply to what they said is already on its way: add the answer to the
            # history so the tutor knows it, without asking for a second reply.
            await self._note(f"[{text}. They also said it aloud; one reply is enough.]")
        else:
            self._prompt(f"{text} Respond briefly to what they wrote, in one reply.")
