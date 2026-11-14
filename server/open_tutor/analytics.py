"""PostHog product analytics for the tutor worker.

Fully OFF unless the backend environment sets ``TUTOR_POSTHOG_KEY`` (the public
project token, ``phc_…``). No key means no import of the ``posthog`` package,
no network calls and no behaviour change — open-source safe and tests need no
network. Analytics events never carry conversation text, typed text, homework
content or images: only counts, route names and ids.

Two events per session, both with a ``room`` property:

- ``tutor_session_started`` {grade, returning, llm_route, tts}
- ``tutor_session_ended`` {duration_s, outcome, close_reason,
  child_spoken_turns, child_typed_turns, tutor_replies, tool_calls,
  tool_errors, provider_errors}

The ended counts reuse ``debug_log.summarize`` (the same function the debug
report uses) over a lightweight in-memory stub event list, so the counting
logic is not duplicated and works when ``TUTOR_DEBUG_LOG`` is off.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("open-tutor")

POSTHOG_HOST_DEFAULT = "https://eu.i.posthog.com"

# Worker-injected session prompts are user-role messages, not the child's
# words. Mirrors debug_log._is_prompt_injection; kept local so this module
# never stores message text, only counts.
_PROMPT_PREFIX = "[Session event"


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
    """Lowercase, trimmed, single-spaced. Mirrors web/src/analytics.ts."""
    return " ".join(str(name or "").strip().lower().split())


def stable_distinct_id(device_id: Any, learner_name: Any, room: str) -> str:
    """The id both the page and the worker derive for one learner on one device.

    Falls back to the room name when the page sent no device id (older page,
    forged request): still countable per session, just not linkable.
    """
    device = str(device_id or "").strip()
    if not device:
        return str(room or "unknown-room")
    name = normalize_learner_name(learner_name)
    if not name:
        return f"device:{device}"
    return f"device:{device}:learner:{name}"


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

            return cls(settings, Posthog(settings["key"], host=settings["host"]))
        except Exception as error:  # missing package, bad host: stay silent, stay off
            log.debug("posthog disabled, client could not start: %s", error)
            return cls(None)

    @property
    def enabled(self) -> bool:
        return self._settings is not None and self._client is not None

    def capture(self, distinct_id: str, event: str, properties: dict[str, Any] | None = None) -> None:
        """Send one event. Never raises; failures are debug-level only."""
        if not self.enabled:
            return
        try:
            self._client.capture(distinct_id, event, properties or {})
        except Exception as error:
            log.debug("posthog capture %s failed: %s", event, error)

    def shutdown(self) -> None:
        """Flush on process shutdown. Never raises."""
        if not self.enabled:
            return
        try:
            flush = getattr(self._client, "flush", None)
            if callable(flush):
                flush()
        except Exception as error:
            log.debug("posthog flush failed: %s", error)


class SessionTracker:
    """Per-session counters that feed ``debug_log.summarize``.

    Subscribes to the same LiveKit SDK events as the debug log but keeps only
    stub records (names and counts, never text, arguments or outputs), so the
    ended-event properties match the debug report summary without writing any
    files or keeping conversation content in memory.
    """

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record_sdk(self, event: Any) -> None:
        try:
            kind = getattr(event, "type", "?")
            if kind == "user_input_transcribed":
                if bool(getattr(event, "is_final", False)):
                    self.events.append({"event": "child_speech", "final": True})
            elif kind == "conversation_item_added":
                item = getattr(event, "item", None)
                if getattr(item, "type", None) != "message":
                    return
                if str(getattr(item, "role", "")) != "user":
                    return
                try:
                    text = item.text_content  # a property, not a method
                except Exception:
                    return
                if not text or str(text).startswith(_PROMPT_PREFIX):
                    return
                # Typed turn. The text is counted, never stored.
                self.events.append({"event": "chat_item", "item": "message",
                                    "role": "user", "text": ""})
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


def get_analytics(environ: dict[str, str] | Any | None = None, client: Any = None) -> Analytics:
    """The process-wide client. First call wins (``reset_analytics`` for tests)."""
    global _process_analytics
    if _process_analytics is None:
        _process_analytics = Analytics.from_env(environ, client=client)
    return _process_analytics


def reset_analytics() -> None:
    global _process_analytics
    _process_analytics = None
