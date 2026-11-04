"""Two consecutive sessions for the same fictional learner, typed instead of spoken.

Session 1 asks for a worked equation on the board and ends with Avsluta; the note it
saves is passed into session 2, exactly as the browser does, and session 2 asks for a
different board item. Checks per session: board items arrive through `board.show`,
and no tool name, tool arguments or JSON reach the spoken captions (the captions are
the text the voice speaks).

    bin/with-env uv run python scripts/two_session_probe.py --out DIR

Uses live providers (costs a little) and the worker registered as TUTOR_AGENT_NAME.
Fictional material only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from pathlib import Path

from fastapi.testclient import TestClient
from livekit import rtc

from open_tutor.web import create_app

TOOL_NAMES = ("show_steps", "focus_step", "show_text", "show_ideas", "show_svg", "show_html",
              "find_resources", "share_resource", "start_quiet_work", "stay_quiet", "save_note")
LEAK = re.compile(r"\b(?:%s)\b|default_api|tool_code|\"(?:tex|steps|markdown|title)\"\s*:|[{}]" % "|".join(TOOL_NAMES))

TURNS = [
    "Hej! Kan du visa hur man löser 3x + 5 = 20 steg för steg på tavlan?",
    "Hej igen! Kan du visa hur man löser 2x - 4 = 10 steg för steg på tavlan?",
]


async def run_session(index: int, notes: list[dict], log) -> dict:
    client = TestClient(create_app())
    response = client.post(
        "/api/session",
        headers={"x-tutor-code": os.environ.get("TUTOR_ACCESS_CODE", "")},
        json={"learner": {"name": "Leo", "grade": 7, "notes": notes}},
    )
    response.raise_for_status()
    session = response.json()
    room = rtc.Room()
    state = {"agent": "initializing"}
    changed = asyncio.Event()
    captions: list[str] = []
    board: list[dict] = []
    saved: list[dict] = []
    gone = asyncio.Event()

    @room.on("participant_attributes_changed")
    def attrs(diff, participant):
        if "lk.agent.state" in diff:
            state["agent"] = diff["lk.agent.state"]
            changed.set()

    room.on("disconnected", lambda *_: gone.set())

    def on_caption(reader, identity):
        async def read():
            text = await reader.read_all()
            if text.strip() and identity != room.local_participant.identity:
                captions.append(text)
                log(index, "caption", text=text)
        asyncio.create_task(read())

    def on_note(reader, identity):
        async def read():
            saved.append(json.loads(await reader.read_all()))
            log(index, "note", topic=saved[-1].get("topic"))
        asyncio.create_task(read())

    await room.connect(session["url"], session["token"])
    room.register_text_stream_handler("lk.transcription", on_caption)
    room.register_text_stream_handler("note", on_note)

    def rpc(method):
        async def handler(data: rtc.RpcInvocationData) -> str:
            item = json.loads(data.payload)
            board.append({"method": method, **item})
            log(index, "board", method=method, id=item.get("id"), item_kind=item.get("kind"), title=item.get("title"))
            await asyncio.sleep(0.15)  # stand-in for render time
            return json.dumps({"ok": True})
        return handler

    for method in ("board.show", "board.update", "board.focus"):
        room.local_participant.register_rpc_method(method, rpc(method))

    async def until(wanted: set[str], timeout: float) -> bool:
        end = time.monotonic() + timeout
        while state["agent"] not in wanted:
            changed.clear()
            if time.monotonic() > end:
                return False
            try:
                await asyncio.wait_for(changed.wait(), end - time.monotonic())
            except asyncio.TimeoutError:
                return False
        return True

    log(index, "connected", room=session["room"], notes_in=len(notes))
    await until({"speaking"}, 30)
    await until({"listening"}, 40)
    await room.local_participant.send_text(TURNS[index], topic="lk.chat")
    log(index, "typed", text=TURNS[index])
    await until({"thinking", "speaking"}, 20)
    await until({"listening"}, 90)
    await asyncio.sleep(2)
    await until({"listening"}, 60)
    await room.local_participant.send_text(json.dumps({"type": "end"}), topic="session-event")
    log(index, "end_sent")
    try:
        await asyncio.wait_for(gone.wait(), 60)
    except asyncio.TimeoutError:
        log(index, "no_disconnect")
    await room.disconnect()
    leaks = [c for c in captions if LEAK.search(c)]
    return {
        "room": session["room"],
        "board_show": [b for b in board if b["method"] == "board.show"],
        "board_focus": len([b for b in board if b["method"] == "board.focus"]),
        "captions": captions,
        "leaks": leaks,
        "notes": saved,
    }


async def main(out: Path) -> dict:
    t0 = time.monotonic()
    events: list[dict] = []

    def log(index, event, **data):
        entry = {"t": round(time.monotonic() - t0, 2), "session": index + 1, "event": event, **data}
        events.append(entry)
        print(json.dumps(entry, ensure_ascii=False)[:300], flush=True)

    first = await run_session(0, [], log)
    second = await run_session(1, list(reversed(first["notes"]))[:5], log)
    summary = {
        f"session{i + 1}": {
            "room": s["room"],
            "board_items": [(b.get("id"), b.get("kind"), b.get("title")) for b in s["board_show"]],
            "focus_calls": s["board_focus"],
            "captions": len(s["captions"]),
            "leaked_captions": s["leaks"],
            "notes_saved": len(s["notes"]),
        }
        for i, s in enumerate((first, second))
    }
    summary["distinct_rooms"] = first["room"] != second["room"]
    summary["second_board_mentions_first_equation"] = any(
        "3x" in json.dumps(b, ensure_ascii=False) for b in second["board_show"])
    (out / "report.json").write_text(json.dumps({"summary": summary, "events": events,
                                                  "sessions": [first, second]}, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    print(json.dumps(asyncio.run(main(args.out)), ensure_ascii=False, indent=2), flush=True)
    os._exit(0)  # the native LiveKit client can abort during interpreter teardown
