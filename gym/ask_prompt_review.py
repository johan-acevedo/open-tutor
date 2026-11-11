#!/usr/bin/env python3
"""Ask a judge model for system-prompt updates from judged boards.

For each judged board in a round, sends the judge: the system prompt used,
the board PNG, the rendering model's own rationale (reasoning note after
</html>), and the earlier verdict. The judge proposes concrete, generalizing
system-prompt edits. Output: judge/<round>/prompt-reviews.jsonl (+ raw/).

Usage: python3 gym/ask_prompt_review.py --round r19 [--judge argon] [--cases ..]
"""
import argparse
import json
import re
import subprocess
import sys
import threading
from pathlib import Path

GYM = Path(__file__).resolve().parent
DATA = Path.home() / "gym-data" / "board-gym"
sys.path.insert(0, str(GYM))
from judge import spawn, parse_pi_jsonl  # noqa: E402

REVIEW_SYSTEM = (
    "You help improve the system prompt of an AI that renders teaching boards "
    "for school children. You see the exact system prompt it was given, one "
    "board it made (screenshot), the model's own explanation of its choices, "
    "and an independent verdict on the board. Answer only with the JSON asked for."
)

REVIEW_RUBRIC = """Propose 0-3 concrete edits to the SYSTEM PROMPT that would generalize beyond this one board.
- Quote the exact current sentence/paragraph you would change (\"find\"), then the replacement (\"replace\"). To add text, set \"find\" to the sentence after which it goes and \"replace\" to \"\" + the new paragraph, or vice versa with \"\" find for a brand-new section.
- Only propose edits that would plausibly help across many boards. Never propose board-specific content (no names, numbers, or topics from this board).
- If the board is good and the prompt needs no change because of it, return an empty list.
- Also give one line each: what the model misunderstood (or \"nothing\"), and whether its own explanation shows good judgment (yes/no + why in 10 words).

Answer with exactly this JSON, no other text:
{"misunderstood": "...", "good_judgment": "...", "edits": [{"find": "...", "replace": "...", "why": "..."}]}
"""


def reasoning_note(run_dir: Path) -> str:
    """Model's rationale: text after </html> in the first-call reply."""
    texts = []
    try:
        for line in (run_dir / "cli.log").read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "message_end":
                msg = d.get("message", {}) or {}
                if msg.get("role") == "assistant":
                    for c in msg.get("content", []) or []:
                        if isinstance(c, dict) and c.get("type") == "text":
                            texts.append(c.get("text", ""))
    except FileNotFoundError:
        return ""
    reply = "\n".join(texts)
    if "</html>" in reply.lower():
        idx = reply.lower().rfind("</html>")
        return reply[idx + len("</html>"):].strip()[:4000]
    return ""


def review_board(round_id: str, verdict: dict, system_prompt: str, judge: str, model: str) -> dict:
    case = verdict["case"]
    member = verdict["member"]
    run_dir = DATA / "runs" / round_id / member.replace("/", "__") / case
    png = run_dir / "board.png"
    note = reasoning_note(run_dir)
    prompt = (
        f"# System prompt given to the renderer\n{system_prompt}\n\n"
        f"# Board screenshot: {png.resolve()} (attached)\n\n"
        f"# The renderer's own explanation of its work\n{note or '(none given)'}\n\n"
        f"# Independent verdict: correct={verdict.get('correct')}, "
        f"clarity={verdict.get('clarity')}, "
        f"issues={json.dumps(verdict.get('issues', []), ensure_ascii=False)}\n\n"
        f"{REVIEW_RUBRIC}"
    )
    pf = run_dir / "prompt-review.md"
    pf.write_text(prompt, encoding="utf-8")
    argv = ["pi", "-p", "--model", model, "--thinking", "high", "--no-tools",
            "--no-session", "--no-context-files", "--no-skills", "--no-extensions",
            "--mode", "json", "--system-prompt", REVIEW_SYSTEM,
            f"@{png.resolve()}", f"@{pf.resolve()}",
            "Propose the system-prompt edits now."]
    rc, wall, err = spawn(argv, run_dir, run_dir / "review.log", 600)
    raw = (run_dir / "review.log").read_text(encoding="utf-8", errors="replace")
    if err is not None or rc != 0:
        return {"round": round_id, "case": case, "ok": False, "error": (err or raw[-500:])}
    reply = parse_pi_jsonl(raw).get("reply", "")
    m = re.search(r"\{[\s\S]*\}", reply)
    if not m:
        return {"round": round_id, "case": case, "ok": False, "error": "no JSON in reply"}
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"round": round_id, "case": case, "ok": False, "error": "bad JSON"}
    return {"round": round_id, "case": case, "ok": True, "wall_s": round(wall, 1),
            "verdict_correct": verdict.get("correct"),
            "verdict_issues": verdict.get("issues", []), **out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--judge", default="argon")
    ap.add_argument("--cases", default="")
    ap.add_argument("--parallel", type=int, default=4)
    a = ap.parse_args()

    from judge import PI_JUDGES
    model = PI_JUDGES[a.judge][0]

    cfg = None
    for c in (GYM / "configs").glob("*.yaml"):
        import yaml
        d = yaml.safe_load(c.read_text(encoding="utf-8"))
        if d.get("round") == a.round:
            cfg = d
            break
    if cfg is None:
        print(f"no config for round {a.round}");
        sys.exit(1)
    prompt_rel = cfg.get("prompt", "prompts/r0")
    system_prompt = (GYM / prompt_rel / "system.md").read_text(encoding="utf-8")

    verdicts = [json.loads(l) for l in
                (DATA / "judge" / a.round / "verdicts.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()]
    if a.cases:
        want = {c.strip() for c in a.cases.split(",") if c.strip()}
        verdicts = [v for v in verdicts if v["case"] in want]

    sem = threading.Semaphore(a.parallel)
    results, lock = [], threading.Lock()

    def one(v):
        with sem:
            try:
                r = review_board(a.round, v, system_prompt, a.judge, model)
            except Exception as e:  # noqa: BLE001
                r = {"round": a.round, "case": v["case"], "ok": False, "error": str(e)[:300]}
            with lock:
                results.append(r)
                print(("ok " if r["ok"] else "FAIL ") + v["case"], flush=True)

    threads = [threading.Thread(target=one, args=(v,)) for v in verdicts]
    [t.start() for t in threads]
    [t.join() for t in threads]

    out = DATA / "judge" / a.round / "prompt-reviews.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in results) + "\n", encoding="utf-8")
    print(f"wrote {out} ({sum(1 for r in results if r['ok'])}/{len(results)} ok)")


if __name__ == "__main__":
    main()
