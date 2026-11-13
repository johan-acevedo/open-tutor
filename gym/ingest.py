#!/usr/bin/env python3
"""Pull tutor debug trails from thinkcentre and turn every board moment into a gym case.

    python3 gym/ingest.py            # rsync new sessions, (re)build cases
    python3 gym/ingest.py --no-pull  # rebuild from the local copy only

Session data is private and never enters git. Everything lands in
$GYM_DATA (default ~/gym-data/board-gym):
    raw/sessions/<room>/...           verbatim copy of the debug trails
    cases/<case_id>.json              one case per board tool call
    cases/index.json                  id, split, kind, title, grade per case

Split: whole sessions are held out, so a conversation never sits in both sets.
A session is hidden when sha256(room) mod 4 == 0. The rule is fixed, so new
sessions extend both sets without moving old cases.
"""
import argparse, hashlib, json, os, subprocess, sys
from pathlib import Path

DATA = Path(os.environ.get("GYM_DATA", Path.home() / "gym-data" / "board-gym"))
REMOTE = os.environ.get("GYM_REMOTE", "100.73.214.109:.local/state/open-tutor/sessions/")
BOARD_TOOLS = {"show_text", "show_steps", "show_svg", "show_html", "show_ideas"}
EVENT_PREFIXES = ("[Session event", "[The child was", "[Homework", "[Board", "[System")


SPLITS = json.loads((Path(__file__).with_name("splits.json")).read_text())
PANEL_SIZE = {"tune": 14, "hidden": 12}
RICH = {"show_svg": 0, "show_html": 0, "show_steps": 1, "show_ideas": 1, "show_text": 2}


def split_for(room: str) -> str:
    if room in SPLITS["hidden_sessions"]:
        return "hidden"
    return "hidden" if int(hashlib.sha256(room.encode()).hexdigest(), 16) % 4 == 0 else "tune"


def panels(index):
    """Fixed panels per split: one case per (session, title) (the last one, most context),
    rich kinds first, at most 3 per session, round-robin over sessions. Deterministic."""
    out = {}
    for split, size in PANEL_SIZE.items():
        last = {}
        for r in index:
            if r["split"] == split:
                last[(r["session"], r["title"])] = r
        by_s = {}
        for r in sorted(last.values(), key=lambda r: (RICH.get(r["tool"], 2), r["utc"] or "")):
            by_s.setdefault(r["session"], []).append(r)
        pick, rnd = [], 0
        while len(pick) < size and rnd < 3:
            for s in sorted(by_s):
                if rnd < len(by_s[s]) and len(pick) < size:
                    pick.append(by_s[s][rnd]["id"])
            rnd += 1
        out[split] = sorted(pick)
    return out


def classify(text: str) -> str:
    return "event" if text.startswith("[") else "child"


def build_session(path: Path):
    events = [json.loads(l) for l in path.open() if l.strip()]
    start = next((e for e in events if e["event"] == "session_start"), {})
    room = start.get("room") or path.parent.name
    learner = start.get("learner", {})
    convo, homework, cases = [], [], []
    for i, e in enumerate(events):
        ev, t = e["event"], e.get("t_rel_s")
        if ev == "chat_item" and e.get("item") == "message" and e.get("text"):
            role = "tutor" if e.get("role") == "assistant" else classify(e["text"])
            convo.append({"t": t, "role": role, "text": e["text"]})
        elif ev == "homework_shared":
            homework.append({"t": t, "kind": e.get("kind"), "description": e.get("description"),
                             "mime": e.get("mime"), "bytes": e.get("bytes"),
                             "image_available": False})
        elif ev == "tools_executed":
            for call, out in zip(e["calls"], e["outputs"]):
                if call["name"] not in BOARD_TOOLS:
                    continue
                try:
                    args = json.loads(call["arguments"])
                except json.JSONDecodeError:
                    args = {"raw": call["arguments"]}
                output = out.get("output", "")
                board_id = output.split()[1] if output.startswith("Item ") else None
                after = [c["text"] for c in
                         ({"t": x.get("t_rel_s"), "role": x.get("role"), "text": x.get("text")}
                          for x in events[i + 1:] if x["event"] == "chat_item"
                          and x.get("item") == "message" and x.get("role") == "assistant"
                          and x.get("text"))][:3]
                title = args.get("title", "")
                cid = f"{room.removeprefix('tutor-')}-{board_id or call['call_id'][-8:]}"
                cases.append({
                    "id": cid,
                    "split": split_for(room),
                    "session": room,
                    "t_rel_s": t,
                    "utc": e.get("t_utc"),
                    "learner": {"name": learner.get("name"), "grade": learner.get("grade"),
                                "language": "sv"},
                    "conversation": list(convo),
                    "homework": list(homework),
                    "request": {"tool": call["name"], "title": title,
                                "content": {k: v for k, v in args.items() if k != "title"}},
                    "shown_ok": not out.get("is_error") and output.startswith("Item "),
                    "after": after,  # judge-only: what the tutor said next
                })
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pull", action="store_true")
    a = ap.parse_args()
    raw = DATA / "raw" / "sessions"
    raw.mkdir(parents=True, exist_ok=True)
    if not a.no_pull:
        subprocess.run(["rsync", "-a", REMOTE, str(raw) + "/"], check=True)
    out = DATA / "cases"
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for f in sorted(raw.glob("*/*.events.jsonl")):
        for c in build_session(f):
            (out / f"{c['id']}.json").write_text(json.dumps(c, ensure_ascii=False, indent=1))
            index.append({k: c[k] for k in ("id", "split", "session", "utc")} |
                         {"tool": c["request"]["tool"], "title": c["request"]["title"],
                          "grade": c["learner"]["grade"], "turns": len(c["conversation"])})
    index.sort(key=lambda r: r["utc"] or "")
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    (out / "panels.json").write_text(json.dumps(panels(index), indent=1))
    n_h = sum(r["split"] == "hidden" for r in index)
    print(f"{len(index)} cases ({len(index) - n_h} tune, {n_h} hidden) from "
          f"{len({r['session'] for r in index})} sessions -> {out}")


if __name__ == "__main__":
    sys.exit(main())
