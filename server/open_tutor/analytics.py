"""PostHog product analytics for the tutor worker.

Fully OFF unless the backend environment sets ``TUTOR_POSTHOG_KEY`` (the public
project token, ``phc_…``). No key means no import of the ``posthog`` package,
no network calls and no behaviour change — open-source safe and tests need no
network. Analytics events never carry conversation text, typed text, homework
content or images: only counts, route names and ids.

Two events per session, both with a ``room`` property:

- ``tutor_session_started`` {grade, returning, llm_route, tts}
- ``tutor_session_ended`` {duration_s, outcome, error_type (only when
  outcome is ``"error"``), close_reason, child_spoken_turns,
  child_typed_turns, tutor_replies, tool_calls, tool_errors,
  provider_errors}

``outcome`` is a fixed category (``ended_by_child``, ``child_left``,
``provider_error``, ``sdk_closed_early``, ``error``, ``unknown``): exception
messages never leave the worker. For ``error`` the exception class name
rides along as ``error_type``; the message is dropped.

The ended counts reuse ``debug_log.summarize`` (the same function the debug
report uses) over a lightweight in-memory stub event list, so the counting
logic is not duplicated and works when ``TUTOR_DEBUG_LOG`` is off.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import re
import threading
from typing import Any

log = logging.getLogger("open-tutor")

POSTHOG_HOST_DEFAULT = "https://eu.i.posthog.com"

# Teardown budgets: analytics is best-effort and must never park a session.
# The request timeout bounds one upload attempt; max_retries=0 drops a failed
# batch instead of retrying it; the flush budget bounds the drain wait. All
# three together mean a hung analytics backend costs a teardown ~2 s, not 10+.
_FLUSH_BUDGET_S = 2.0
_REQUEST_TIMEOUT_S = 2.0


def _bounded_flush(flush: Any, budget: float) -> None:
    """Drain the queue within ``budget`` seconds. Never raises.

    Current posthog clients take a ``timeout_seconds`` budget; older ones
    and test doubles take none — fall back to a bare call."""
    try:
        try:
            flush(timeout_seconds=budget)
        except TypeError:
            flush()
    except Exception as error:
        log.debug("posthog flush failed: %s", error)


def posthog_settings(environ: dict[str, str] | Any | None = None) -> dict[str, str] | None:
    """``{"key", "host"}`` when analytics is configured, else ``None``.

    ``TUTOR_POSTHOG_HOST`` defaults to the EU cloud. An empty key disables
    analytics entirely.
    """
    import os

    env = os.environ if environ is None else environ
    get = env.get if hasattr(env, "get") else (lambda k, d="": os.environ.get(k, d))
    key = (get("TUTOR_POSTHOG_KEY", "") or "").strip()
    if not key:
        return None
    host = (get("TUTOR_POSTHOG_HOST", "") or "").strip() or POSTHOG_HOST_DEFAULT
    return {"key": key, "host": host}


def normalize_learner_name(name: Any) -> str:
    """Lowercase, trimmed, single-spaced.

    Kept for the debug trail and session notes; analytics no longer uses it —
    the learner's name never leaves the worker (see ``stable_distinct_id``)."""
    return " ".join(str(name or "").strip().lower().split())


# Outcomes the session can end with. Anything else (notably the
# ``f"error: {Class}: {message}"`` string the worker builds for the debug
# trail) is mapped down to one of these before it leaves the worker.
_KNOWN_OUTCOMES = frozenset({
    "ended_by_child", "child_left", "provider_error",
    "sdk_closed_early", "idle_timeout", "error", "unknown",
})


def sanitize_outcome(outcome: Any) -> tuple[str, str | None]:
    """Map a worker outcome to ``(category, error_type)`` for analytics.

    Known categories pass through. ``"error: ValueError: <message>"``
    becomes ``("error", "ValueError")`` — the class name is countable,
    the message (which can quote the child, the tutor or a provider) is
    dropped. Anything unrecognised becomes ``("unknown", None)``.
    """
    text = str(outcome or "unknown")
    if text in _KNOWN_OUTCOMES:
        return text, None
    if text.startswith("error:"):
        rest = text[len("error:"):].strip()
        err_type = rest.split(":", 1)[0].strip()
        err_type = "".join(c for c in err_type if c.isalnum() or c in "._")[:80]
        return "error", err_type or "error"
    return "unknown", None


# Shape of a device id the page mints (crypto.randomUUID or its id- fallback).
# MUST match DEVICE_ID_RE in web/src/analytics.ts. Anything else (a custom
# client, a hand-edited value) is not trusted: it could carry a name.
DEVICE_ID_RE = re.compile(
    r"^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|id-\d{1,16}-\d{1,10})$")


def valid_device_id(device_id: Any) -> str | None:
    device = str(device_id or "").strip()
    return device if DEVICE_ID_RE.match(device) else None


def stable_distinct_id(device_id: Any, room: str = "unknown-room") -> str:
    """The id both the page and the worker derive for one browser.

    The learner's name is never part of it: children's names stay out of
    analytics entirely. Falls back to the room name when the page sent no
    device id (older page, forged request): still countable per session,
    just not linkable. MUST match web/src/analytics.ts stableLearnerId."""
    device = valid_device_id(device_id)
    if not device:
        return str(room or "unknown-room")
    return f"device:{device}"


def summarize_llm_turns(turns: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Aggregate per-turn ``llm_turn`` records into counts and timings.

    Pure (no network, no text): the same function feeds the live session
    summary and the debug report summary, so the two never drift apart.
    Only route names, timings and error classes in, same out.

    Only turns served to completion count as wins: a partial-then-failed
    secondary (``winner`` set with ``error`` set) counts as an error for its
    route, never a win. Attempts stay visible via ``turns_errored`` (global)
    and per-route ``turns_errored`` alongside ``turns_won``.
    """
    won: dict[str, int] = {}
    errored: dict[str, int] = {}
    times: dict[str, list[float]] = {}
    hedged = 0
    turns_errored = 0
    for turn in turns or []:
        if turn.get("hedged"):
            hedged += 1
        if turn.get("error") is not None:
            turns_errored += 1
        route = turn.get("winner")
        if route is None:
            continue
        if turn.get("error") is not None:
            # Served partially, then failed: an attempt and an error, not a win.
            errored[route] = errored.get(route, 0) + 1
            continue
        won[route] = won.get(route, 0) + 1
        if turn.get("ttft_s") is not None:
            times.setdefault(route, []).append(turn["ttft_s"])
    routes = {}
    for route in sorted(set(won) | set(errored)):
        entry: dict[str, Any] = {"turns_won": won.get(route, 0)}
        if errored.get(route):
            entry["turns_errored"] = errored[route]
        if times.get(route):
            entry["median_ttft_s"] = round(statistics.median(times[route]), 3)
            entry["max_ttft_s"] = round(max(times[route]), 3)
        routes[route] = entry
    return {"turns_total": len(turns or []), "hedged_turns": hedged,
            "turns_errored": turns_errored, "routes": routes}


def summarize_screen_calls(calls: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Aggregate per-call screen records into counts and timings.

    Pure, like ``summarize_llm_turns``: counts, hedges and first-text timings
    per call kind, plus which provider served each call."""
    by_kind: dict[str, dict[str, Any]] = {}
    wins: dict[str, int] = {}
    hedged = 0
    for call in calls or []:
        kind = str(call.get("kind") or "?")
        slot = by_kind.setdefault(kind, {"calls": 0, "hedges": 0, "ttfts": []})
        slot["calls"] += 1
        if call.get("hedged"):
            hedged += 1
            slot["hedges"] += 1
        if call.get("ttft_s") is not None:
            slot["ttfts"].append(call["ttft_s"])
        if call.get("provider"):
            wins[call["provider"]] = wins.get(call["provider"], 0) + 1
    kinds = {}
    for kind, slot in by_kind.items():
        entry: dict[str, Any] = {"calls": slot["calls"], "hedges": slot["hedges"]}
        if slot["ttfts"]:
            entry["median_ttft_s"] = round(statistics.median(slot["ttfts"]), 3)
            entry["max_ttft_s"] = round(max(slot["ttfts"]), 3)
        kinds[kind] = entry
    return {"calls_total": len(calls or []), "hedged_calls": hedged,
            "provider_wins": wins, "calls": kinds}


class Analytics:
    """Thin, never-raising wrapper around one PostHog client. Disabled without a key."""

    def __init__(self, settings: dict[str, str] | None, client: Any = None) -> None:
        self._settings = settings
        self._client = client

    @classmethod
    def from_env(cls, environ: dict[str, str] | Any | None = None, client: Any = None) -> "Analytics":
        """Build from the environment. A ``client`` double skips the real SDK (tests)."""
        settings = posthog_settings(environ)
        if settings is None:
            return cls(None)
        if client is not None:
            return cls(settings, client)
        try:
            from posthog import Posthog

            return cls(settings, Posthog(settings["key"], host=settings["host"],
                                         timeout=_REQUEST_TIMEOUT_S, max_retries=0))
        except Exception as error:  # missing package, bad host: stay silent, stay off
            log.debug("posthog disabled, client could not start: %s", error)
            return cls(None)

    @property
    def enabled(self) -> bool:
        return self._settings is not None and self._client is not None

    def capture(self, distinct_id: str, event: str, properties: dict[str, Any] | None = None) -> None:
        """Send one event. Never raises; failures are debug-level only.

        The locked ``posthog`` package (7.x) takes the id and properties as
        keywords: ``client.capture(event, distinct_id=..., properties=...)``.
        A positional call raises TypeError, so this wrapper pins the keywords.
        """
        if not self.enabled:
            return
        try:
            self._client.capture(event, distinct_id=distinct_id, properties=properties or {})
        except Exception as error:
            log.debug("posthog capture %s failed: %s", event, error)

    def shutdown(self) -> None:
        """Flush on process shutdown. Never raises.

        Synchronous: only for tests and non-async paths. The session teardown
        in agent.py is async, so it uses ``aclose`` below and never parks the
        event loop on the SDK's blocking flush. Bounded like ``aclose``: even
        a hung backend costs ~2 s, not the SDK default of 10 s.
        """
        if not self.enabled:
            return
        flush = getattr(self._client, "flush", None)
        if callable(flush):
            _bounded_flush(flush, _FLUSH_BUDGET_S)

    async def aclose(self, timeout: float = 2.0) -> None:
        """Flush off the event loop with a short timeout. Never raises.

        The flush itself runs in a daemon thread with its own budget, so a
        slow analytics backend neither parks the event loop while awaited nor
        delays process/loop shutdown after this returns: ``asyncio.to_thread``
        (non-daemon executor threads, joined at loop close) left hung
        teardowns waiting out the SDK default even after cancellation.
        """
        if not self.enabled:
            return
        flush = getattr(self._client, "flush", None)
        if not callable(flush):
            return
        budget = max(0.1, min(float(timeout), _FLUSH_BUDGET_S))
        thread = threading.Thread(target=_bounded_flush, args=(flush, budget),
                                  name="posthog-flush", daemon=True)
        thread.start()
        try:
            # The driver is a daemon thread: even if the backend hangs, this
            # wait ends at the budget and nothing downstream parks on it.
            await asyncio.wait_for(asyncio.to_thread(thread.join, budget), timeout=timeout)
        except Exception as error:
            log.debug("posthog flush failed: %s", error)


class SessionTracker:
    """Per-session counters that feed ``debug_log.summarize``.

    Subscribes to the same LiveKit SDK events as the debug log but keeps only
    stub records (names and counts, never text, arguments or outputs), plus
    one stub per typed turn from the typed-input boundary (``TypedChat``),
    so the ended-event properties match the debug report summary without
    writing any files or keeping conversation content in memory.
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record_typed_turn(self) -> None:
        """One typed turn, called from the typed-input boundary (``TypedChat``).

        Spoken transcripts also arrive as user ``conversation_item_added``,
        so typed turns cannot be derived from SDK chat items: one spoken
        turn would count as spoken=1 and typed=1. The turn is counted, never
        stored — no text reaches this tracker."""
        self.events.append({"event": "chat_typed"})

    def record_sdk(self, event: Any) -> None:
        try:
            kind = getattr(event, "type", "?")
            if kind == "user_input_transcribed":
                if bool(getattr(event, "is_final", False)):
                    self.events.append({"event": "child_speech", "final": True})
            elif kind == "conversation_item_added":
                # Deliberately not recorded: spoken transcripts AND typed
                # echoes both arrive here as user messages, so any count
                # derived from them double-counts spoken turns as typed.
                # Typed turns come from record_typed_turn instead.
                return
            elif kind == "speech_created":
                self.events.append({"event": "reply_started"})
            elif kind == "function_tools_executed":
                calls = getattr(event, "function_calls", None) or []
                outputs = getattr(event, "function_call_outputs", None) or []
                self.events.append({
                    "event": "tools_executed",
                    "calls": [{} for _ in calls],
                    "outputs": [{"is_error": bool(getattr(o, "is_error", False))} for o in outputs],
                })
            elif kind == "error":
                self.events.append({"event": "provider_error"})
            elif kind == "close":
                reason = getattr(event, "reason", "?")
                self.events.append({
                    "event": "session_close",
                    "reason": str(getattr(reason, "value", reason)),
                })
            # Anything else (usage, speech states, modes) is debug-trail detail,
            # not an analytics property.
        except Exception as error:
            log.debug("analytics tracker skipped an event: %s", error)

    def summary(self) -> dict[str, Any]:
        from .debug_log import summarize

        return summarize(self.events)


# One client per process: entrypoint configures it once per worker process.
_process_analytics: Analytics | None = None


def warm_up(environ: dict[str, str] | Any | None = None) -> None:
    """Import the PostHog SDK now, when analytics is configured.

    The first capture inside a session otherwise blocks the event loop importing
    ``posthog.args`` (observed 241 ms in a live session). Fully off without
    ``TUTOR_POSTHOG_KEY``: nothing is imported then. An SDK that cannot load
    stays off, exactly as ``from_env`` treats it at session start."""
    if posthog_settings(environ) is None:
        return
    try:
        from posthog import Posthog  # noqa: F401  (warmed for from_env)
    except Exception as error:
        log.debug("posthog warm-up skipped, analytics stays off: %s", error)


def get_analytics(environ: dict[str, str] | Any | None = None, client: Any = None) -> Analytics:
    """The process-wide client. First call wins (``reset_analytics`` for tests)."""
    global _process_analytics
    if _process_analytics is None:
        _process_analytics = Analytics.from_env(environ, client=client)
    return _process_analytics


def reset_analytics() -> None:
    global _process_analytics
    _process_analytics = None
