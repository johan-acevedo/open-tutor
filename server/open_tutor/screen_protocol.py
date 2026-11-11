"""Fox side of the browser-owned Screen protocol v1.

The browser owns the visible workspace. Räven only sends high-level intents
and observes actual pixels plus a small private teaching context. This module
is the pure state machine (no LiveKit dependency) so it is easy to test:

- capability parsing from participant metadata ``screen: {version:1}``
- intent / observation id generation and payload builders
- correlation of async ``screen-event`` outcomes with their RPCs
- correlation of ``screen-pixels`` (PNG) with ``screen-context`` (JSON)
- timeouts, session-close cancellation, latest-intent tracking, bounded state

LiveKit wiring lives in ``agent.py``: ``screen.intent`` / ``screen.observe``
RPCs (immediate ``{accepted}`` ack) plus ``screen-event`` / ``screen-pixels`` /
``screen-context`` stream handlers that feed this tracker.

Frontend assumptions (browser Screen agent, owned by the lead):
- RPC ``screen.intent`` accepts
  ``{intentId, lessonId, op, need?, background?, target?, viewport}``
  with ``op`` in ``prepare|show|reveal`` and replies immediately with
  ``{accepted: bool, intentId, reason?}``. It never waits for model work.
- RPC ``screen.observe`` accepts
  ``{observationId, lessonId, pageId, revision}`` and replies immediately with
  ``{accepted: bool, observationId, reason?}``.
- Text stream ``screen-event`` carries
  ``{type, intentId?, lessonId, page?: {id, revision}, reason?, answer?}``
  with ``type`` in ``ready|rejected|failed|answer-submitted``.
  ``ready`` means the page is committed and rendered. A stale ``reveal``
  returns ``rejected``; a duplicate intent id returns the existing outcome
  without re-executing. ``answer-submitted`` carries the explicit child answer
  only (never draft keystrokes).
- Byte stream ``screen-pixels`` carries one bounded PNG per accepted
  observation with attributes ``{observationId, pageId, revision}``.
- Text stream ``screen-context`` carries one small JSON record per accepted
  observation with the same correlation ids plus visible state and
  ``privateTeaching`` (e.g. the hidden solution). Never the full Screen
  transcript or page source.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("open-tutor")

SCREEN_VERSION = 1

# RPCs stay within their short timeout; slow preparation must not block voice.
SCREEN_RPC_TIMEOUT = 6.0
# Model/preparation work in the browser can take a while.
SCREEN_INTENT_TIMEOUT = 120.0
# An accepted observation should render and arrive quickly.
SCREEN_OBSERVE_TIMEOUT = 20.0
# Context may trail pixels slightly; do not hold pixels for it for long.
SCREEN_CONTEXT_GRACE = 5.0

MAX_PENDING = 32
MAX_OUTCOMES = 64

INTENT_OPS = ("prepare", "show", "reveal")
EVENT_TYPES = ("ready", "rejected", "failed", "answer-submitted")


def parse_screen_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Read the Screen capability from participant metadata.

    The lead sends ``screen: {version: 1, lessonId: ...}`` in the token
    metadata. Anything else means a legacy browser: keep board tools.
    """
    if not isinstance(meta, dict):
        return {"capable": False, "version": None, "lesson_id": ""}
    screen = meta.get("screen")
    if not isinstance(screen, dict):
        return {"capable": False, "version": None, "lesson_id": ""}
    try:
        version = int(screen.get("version"))
    except (TypeError, ValueError):
        return {"capable": False, "version": None, "lesson_id": ""}
    lesson_id = str(screen.get("lessonId") or screen.get("lesson_id") or "")[:80]
    return {
        "capable": version == SCREEN_VERSION,
        "version": version,
        "lesson_id": lesson_id,
    }


def screen_capable(meta: dict[str, Any] | None) -> bool:
    return bool(parse_screen_meta(meta).get("capable"))


def build_intent_payload(
    intent_id: str,
    lesson_id: str,
    op: str,
    need: str = "",
    background: str = "",
    target: dict[str, str] | None = None,
    viewport: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "intentId": intent_id,
        "lessonId": lesson_id,
        "op": op,
        "viewport": viewport or {},
    }
    if op in ("prepare", "show"):
        payload["need"] = (need or "")[:2000]
        payload["background"] = (background or "")[:2000]
    if op == "reveal" and target is not None:
        payload["target"] = {
            "pageId": str(target.get("pageId") or target.get("id") or "")[:80],
            "revision": str(target.get("revision") or "")[:80],
        }
    return payload


def build_observe_payload(
    observation_id: str,
    lesson_id: str,
    page_id: str,
    revision: str,
) -> dict[str, Any]:
    return {
        "observationId": observation_id,
        "lessonId": lesson_id,
        "pageId": page_id,
        "revision": revision,
    }


def validate_screen_event(event: Any) -> tuple[bool, str]:
    if not isinstance(event, dict):
        return False, "not an object"
    if event.get("type") not in EVENT_TYPES:
        return False, f"unknown type {event.get('type')!r}"
    if not str(event.get("lessonId") or ""):
        return False, "missing lessonId"
    return True, ""


def summarize_screen_context(context: dict[str, Any] | None) -> tuple[str, str]:
    """Split Screen context into (visible summary, private teaching).

    Both parts are truncated. The private part must stay model-only: it guides
    Räven without ever being shown or read aloud to the child.
    """
    if not isinstance(context, dict):
        return "", ""
    visible_bits: list[str] = []
    for key in ("summary", "visible", "interaction", "state"):
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            visible_bits.append(value.strip()[:600])
        elif isinstance(value, dict):
            visible_bits.append(str(value)[:600])
    viewport = context.get("viewport")
    if isinstance(viewport, dict) and viewport:
        visible_bits.append(f"viewport {str(viewport)[:160]}")
    sources = context.get("sources")
    if isinstance(sources, list) and sources:
        visible_bits.append("sources: " + ", ".join(str(s)[:120] for s in sources[:4])[:400])
    page = context.get("page")
    if isinstance(page, dict) and page.get("id"):
        visible_bits.append(f"page {page.get('id')} rev {page.get('revision', '?')}")
    private = context.get("privateTeaching")
    if not isinstance(private, str):
        # Accept american spelling / nested teacher notes without failing.
        private = context.get("private_teaching") if isinstance(context.get("private_teaching"), str) else ""
    return (" ".join(visible_bits)[:1200], (private or "")[:1500])


@dataclass
class _ObservationWait:
    page_id: str = ""
    revision: str = ""
    pixels: asyncio.Future = field(default=None)  # type: ignore[assignment]
    context: asyncio.Future = field(default=None)  # type: ignore[assignment]


class ScreenTracker:
    """Correlate async Screen outcomes with their RPCs. No LiveKit here."""

    def __init__(
        self,
        lesson_id: str,
        intent_timeout: float = SCREEN_INTENT_TIMEOUT,
        observe_timeout: float = SCREEN_OBSERVE_TIMEOUT,
        context_grace: float = SCREEN_CONTEXT_GRACE,
        max_pending: int = MAX_PENDING,
    ) -> None:
        self.lesson_id = lesson_id or ""
        self.intent_timeout = intent_timeout
        self.observe_timeout = observe_timeout
        self.context_grace = context_grace
        self.max_pending = max_pending
        self.current_page: dict[str, str] | None = None
        self.latest_intent_id: str | None = None
        self._intent_seq = 0
        self._obs_seq = 0
        self._intents: dict[str, asyncio.Future] = {}
        self._outcomes: dict[str, dict[str, Any]] = {}
        self._observations: dict[str, _ObservationWait] = {}
        self._closed = False

    # ---- ids ---------------------------------------------------------------

    def new_intent_id(self) -> str:
        self._intent_seq += 1
        return f"i{self._intent_seq}"

    def new_observation_id(self) -> str:
        self._obs_seq += 1
        return f"o{self._obs_seq}"

    # ---- intents -----------------------------------------------------------

    def _evict_intents(self) -> None:
        while len(self._intents) >= self.max_pending:
            oldest = next(iter(self._intents))
            fut = self._intents.pop(oldest)
            if not fut.done():
                fut.cancel()

    def track_intent(self, intent_id: str) -> asyncio.Future:
        """Register a future for an intent we will wait for. Updates latest."""
        self._evict_intents()
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._intents[intent_id] = fut
        self.latest_intent_id = intent_id
        return fut

    def note_intent_sent(self, intent_id: str) -> None:
        """Fire-and-forget intents (prepare): track latest without a waiter."""
        self.latest_intent_id = intent_id

    def abandon_intent(self, intent_id: str) -> None:
        fut = self._intents.pop(intent_id, None)
        if fut is not None and not fut.done():
            fut.cancel()

    def resolve_event(self, event: dict[str, Any]) -> str:
        """Resolve a ready/rejected/failed event. Returns disposition."""
        ok, _ = validate_screen_event(event)
        if not ok:
            return "ignored"
        if event.get("type") == "answer-submitted":
            return "answer"
        if str(event.get("lessonId") or "") != self.lesson_id:
            return "ignored"
        intent_id = str(event.get("intentId") or "")
        if not intent_id:
            return "ignored"
        if intent_id in self._outcomes and intent_id not in self._intents:
            return "duplicate"
        self._outcomes[intent_id] = dict(event)
        while len(self._outcomes) > MAX_OUTCOMES:
            self._outcomes.pop(next(iter(self._outcomes)))
        fut = self._intents.get(intent_id)
        if fut is None:
            return "unknown"
        if fut.done():
            return "duplicate"
        if event.get("type") == "ready" and isinstance(event.get("page"), dict):
            page = event["page"]
            if page.get("id"):
                self.current_page = {
                    "id": str(page.get("id"))[:80],
                    "revision": str(page.get("revision") or "")[:80],
                }
        fut.set_result(dict(event))
        return "resolved"

    async def wait_intent(self, intent_id: str, timeout: float | None = None) -> dict[str, Any]:
        fut = self._intents.get(intent_id)
        if fut is None:
            # Already resolved (e.g. duplicate arrived first) or never tracked.
            if intent_id in self._outcomes:
                return dict(self._outcomes[intent_id])
            raise KeyError(f"unknown intent {intent_id}")
        try:
            event = await asyncio.wait_for(fut, timeout or self.intent_timeout)
        except (asyncio.TimeoutError, TimeoutError) as error:
            self._intents.pop(intent_id, None)
            raise TimeoutError(f"screen intent {intent_id} timed out") from error
        except asyncio.CancelledError:
            self._intents.pop(intent_id, None)
            raise
        self._intents.pop(intent_id, None)
        return dict(event)

    # ---- observations ------------------------------------------------------

    def track_observation(self, observation_id: str, page_id: str, revision: str) -> None:
        while len(self._observations) >= self.max_pending:
            oldest = next(iter(self._observations))
            self.abandon_observation(oldest)
        loop = asyncio.get_running_loop()
        self._observations[observation_id] = _ObservationWait(
            page_id=page_id,
            revision=revision,
            pixels=loop.create_future(),
            context=loop.create_future(),
        )

    def abandon_observation(self, observation_id: str) -> None:
        wait = self._observations.pop(observation_id, None)
        if wait is None:
            return
        for fut in (wait.pixels, wait.context):
            if fut is not None and not fut.done():
                fut.cancel()

    def feed_pixels(self, observation_id: str, png: bytes, attrs: dict[str, Any] | None = None) -> bool:
        wait = self._observations.get(observation_id)
        if wait is None or wait.pixels.done():
            return False
        attrs = attrs or {}
        # Tolerate page correlation when the browser sends it; the observation
        # id is the binding key.
        wait.pixels.set_result((bytes(png), dict(attrs)))
        return True

    def feed_context(self, observation_id: str, context: dict[str, Any]) -> bool:
        wait = self._observations.get(observation_id)
        if wait is None or wait.context.done():
            return False
        if isinstance(context, dict) and context.get("lessonId"):
            if str(context.get("lessonId")) != self.lesson_id:
                return False
        wait.context.set_result(dict(context))
        return True

    async def wait_observation(
        self, observation_id: str, timeout: float | None = None
    ) -> tuple[bytes, dict[str, Any] | None]:
        wait = self._observations.get(observation_id)
        if wait is None:
            raise KeyError(f"unknown observation {observation_id}")
        try:
            pixels_timeout = timeout or self.observe_timeout
            try:
                png, _attrs = await asyncio.wait_for(wait.pixels, pixels_timeout)
            except (asyncio.TimeoutError, TimeoutError) as error:
                raise TimeoutError(f"screen pixels {observation_id} timed out") from error
            try:
                context = await asyncio.wait_for(wait.context, self.context_grace)
            except (asyncio.TimeoutError, TimeoutError):
                context = None
            return png, context
        finally:
            self._observations.pop(observation_id, None)

    # ---- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._closed = True
        for intent_id in list(self._intents):
            self.abandon_intent(intent_id)
        for obs_id in list(self._observations):
            self.abandon_observation(obs_id)

    @property
    def closed(self) -> bool:
        return self._closed
