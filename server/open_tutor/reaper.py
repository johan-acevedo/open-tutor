"""Own provider teardown without putting it on the response path."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine, Iterable
from typing import Any

log = logging.getLogger("open-tutor")


class Reaper:
    def __init__(self, bound: float = 2.0) -> None:
        self.bound = bound
        self.tasks: set[asyncio.Future[Any]] = set()
        self._groups: dict[asyncio.TimerHandle, tuple[str, set[asyncio.Future[Any]]]] = {}

    def stop(self, route: str, tasks: Iterable[asyncio.Future[Any]] = (),
             close: Coroutine[Any, Any, Any] | None = None) -> set[asyncio.Future[Any]]:
        """Cancel work now and start closing, without waiting for either.

        Returns what the reaper now owns -- the cancelled work and the close --
        so a caller that must not overlap the next request with this one can
        wait for it for a bounded moment (see ``Screen._settle_reaped``)."""
        owned = set(tasks) - self.tasks
        for task in owned:
            if not task.done():
                task.cancel()
        if close is not None:
            owned.add(asyncio.create_task(close, name=f"provider-close-{route}"))
        if not owned:
            return owned
        self.tasks.update(owned)
        timer = asyncio.get_running_loop().call_later(self.bound, self._expire, owned)
        self._groups[timer] = (route, owned)
        for task in owned:
            task.add_done_callback(self._finished)
        return owned

    def _finished(self, task: asyncio.Future[Any]) -> None:
        self.tasks.discard(task)
        if not task.cancelled():
            task.exception()
        for timer, (_, group) in list(self._groups.items()):
            if all(member.done() for member in group):
                timer.cancel()
                del self._groups[timer]

    def _expire(self, group: set[asyncio.Future[Any]]) -> None:
        for timer, (route, members) in list(self._groups.items()):
            if members is group:
                timer.cancel()
                del self._groups[timer]
                pending = [task for task in group if not task.done()]
                if pending:
                    log.warning("provider cleanup exceeded deadline (%s)", route)
                    for task in pending:
                        task.cancel()
                return

    async def wait(self, bound: float | None = None) -> None:
        """Wait against one deadline; caller cancellation propagates immediately."""
        deadline = asyncio.get_running_loop().time() + max(0.0, self.bound if bound is None else bound)
        while pending := {task for task in self.tasks if not task.done()}:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            await asyncio.wait(pending, timeout=remaining)
        # Never await after the final cancellation. Survivors stay strongly
        # owned, with exception retrieval attached, until their teardown ends.
        for _, group in list(self._groups.values()):
            self._expire(group)
