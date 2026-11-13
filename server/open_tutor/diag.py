"""Allowlist and bound diagnostic events before writing them to the session journal.

Sequence numbers identify gaps among received events. Missing tail events
cannot be detected when a tab or its connection never recovers.
"""

from __future__ import annotations

import math
from typing import Any

DIAG_VERSION = 1
MAX_EVENTS_PER_BATCH = 25

_MAX_SEQ = 2**31 - 1
_MAX_T_CLIENT_MS = 10**15
_MAX_DROPPED = 10**9

# kind -> field -> (expected type, max string length)
_EVENT_FIELDS: dict[str, dict[str, tuple[type, int]]] = {
    "visibility": {"state": (str, 16), "via": (str, 24), "precise": (bool, 0)},
    "connection": {"kind": (str, 16), "state": (str, 32), "reason": (str, 48)},
    "mic-track": {
        "change": (str, 16), "wanted": (bool, 0), "via": (str, 24),
        "ready": (str, 16), "muted": (bool, 0), "enabled": (bool, 0),
    },
    "playback": {"allowed": (bool, 0), "ctx": (str, 16), "via": (str, 16)},
    "resume": {"ok": (bool, 0), "step": (str, 16), "code": (str, 24)},
    # Hook point for the parallel wake-lock PR; no wake-lock code depends on it.
    "wakelock": {"status": (str, 24)},
}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value)))


def _clean_event(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("k")
    if not isinstance(kind, str) or kind not in _EVENT_FIELDS:
        return None
    seq, t = raw.get("seq"), raw.get("t")
    if not _is_int(seq) or seq < 1 or seq > _MAX_SEQ:
        return None
    if not _is_num(t) or t < 0 or t > _MAX_T_CLIENT_MS:
        return None
    event: dict[str, Any] = {"k": kind, "seq": seq, "t": raw["t"]}
    for field, (expected, cap) in _EVENT_FIELDS[kind].items():
        value = raw.get(field)
        if expected is str:
            if isinstance(value, str):
                event[field] = value[:cap]
        elif expected is bool and isinstance(value, bool):
            event[field] = value
    return event


def parse_diag(payload: Any) -> dict[str, Any] | None:
    """Normalize a ``diag`` envelope, or ``None`` when it must not be logged.

    Anything that is not this schema (mic/start/end/page-answer/board-size and
    all other session events) also returns ``None`` so existing handlers keep
    their behavior untouched.
    """
    if not isinstance(payload, dict):
        return None
    if payload.get("type") != "diag":
        return None
    if payload.get("v") != DIAG_VERSION or isinstance(payload.get("v"), bool):
        return None
    seq, t_client, dropped = payload.get("seq"), payload.get("tClient"), payload.get("dropped")
    if not _is_int(seq) or seq < 1 or seq > _MAX_SEQ:
        return None
    if not _is_num(t_client) or t_client < 0 or t_client > _MAX_T_CLIENT_MS:
        return None
    if not _is_int(dropped) or dropped < 0 or dropped > _MAX_DROPPED:
        return None
    raw_events = payload.get("events")
    if not isinstance(raw_events, list) or not raw_events or len(raw_events) > MAX_EVENTS_PER_BATCH:
        return None
    events = [clean for raw in raw_events if (clean := _clean_event(raw)) is not None]
    if not events:
        return None
    return {"seq": seq, "t_client": payload["tClient"], "dropped": dropped, "events": events}
