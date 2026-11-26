"""Idle-silence timeout: end a forgotten open tab, gently.

Children think and write silently, so the timeout is generous (20 minutes by
default): it only catches a tab everyone walked away from. Any sign of the
learner — speech (final or interim transcript), typed chat, homework upload,
a page answer, a mic-button press — resets the clock. The tutor speaking
alone never resets it, and the timeout never fires mid-speech: the check
waits until the tutor is quiet first.

``IdleWatch`` is pure (an injectable clock) so the policy is unit-testable
without a session; agent.py only wires learner events to ``note_activity``
and polls ``expired`` from a background task.
"""

from __future__ import annotations

import os
import time
from typing import Callable

#: Default minutes of learner silence before the call ends itself.
IDLE_TIMEOUT_DEFAULT_S = 1200.0

#: How often the worker checks the clock (seconds). Firing may lag the
#: deadline by up to this much; 30 s is invisible against a 20-minute budget.
IDLE_POLL_S = 30.0


def idle_timeout_s(environ: dict[str, str] | None = None) -> float:
    """Seconds of learner silence before the call ends itself.

    ``TUTOR_IDLE_TIMEOUT_S``, default 1200 (20 minutes). Zero or negative
    disables the timeout entirely.
    """
    env = os.environ if environ is None else environ
    try:
        return float(env.get("TUTOR_IDLE_TIMEOUT_S", IDLE_TIMEOUT_DEFAULT_S))
    except (ValueError, TypeError, AttributeError):
        return IDLE_TIMEOUT_DEFAULT_S


class IdleWatch:
    """Tracks learner silence with an injectable clock (tests pass a fake)."""

    def __init__(self, timeout_s: float = IDLE_TIMEOUT_DEFAULT_S,
                 clock: Callable[[], float] | None = None) -> None:
        self._timeout = timeout_s
        self._clock = clock or time.monotonic
        self._last_activity = self._clock()

    @property
    def timeout_s(self) -> float:
        return self._timeout

    @property
    def enabled(self) -> bool:
        return self._timeout > 0

    def note_activity(self) -> None:
        """The learner did something: restart the silence clock."""
        self._last_activity = self._clock()

    def seconds_since_activity(self) -> float:
        return self._clock() - self._last_activity

    def expired(self, *, speaking: bool = False) -> bool:
        """True when the call should end for idleness.

        Never fires while disabled, and never while the tutor is mid-speech:
        the caller defers the check until the tutor is quiet instead of
        cutting a sentence off.
        """
        if not self.enabled:
            return False
        if speaking:
            return False
        return self.seconds_since_activity() >= self._timeout
