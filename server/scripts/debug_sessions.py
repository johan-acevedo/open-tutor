"""Review helper for Open Tutor debug session logs (TUTOR_DEBUG_LOG=1).

Runs where the worker runs (it reads the worker's private state dir):

    bin/with-env uv run python scripts/debug_sessions.py --list
    bin/with-env uv run python scripts/debug_sessions.py --last --learner kian
    bin/with-env uv run python scripts/debug_sessions.py --show tutor-XXXX

--list prints one line per session (newest first): room, start (UTC), learner,
outcome, turns/tools/errors and the session directory. --last/--show print a
compact timeline with real timestamps and content. Session content stays in
these local files; nothing is exposed over HTTP.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from open_tutor.debug_log import default_dir  # noqa: E402


def base_dir() -> Path:
    override = os.environ.get("TUTOR_DEBUG_LOG_DIR", "")
    return Path(override) if override else default_dir()


def load_session(room_dir: Path) -> dict | None:
    report = room_dir / "report.json"
    if report.is_file():
        try:
            body = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        events = body.get("events", [])
        start = next((e for e in events if e.get("event") == "session_start"), {})
        return {
            "room": room_dir.name,
            "dir": str(room_dir),
            "started_utc": start.get("t_utc", "?"),
            "learner": (start.get("learner") or {}).get("name", "?"),
            "grade": (start.get("learner") or {}).get("grade"),
            "outcome": body.get("outcome", "?"),
            "duration_s": body.get("duration_s"),
            "summary": body.get("summary", {}),
            "events": events,
            "complete": True,
        }
    # No report: the worker died before shutdown. events.jsonl is the evidence.
    lines = []
    for events_file in sorted(room_dir.glob("*.events.jsonl")):
        try:
            lines.extend(events_file.read_text(encoding="utf-8").splitlines())
        except OSError:
            pass
    if not lines:
        return None
    try:
        events = [json.loads(line) for line in lines]
    except ValueError:
        return None
    start = next((e for e in events if e.get("event") == "session_start"), {})
    return {
        "room": room_dir.name,
        "dir": str(room_dir),
        "started_utc": start.get("t_utc", "?"),
        "learner": (start.get("learner") or {}).get("name", "?"),
        "grade": (start.get("learner") or {}).get("grade"),
        "outcome": "no report (worker died before shutdown)",
        "duration_s": round(events[-1].get("t_rel_s", 0), 1) if events else None,
        "summary": {},
        "events": events,
        "complete": False,
    }


def all_sessions() -> list[dict]:
    base = base_dir()
    sessions = []
    if base.is_dir():
        for room_dir in base.iterdir():
            if room_dir.is_dir():
                session = load_session(room_dir)
                if session is not None:
                    sessions.append(session)
    sessions.sort(key=lambda s: s["started_utc"], reverse=True)
    return sessions


def describe(session: dict) -> str:
    summary = session["summary"]
    grade = session["grade"]
    grade_bit = f" arskurs {grade}" if grade else ""
    duration = session["duration_s"]
    bits = [
        session["room"],
        str(session["started_utc"]),
        "learner=" + str(session["learner"]) + grade_bit,
        "outcome=" + str(session["outcome"]),
        "duration=" + (str(duration) + "s" if duration is not None else "?"),
    ]
    if summary:
        bits.append(
            "child_turns=" + str(summary.get("child_final_turns"))
            + " tutor_replies=" + str(summary.get("tutor_replies"))
            + " tools=" + str(summary.get("tool_calls"))
            + " tool_errors=" + str(summary.get("tool_errors"))
            + " provider_errors=" + str(summary.get("provider_errors"))
        )
    if not session["complete"]:
        bits.append("(INCOMPLETE)")
    return " | ".join(bits)


def one_line(text: object, limit: int = 500) -> str:
    flat = " ".join(str(text).split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + " ... (+" + str(len(flat) - limit) + " chars)"


def timeline_line(entry: dict) -> str:
    stamp = str(entry.get("t_rel_s", "?")).rjust(8) + " " + str(entry.get("t_utc", ""))[11:23]
    kind = entry.get("event", "?")
    if kind == "child_speech":
        mark = "CHILD" if entry.get("final") else "child~interim"
        return stamp + " " + mark + ": " + one_line(entry.get("text", ""), 800)
    if kind == "chat_item" and entry.get("item") == "message":
        who = "TUTOR" if entry.get("role") == "assistant" else "child-typed"
        metrics = entry.get("metrics") or {}
        extra = ""
        if metrics.get("llm_node_ttft") is not None:
            extra = " [ttft=" + str(round(metrics["llm_node_ttft"], 1)) + "s]"
        return stamp + " " + who + ": " + one_line(entry.get("text", ""), 800) + extra
    if kind == "tools_executed":
        parts = []
        for call, output in zip(entry.get("calls", []), entry.get("outputs", [])):
            flag = " ERROR" if output.get("is_error") else ""
            parts.append(
                str(call.get("name")) + "(" + one_line(call.get("arguments", ""), 300) + ")"
                + " -> " + one_line(output.get("output", ""), 300) + flag
            )
        return stamp + " TOOLS: " + " ; ".join(parts)
    if kind == "board_ack":
        return (
            stamp + " BOARD " + str(entry.get("method")) + " " + str(entry.get("id"))
            + " ok=" + str(entry.get("ok")) + " " + one_line(entry.get("title") or "", 120)
        )
    if kind == "mode":
        return stamp + " MODE " + str(entry.get("old")) + " -> " + str(entry.get("mode"))
    if kind == "note":
        return stamp + " NOTE ok=" + str(entry.get("ok")) + " topic=" + one_line(entry.get("topic", ""), 200)
    if kind == "provider_error":
        return stamp + " PROVIDER_ERROR " + str(entry.get("error_type")) + ": " + one_line(entry.get("error", ""), 300)
    if kind == "session_close":
        return stamp + " CLOSE reason=" + str(entry.get("reason"))
    detail = {k: v for k, v in entry.items() if k not in ("t_utc", "t_rel_s", "event")}
    return stamp + " " + str(kind) + ": " + one_line(detail, 400)


def main() -> int:
    parser = argparse.ArgumentParser(description="Review Open Tutor debug session logs.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="one line per session, newest first")
    group.add_argument("--last", action="store_true", help="timeline of the most recent session")
    group.add_argument("--show", metavar="ROOM", help="timeline of one session by room name")
    parser.add_argument("--learner", default="", help="filter by learner name substring")
    parser.add_argument("--since", default="", help="only sessions started on/after YYYY-MM-DD (UTC)")
    args = parser.parse_args()

    sessions = all_sessions()
    if args.learner:
        sessions = [s for s in sessions if args.learner.lower() in str(s["learner"]).lower()]
    if args.since:
        sessions = [s for s in sessions if s["started_utc"] >= args.since]
    if not sessions:
        print("no debug sessions in " + str(base_dir()))
        return 1
    if args.list:
        for session in sessions:
            print(describe(session))
        print(str(len(sessions)) + " session(s) in " + str(base_dir()))
        return 0
    session = next((s for s in sessions if s["room"] == args.show), None) if args.show else sessions[0]
    if session is None:
        print("no session " + str(args.show) + " in " + str(base_dir()))
        return 1
    print(describe(session))
    print("dir: " + session["dir"])
    for entry in session["events"]:
        if entry.get("event") == "session_start":
            continue
        print(timeline_line(entry))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
