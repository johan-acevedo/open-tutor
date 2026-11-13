"""Per-session debug trail for authorised family testing.

Off by default (open-source safe): nothing is written unless the backend
environment sets ``TUTOR_DEBUG_LOG=1``. When enabled, one private directory per
session records both sides of the conversation, tool calls with arguments and
results (including board content), lifecycle/close/disconnect events, mode and
board acknowledgements, plus usage metrics — enough to reconstruct a learner
session timeline after the fact.

Crash evidence first: events append to ``events.jsonl`` immediately (each line
flushed), so a killed worker still leaves a trail. On shutdown the worker also
writes ``report.json`` with the session header, a summary and the full event
list. Filenames contain only sanitised generated IDs (room/job); the directory
is private (0700) with private files (0600) outside the repository.

What is deliberately NOT captured: credentials, API keys, auth headers, signed
tokens/URLs, the whole environment, homework image bytes (only a description
and size; pasted text is kept, capped at the same 12 kB the worker forwards),
and audio itself (LiveKit Cloud recording already keeps that when
``TUTOR_CLOUD_RECORDING=1``). The config snapshot is an explicit allowlist, not
a filtered dump.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("open-tutor")

ENABLED = os.environ.get("TUTOR_DEBUG_LOG") == "1"

# Explicitly safe to record: route and tuning names, never secrets. Anything not
# listed here is never written, even if present in the environment.
SAFE_CONFIG_KEYS = (
    "TUTOR_LLM",
    "TUTOR_LLM_MODEL",
    "TUTOR_LLM_BASE_URL",
    "TUTOR_LLM_REASONING",
    "TUTOR_TTS",
    "TUTOR_TTS_MODEL",
    "TUTOR_TTS_VOICE",
    "TUTOR_STT_MODEL",
    "TUTOR_STT_MAX_ENDPOINT_MS",
    "TUTOR_MIN_ENDPOINT",
    "TUTOR_NOISE_CANCELLATION",
    "TUTOR_AGENT_NAME",
    "TUTOR_CLOUD_RECORDING",
    "TUTOR_DEBUG_LOG",
    "TUTOR_MAX_SESSIONS_PER_HOUR",
)

_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")


def sanitize_id(value: str, limit: int = 80) -> str:
    """Make a generated id safe for a filename; never allows path separators."""
    return _SAFE_ID.sub("_", value or "unknown")[:limit] or "unknown"


def default_dir() -> Path:
    state_home = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state_home) / "open-tutor" / "sessions"


def config_snapshot(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Only the allowlisted keys, values truncated. Never credentials."""
    env = os.environ if environ is None else environ
    snapshot: dict[str, str] = {}
    for key in SAFE_CONFIG_KEYS:
        value = env.get(key)
        if value is not None:
            snapshot[key] = value[:200]
    return snapshot


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# One job runs in one process, so the active log is process-local: entrypoint sets
# it and helpers (tool healing, interrupts, board acks) record without threading
# a handle through SDK-fixed signatures.
_active: DebugLog | None = None


def set_active(debug: DebugLog) -> None:
    global _active
    _active = debug if debug.enabled else None


def clear_active() -> None:
    global _active
    _active = None


def record_active(event: str, data: dict[str, Any] | None = None) -> None:
    if _active is not None:
        _active.record(event, data)


class DebugLog:
    """Append-only per-session timeline. A disabled instance is a silent no-op."""

    def __init__(self, directory: Path | None = None) -> None:
        self.enabled = False
        self.directory = directory
        self.events: list[dict[str, Any]] = []
        self.started_at = time.time()
        self._file = None

    @classmethod
    def create(
        cls,
        room: str,
        learner: dict[str, Any],
        job_id: str,
        environ: dict[str, str] | None = None,
        base_dir: Path | None = None,
    ) -> DebugLog:
        """Start a session log when ``TUTOR_DEBUG_LOG=1``, else a disabled no-op."""
        env = os.environ if environ is None else environ
        if env.get("TUTOR_DEBUG_LOG") != "1":
            return cls()
        self = cls()
        try:
            base = base_dir or Path(
                env.get("TUTOR_DEBUG_LOG_DIR", "") or default_dir_with_env(env)
            )
            session_dir = (base / sanitize_id(room)).resolve()
            if session_dir != (base.resolve() / sanitize_id(room)):
                raise ValueError(f"unsafe session dir for room {room!r}")
            session_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(base, 0o700)
            os.chmod(session_dir, 0o700)
            path = session_dir / f"{sanitize_id(job_id, 40)}.events.jsonl"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            os.chmod(path, 0o600)
            self._file = os.fdopen(fd, "a", buffering=1)
            self.directory = session_dir
            self.enabled = True
        except Exception as error:
            log.warning("debug log disabled, could not open session file: %s", error)
            return cls()
        self.started_at = time.time()
        self.record(
            "session_start",
            {
                "room": room,
                "job_id": job_id,
                "learner": {
                    "name": str(learner.get("name", ""))[:40],
                    "grade": learner.get("grade"),
                    "notes_in": len(learner.get("notes") or []),
                },
                "cloud_recording": env.get("TUTOR_CLOUD_RECORDING") == "1",
                "config": config_snapshot(env),
            },
        )
        return self

    def _stamp(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        return {
            "t_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="milliseconds"),
            "t_rel_s": round(now - self.started_at, 3),
            "event": event,
            **data,
        }

    def record(self, event: str, data: dict[str, Any] | None = None) -> None:
        """Append one event and flush at once, so crashes keep the evidence."""
        if not self.enabled:
            return
        entry = self._stamp(event, data or {})
        self.events.append(entry)
        try:
            assert self._file is not None
            self._file.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as error:
            log.warning("debug log write failed: %s", error)

    def record_sdk(self, event: Any) -> None:
        """Record one LiveKit AgentSession event by its schema, not by assumption."""
        if not self.enabled:
            return
        kind = getattr(event, "type", "?")
        try:
            if kind == "user_input_transcribed":
                self.record(
                    "child_speech",
                    {
                        "final": bool(getattr(event, "is_final", False)),
                        "text": getattr(event, "transcript", ""),
                    },
                )
            elif kind == "user_transcription_timeout":
                self.record(
                    "transcription_timeout",
                    {"speech_s": round(float(getattr(event, "speech_duration", 0.0)), 2)},
                )
            elif kind == "conversation_item_added":
                self.record("chat_item", _chat_item(getattr(event, "item", None)))
            elif kind == "function_tools_executed":
                calls = [
                    {"name": c.name, "call_id": c.call_id, "arguments": c.arguments}
                    for c in (getattr(event, "function_calls", None) or [])
                ]
                outputs = [
                    {"name": o.name, "call_id": o.call_id, "is_error": o.is_error, "output": o.output}
                    for o in (getattr(event, "function_call_outputs", None) or [])
                ]
                self.record("tools_executed", {"calls": calls, "outputs": outputs})
            elif kind in ("user_state_changed", "agent_state_changed"):
                self.record(
                    "speech_state",
                    {
                        "who": "child" if kind.startswith("user") else "tutor",
                        "old": str(getattr(event, "old_state", "?")),
                        "new": str(getattr(event, "new_state", "?")),
                    },
                )
            elif kind == "speech_created":
                self.record(
                    "reply_started",
                    {
                        "source": str(getattr(event, "source", "?")),
                        "user_initiated": bool(getattr(event, "user_initiated", False)),
                    },
                )
            elif kind == "tool_execution_updated":
                update = getattr(event, "update", None)
                update_type = getattr(update, "type", "?")
                # ToolCallStarted carries the call inside `function_call`; the other
                # updates carry call_id/status/message directly.
                if update_type == "tool_call_started":
                    fnc = getattr(update, "function_call", None)
                    self.record(
                        "tool_lifecycle",
                        {
                            "update": update_type,
                            "call_id": getattr(fnc, "call_id", "?"),
                            "name": getattr(fnc, "name", "?"),
                        },
                    )
                else:
                    self.record(
                        "tool_lifecycle",
                        {
                            "update": update_type,
                            "call_id": getattr(update, "call_id", "?"),
                            "status": getattr(update, "status", None),
                            "message": getattr(update, "message", None),
                        },
                    )
            elif kind in ("agent_false_interruption", "overlapping_speech"):
                self.record(kind, _dump(getattr(event, "model_dump", lambda: {})()))
            elif kind == "session_usage_updated":
                self.record("usage", {"usage": _dump(getattr(event, "usage", None))})
            elif kind == "error":
                self.record("provider_error", _dump_error(event))
            elif kind == "close":
                reason = getattr(event, "reason", "?")
                self.record(
                    "session_close",
                    {
                        "reason": str(getattr(reason, "value", reason)),
                        "error": _dump(getattr(event, "error", None)),
                    },
                )
            # "metrics_collected" is deprecated and noisy; the SDK itself skips it
            # for Cloud reports. "debug_message" is internal. Anything unknown is
            # still noted so a schema change is visible instead of silent.
            else:
                self.record("unknown_sdk_event", {"type": kind})
        except Exception as error:
            log.warning("debug log could not record %s event: %s", kind, error)

    def finalize(self, outcome: str, detail: str = "") -> Path | None:
        """Write report.json (header + summary + full timeline). Always safe to call."""
        if not self.enabled or self.directory is None:
            self.close()
            return None
        summary = _summarize(self.events)
        report = {
            "report": "open-tutor debug session",
            "written_utc": _utc_now(),
            "outcome": outcome,
            "detail": detail[:500],
            "duration_s": round(time.time() - self.started_at, 2),
            "summary": summary,
            "events": self.events,
        }
        path = self.directory / "report.json"
        try:
            text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.chmod(path, 0o600)
        except Exception as error:
            log.warning("debug log could not write report: %s", error)
            self.close()
            return None
        self.close()
        return path

    def close(self) -> None:
        try:
            if self._file is not None:
                self._file.close()
        except Exception:
            pass
        self._file = None


def default_dir_with_env(env: dict[str, str] | Any) -> Path:
    get = env.get if hasattr(env, "get") else (lambda k, d="": os.environ.get(k, d))
    state_home = get("XDG_STATE_HOME", "") or str(Path.home() / ".local" / "state")
    return Path(state_home) / "open-tutor" / "sessions"


def _text_content(item: Any) -> str | None:
    text = getattr(item, "text_content", None)
    if callable(text):
        try:
            return text()
        except Exception:
            return None
    return text if isinstance(text, str) else None


def _chat_item(item: Any) -> dict[str, Any]:
    kind = getattr(item, "type", "?")
    if kind == "message":
        entry: dict[str, Any] = {"item": "message", "role": str(getattr(item, "role", "?"))}
        text = _text_content(item) or ""
        # User messages arrive as typed text or STT transcripts; assistant messages
        # are the captioned words the voice speaks (expression markup stripped).
        entry["text"] = text
        metrics = getattr(item, "metrics", None)
        if metrics:
            entry["metrics"] = {k: v for k, v in dict(metrics).items() if v is not None}
        return entry
    if kind == "function_call":
        return {
            "item": "function_call",
            "name": getattr(item, "name", "?"),
            "call_id": getattr(item, "call_id", "?"),
            "arguments": getattr(item, "arguments", ""),
        }
    if kind == "function_call_output":
        return {
            "item": "function_call_output",
            "name": getattr(item, "name", "?"),
            "call_id": getattr(item, "call_id", "?"),
            "is_error": bool(getattr(item, "is_error", False)),
            "output": str(getattr(item, "output", ""))[:4000],
        }
    return {"item": kind}


def _dump(value: Any, _depth: int = 0) -> Any:
    """Convert SDK objects to plain JSON-safe data, recursing into models."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if _depth > 4:
        return repr(value)[:1000]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _dump(model_dump(), _depth + 1)
        except Exception:
            return repr(value)[:1000]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        try:
            fields = {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
        except Exception:
            return repr(value)[:1000]
        return {key: _dump(item, _depth + 1) for key, item in fields.items()}
    if isinstance(value, dict):
        return {str(k)[:80]: _dump(v, _depth + 1) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_dump(v, _depth + 1) for v in list(value)[:50]]
    return repr(value)[:1000]


def _dump_error(event: Any) -> dict[str, Any]:
    error, source = getattr(event, "error", None), getattr(event, "source", None)
    entry = {
        "error_type": type(error).__name__,
        "error": _dump(error),
        "source": _dump(source),
    }
    # LLMError marks its underlying exception `exclude=True`, so model_dump drops the
    # one thing that explains the failure (a 400 body names the rejected field). Keep
    # the provider's own message, type and status in the same provider_error record.
    cause = getattr(error, "error", None)
    if cause is not None:
        entry["cause"] = {
            "error_type": type(cause).__name__,
            "message": str(cause)[:600],
            "status_code": getattr(cause, "status_code", None),
            "body": str(getattr(cause, "body", ""))[:1200],
        }
    return entry


def _is_prompt_injection(text: str) -> bool:
    """Worker-injected session events are user-role messages, not the child's words."""
    return text.startswith("[Session event")


def _summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    child_turns = sum(1 for e in events if e["event"] == "child_speech" and e.get("final"))
    typed_turns = sum(
        1
        for e in events
        if e["event"] == "chat_item"
        and e.get("item") == "message"
        and e.get("role") == "user"
        and not _is_prompt_injection(e.get("text") or "")
    )
    tutor_replies = sum(1 for e in events if e["event"] == "reply_started")
    assistant_texts = sum(
        1
        for e in events
        if e["event"] == "chat_item"
        and e.get("item") == "message"
        and e.get("role") == "assistant"
    )
    tool_calls = sum(len(e.get("calls", [])) for e in events if e["event"] == "tools_executed")
    tool_errors = sum(
        1
        for e in events
        if e["event"] == "tools_executed"
        for o in e.get("outputs", [])
        if o.get("is_error")
    )
    return {
        "diag_batches": sum(1 for e in events if e["event"] == "diag"),
        "diag_events": sum(len(e.get("events", [])) for e in events if e["event"] == "diag"),
        "diag_dropped": max(
            [e.get("dropped", 0) for e in events if e["event"] == "diag"] + [0]
        ),
        "child_final_turns": child_turns,
        "child_typed_turns": typed_turns,
        "tutor_replies": tutor_replies,
        "assistant_messages": assistant_texts,
        "tool_calls": tool_calls,
        "tool_errors": tool_errors,
        "provider_errors": sum(1 for e in events if e["event"] == "provider_error"),
        "close_reason": next(
            (e.get("reason") for e in events if e["event"] == "session_close"), None
        ),
        "mode_changes": [(e["t_rel_s"], e.get("mode")) for e in events if e["event"] == "mode"],
        "healed_tool_arguments": sum(e.get("count", 0) for e in events if e["event"] == "healed_arguments"),
        # Which model was the fox, and both warm-up times, at a glance (session_llm.py).
        "llm": next(
            (
                {
                    "route": e.get("route"),
                    "model": e.get("model"),
                    "choice": e.get("choice"),
                    "reason": e.get("reason"),
                    "preferred_s": e.get("preferred_s"),
                    "fallback_s": e.get("fallback_s"),
                }
                for e in reversed(events)
                if e["event"] == "llm_chosen"
            ),
            {"route": None, "reason": "no warm-up (single route)"},
        ),
        "llm_failovers": [
            {"at_s": e["t_rel_s"], "from": e.get("from"), "to": e.get("to"), "error": e.get("error")}
            for e in events
            if e["event"] == "llm_failover"
        ],
        "greeting_said": next(
            (e["t_rel_s"] for e in events if e["event"] == "greeting"), None
        ),
        # Which audio filter the child's microphone went through (noise.py).
        "noise_cancellation": next(
            (
                e.get("noise_cancellation")
                for e in events
                if e["event"] == "worker_session_started"
            ),
            None,
        ),
    }
