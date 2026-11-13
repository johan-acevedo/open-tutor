"""Call-diagnostic intake: strict allowlist, bounds, and existing-handler safety.

All payloads here are synthetic. The point is what the server keeps: known
kinds and fields only, strings truncated, numbers range-checked, and every
other session event (mic/end/page-answer/board-size) passing through to its
existing handler untouched.
"""

import json
import math

import pytest

from open_tutor.debug_log import DebugLog
from open_tutor.diag import MAX_EVENTS_PER_BATCH, parse_diag


def batch(*events, **top):
    envelope = {"type": "diag", "v": 1, "seq": 1, "tClient": 1234.5, "dropped": 0, "events": list(events)}
    envelope.update(top)
    return envelope


def test_valid_batch_keeps_allowlisted_fields():
    parsed = parse_diag(
        batch(
            {"k": "visibility", "seq": 1, "t": 10.0, "state": "hidden", "via": "pagehide", "precise": False},
            {"k": "mic-track", "seq": 2, "t": 20.0, "change": "ended", "wanted": True, "via": "track"},
            {"k": "resume", "seq": 3, "t": 30.0, "step": "mic", "ok": False, "code": "mic-failed"},
        )
    )
    assert parsed is not None
    assert parsed["seq"] == 1
    assert parsed["dropped"] == 0
    assert [e["k"] for e in parsed["events"]] == ["visibility", "mic-track", "resume"]
    assert parsed["events"][1] == {
        "k": "mic-track",
        "seq": 2,
        "t": 20.0,
        "change": "ended",
        "wanted": True,
        "via": "track",
    }


def test_hostile_fields_truncated_or_dropped_not_passed_through():
    parsed = parse_diag(
        batch(
            {
                "k": "connection",
                "seq": 1,
                "t": 5.0,
                "kind": "disconnected",
                "state": "connected",
                "reason": "x" * 500,
                "token": "livekit-secret-should-never-land-here",
                "wanted": "yes-please",
            },
        )
    )
    assert parsed is not None
    (event,) = parsed["events"]
    assert event["reason"] == "x" * 48
    assert "token" not in event
    assert "wanted" not in event  # wrong kind, wrong type: dropped


def test_unknown_kinds_dropped_batch_with_only_junk_rejected():
    assert parse_diag(batch({"k": "microphone-audio-bytes", "seq": 1, "t": 1.0})) is None
    assert parse_diag(batch({"k": "mic", "seq": 1, "t": 1.0, "on": True})) is None
    parsed = parse_diag(
        batch(
            {"k": "bogus", "seq": 1, "t": 1.0},
            {"k": "playback", "seq": 2, "t": 2.0, "allowed": True, "ctx": "running", "via": "start"},
        )
    )
    assert parsed is not None
    assert [e["seq"] for e in parsed["events"]] == [2]


def test_bounds_reject_oversized_and_shapeless_batches():
    too_many = [{"k": "resume", "seq": i + 1, "t": float(i), "step": "audio", "ok": True, "code": "ok"}
                for i in range(MAX_EVENTS_PER_BATCH + 1)]
    assert parse_diag(batch(*too_many)) is None
    assert parse_diag(batch()) is None
    assert parse_diag({"type": "diag"}) is None
    assert parse_diag("diag") is None
    assert parse_diag(None) is None
    assert parse_diag(batch({"k": "resume", "seq": 1, "t": 1.0}, v=2)) is None
    assert parse_diag(batch({"k": "resume", "seq": 1, "t": 1.0}, v=True)) is None
    assert parse_diag(batch({"k": "resume", "seq": 1, "t": 1.0}, seq=0)) is None
    assert parse_diag(batch({"k": "resume", "seq": 1, "t": 1.0}, seq=True)) is None
    assert parse_diag(batch({"k": "resume", "seq": True, "t": 1.0})) is None
    assert parse_diag(batch({"k": "resume", "seq": 1, "t": -5.0})) is None
    assert parse_diag(batch({"k": "resume", "seq": 1, "t": 1.0}, dropped=-1)) is None
    assert parse_diag(batch({"k": "resume", "seq": 1, "t": 1.0}, dropped=10**10)) is None
    assert parse_diag(batch({"k": "resume", "seq": 1, "t": 1.0}, events="nope")) is None
    assert parse_diag(batch({"k": "resume", "seq": 1})) is None


def test_existing_session_events_pass_through_untouched():
    # parse_diag must not claim anything the current handlers own.
    assert parse_diag({"type": "mic", "on": True, "why": "button"}) is None
    assert parse_diag({"type": "end"}) is None
    assert parse_diag({"type": "page-answer", "page": "p1", "part": "a", "value": "42", "kind": "gap"}) is None
    assert parse_diag({"type": "board-size", "w": 800, "h": 600, "device": "mobile"}) is None
    assert parse_diag({"type": "resource-closed", "id": "abc"}) is None


@pytest.mark.parametrize("kind", [[], {}])
def test_malformed_event_kind_is_rejected_without_throwing(kind):
    assert parse_diag(batch({"k": kind, "seq": 1, "t": 1.0})) is None


@pytest.mark.parametrize("clock", [math.nan, math.inf, -math.inf])
def test_nonfinite_client_clocks_are_rejected(clock):
    assert parse_diag(batch({"k": "resume", "seq": 1, "t": clock})) is None
    assert parse_diag(batch({"k": "resume", "seq": 1, "t": 1.0}, tClient=clock)) is None


def test_diag_round_trip_into_debug_log(tmp_path):
    env = {"TUTOR_DEBUG_LOG": "1"}
    debug = DebugLog.create("tutor-room", {"name": "Leo", "grade": 7}, "AJ_1", environ=env, base_dir=tmp_path)
    assert debug.enabled
    parsed = parse_diag(
        batch(
            {"k": "visibility", "seq": 7, "t": 700.0, "state": "hidden", "via": "pagehide"},
            {"k": "connection", "seq": 8, "t": 900.0, "kind": "reconnected"},
            dropped=3,
            seq=7,
        )
    )
    assert parsed is not None
    debug.record("diag", parsed)
    path = debug.finalize("ended")
    assert path is not None
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["summary"]["diag_batches"] == 1
    assert report["summary"]["diag_events"] == 2
    assert report["summary"]["diag_dropped"] == 3
    diag_lines = [e for e in report["events"] if e["event"] == "diag"]
    assert len(diag_lines) == 1
    # Server receive time is stamped on arrival, client time travels along.
    assert "t_utc" in diag_lines[0] and "t_rel_s" in diag_lines[0]
    assert diag_lines[0]["t_client"] == 1234.5
    assert [e["seq"] for e in diag_lines[0]["events"]] == [7, 8]
