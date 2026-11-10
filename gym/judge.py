#!/usr/bin/env python3
"""Blind board judge: batches of board PNGs go to Opus and/or Codex judges.

    python3 gym/judge.py --round r0                  # auto: alternate, Haiku batches go to both
    python3 gym/judge.py --round r0 --judge opus
    python3 gym/judge.py --round r0 --judge sol
    python3 gym/judge.py --round r0 --judge auto --force   # re-judge everything

Anonymous ids (B1, B2, ...) are assigned once and stored in
$GYM_DATA/judge/<round>/key.json so judges never see model names.
Boards are judged in batches of 5. A batch containing a board from member
claude-haiku-5-5 always goes to BOTH judges (Opus never alone on Haiku);
their scores are combined (correct ANDed, numbers averaged, issues unioned).

Private data stays in $GYM_DATA (default ~/gym-data/board-gym):
    judge/<round>/key.json            anon -> {member, case}
    judge/<round>/batches/<bid>/      <anon>.png, <anon>.html, context.md, prompt.md
    judge/<round>/raw/<anon>.<judge>.json   per-judge verdicts
    judge/<round>/verdicts.jsonl      combined verdicts mapped to member/case
Results in results.jsonl are merged with judge scores on each run.
"""
import argparse
import datetime
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

GYM = Path(__file__).resolve().parent
DATA = Path(os.environ.get("GYM_DATA", Path.home() / "gym-data" / "board-gym"))
CASES = DATA / "cases"
RUNS = DATA / "runs"
JUDGE_DIR = DATA / "judge"
RUBRIC = (GYM / "prompts" / "judge.md").read_text(encoding="utf-8")

BATCH_SIZE = 5
HAIKU_MEMBER = "claude-haiku-5-5"
TIMEOUT_S = 600


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- boards

def collect_boards(round_id: str) -> list:
    """Finished runs for the round: board.html + board.png present."""
    out = []
    base = RUNS / round_id
    if not base.exists():
        return out
    for member_dir in sorted(base.iterdir()):
        if not member_dir.is_dir():
            continue
        for case_dir in sorted(member_dir.iterdir()):
            if not (case_dir / "board.html").exists() or not (case_dir / "board.png").exists():
                continue
            cpath = CASES / f"{case_dir.name}.json"
            case = json.loads(cpath.read_text(encoding="utf-8")) if cpath.exists() else {}
            out.append({"member": member_dir.name, "case": case_dir.name,
                        "split": case.get("split"), "run_dir": case_dir, "data": case})
    return out


def load_key(round_id: str) -> dict:
    p = JUDGE_DIR / round_id / "key.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def assign_ids(round_id: str, boards: list) -> dict:
    """key.json: anon -> {member, case}. New boards get the next B-numbers in
    random order (blinding); existing mappings are kept stable."""
    d = JUDGE_DIR / round_id
    d.mkdir(parents=True, exist_ok=True)
    key = load_key(round_id)
    have = {(v["member"], v["case"]) for v in key.values()}
    used = {int(k[1:]) for k in key if re.fullmatch(r"B\d+", k)}
    fresh = [b for b in boards if (b["member"], b["case"]) not in have]
    random.shuffle(fresh)
    nxt = max(used, default=0) + 1
    for b in fresh:
        while f"B{nxt}" in key:
            nxt += 1
        key[f"B{nxt}"] = {"member": b["member"], "case": b["case"]}
        nxt += 1
    (d / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1) + "\n",
                                encoding="utf-8")
    return key


# ---------------------------------------------------------------- context

def format_convo(convo: list, limit: int = 30) -> str:
    lines = []
    for turn in convo[-limit:]:
        role, text = turn.get("role"), (turn.get("text") or "").strip()
        if not text:
            continue
        if role == "event":
            lines.append(text if text.startswith("[") else f"[{text}]")
        elif role == "child":
            lines.append(f"Barnet: {text}")
        elif role == "tutor":
            lines.append(f"Räven: {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


def board_context(anon: str, board: dict, batch_dir: Path) -> str:
    case = board["data"] or {}
    learner = case.get("learner", {})
    req = case.get("request", {})
    after = case.get("after", []) or []
    payload = {"tool": req.get("tool", ""), "title": req.get("title", ""),
               "content": req.get("content", {})}
    after_s = "\n".join(f"- {t}" for t in after) if after else "(inget – tavlan var det sista)"
    return (
        f"## {anon}\n"
        f"Learner: {learner.get('name')}, grade {learner.get('grade')}\n"
        f"PNG: {(batch_dir / f'{anon}.png').resolve()} (also ./{anon}.png)\n"
        f"HTML source: {(batch_dir / f'{anon}.html').resolve()} (also ./{anon}.html)\n"
        f"### Last conversation lines\n{format_convo(case.get('conversation', []))}\n"
        f"### What the tutor asked to show\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
        f"### What the tutor said next (judge-only)\n{after_s}\n"
    )


def write_batch(round_id: str, bid: str, anons: list, by_anon: dict) -> Path:
    bdir = JUDGE_DIR / round_id / "batches" / bid
    bdir.mkdir(parents=True, exist_ok=True)
    for anon in anons:
        board = by_anon[anon]
        shutil.copy(board["run_dir"] / "board.png", bdir / f"{anon}.png")
        shutil.copy(board["run_dir"] / "board.html", bdir / f"{anon}.html")
    ctx = "\n\n".join(board_context(a, by_anon[a], bdir) for a in anons)
    (bdir / "context.md").write_text(ctx, encoding="utf-8")
    return bdir


def judge_prompt(anons: list, by_anon: dict, bdir: Path, tool: str) -> str:
    ctx = "\n\n".join(board_context(a, by_anon[a], bdir) for a in anons)
    if tool == "opus":
        paths = "\n".join(f"- {bdir.resolve() / (a + '.png')}" for a in anons)
        how = (f"Read each PNG with the Read tool before scoring it:\n{paths}\n"
               "You may also Read the HTML source files listed per board.")
    else:
        how = ("The board images are attached to this message in batch order "
               f"({', '.join(anons)}). Match image N to board N in the list.")
    return (f"{RUBRIC}\n\n# Batch ({len(anons)} boards)\n{how}\n\n{ctx}\n")


# ---------------------------------------------------------------- judge calls

def spawn(argv: list, cwd: Path, log_path: Path, timeout_s: int):
    t0 = datetime.datetime.now(datetime.timezone.utc).timestamp()
    with open(log_path, "w", encoding="utf-8", errors="replace") as lf:
        lf.write(f"$ {' '.join(argv)}\n\n")
        lf.flush()
        proc = subprocess.Popen(
            argv, cwd=str(cwd), stdout=lf, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
            env={**os.environ, "TERM": "dumb", "NO_COLOR": "1", "CI": "1"})
        try:
            rc = proc.wait(timeout=timeout_s)
            err = None
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            proc.wait()
            rc = None
            err = f"timeout after {timeout_s}s"
    wall = datetime.datetime.now(datetime.timezone.utc).timestamp() - t0
    return rc, wall, err


def parse_claude_result(text: str) -> str:
    end = text.rfind("}")
    if end == -1:
        return text
    lines = text.splitlines()
    cands = [text]
    for i in range(len(lines) - 1, max(-1, len(lines) - 6), -1):
        cands.append("\n".join(lines[i:]))
    for cand in cands:
        s = cand.strip()
        if not s.startswith("{"):
            continue
        try:
            data = json.loads(s)
        except json.JSONDecodeError:
            continue
        res = data.get("result", "")
        if isinstance(res, str) and res.strip():
            return res
    return text


def parse_codex_reply(text: str) -> str:
    last = ""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = d.get("type", "")
        if t in ("item.completed", "agent_message", "message"):
            item = d.get("item") or d.get("message") or d
            txt = _extract_text(item)
            if txt:
                last = txt
    if last:
        return last
    # Fallback: last JSONL text payload that looks like a verdict list.
    for line in reversed(text.splitlines()):
        if '"correct"' in line and '"clarity"' in line:
            try:
                d = json.loads(line.strip())
                txt = _extract_text(d)
                if txt and '"correct"' in txt:
                    return txt
            except (json.JSONDecodeError, TypeError):
                pass
    return ""


def _extract_text(item) -> str:
    if isinstance(item, str):
        return item if len(item) < 60000 else ""
    if isinstance(item, dict):
        if item.get("type") in ("text", "output_text"):
            t = item.get("text", "")
            return t if isinstance(t, str) else ""
        for k in ("text", "content", "message", "payload"):
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                return v
            if isinstance(v, list):
                parts = [_extract_text(x) for x in v]
                s = "\n".join(p for p in parts if p)
                if s.strip():
                    return s
    if isinstance(item, list):
        return "\n".join(p for p in (_extract_text(x) for x in item) if p)
    return ""


def extract_verdicts(reply: str, anons: list) -> list:
    """Pull the JSON array of verdicts out of a judge reply."""
    t = (reply or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL | re.IGNORECASE)
    if m:
        t = m.group(1).strip()
    # Find the outermost [...] block containing '"correct"'.
    start = t.find("[")
    data = None
    if start >= 0:
        depth, instr, esc = 0, False, False
        for i in range(start, len(t)):
            ch = t[i]
            if instr:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    instr = False
                continue
            if ch == '"':
                instr = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(t[start:i + 1])
                    except json.JSONDecodeError:
                        data = None
                    break
    if data is None:
        try:
            obj = json.loads(t)
            data = obj if isinstance(obj, list) else [obj]
        except json.JSONDecodeError:
            raise ValueError(f"no JSON verdict array found in reply: {t[:300]}")
    if isinstance(data, dict):
        data = [data]
    out = []
    for v in data:
        if not isinstance(v, dict) or v.get("id") not in anons:
            continue
        out.append({"id": v["id"], "correct": bool(v.get("correct")),
                    "clarity": int(v.get("clarity", 0)),
                    "fits_request": int(v.get("fits_request", 0)),
                    "issues": [str(s) for s in (v.get("issues") or [])]})
    missing = [a for a in anons if a not in {v["id"] for v in out}]
    if missing:
        raise ValueError(f"judge reply missing boards {missing}: {t[:300]}")
    return out


def run_opus(bdir: Path, prompt: str, anons: list) -> list:
    (bdir / "prompt-opus.md").write_text(prompt, encoding="utf-8")
    argv = ["claude", "-p", prompt, "--model", "claude-opus-5-5",
            "--effort", "medium", "--output-format", "json",
            "--add-dir", str(bdir.resolve()), "--tools", "Read"]
    rc, wall, err = spawn(argv, bdir, bdir / "judge-opus.log", TIMEOUT_S)
    raw = (bdir / "judge-opus.log").read_text(encoding="utf-8", errors="replace")
    if err is not None:
        raise RuntimeError(err)
    if rc != 0:
        raise RuntimeError(f"claude exit={rc}")
    return extract_verdicts(parse_claude_result(raw), anons)


def run_sol(bdir: Path, prompt: str, anons: list) -> list:
    (bdir / "prompt-sol.md").write_text(prompt, encoding="utf-8")
    argv = ["codex", "exec", "-m", "gpt-6.1-sol",
            "-c", "model_reasoning_effort=high",
            "--skip-git-repo-check", "--json", "-s", "read-only"]
    # NOTE: --image takes multiple values, so the = form is required;
    # `--image path PROMPT` would swallow the prompt as another image.
    for a in anons:
        argv += [f"--image={(bdir / f'{a}.png').resolve()}"]
    argv.append(prompt)
    rc, wall, err = spawn(argv, bdir, bdir / "judge-sol.log", TIMEOUT_S)
    raw = (bdir / "judge-sol.log").read_text(encoding="utf-8", errors="replace")
    if err is not None:
        raise RuntimeError(err)
    if rc != 0:
        raise RuntimeError(f"codex exit={rc}: {raw[-2000:]}")
    return extract_verdicts(parse_codex_reply(raw), anons)


RUNNERS = {"opus": run_opus, "sol": run_sol}


def combine(judged: dict) -> dict:
    """Combine per-judge verdicts for one board. correct is ANDed, numbers
    averaged, issues unioned."""
    vs = list(judged.values())
    issues: list = []
    for _, v in sorted(judged.items()):
        for s in v.get("issues", []):
            if s not in issues:
                issues.append(s)
    return {"correct": all(v.get("correct") for v in vs),
            "clarity": round(sum(v.get("clarity", 0) for v in vs) / len(vs), 2),
            "fits_request": round(sum(v.get("fits_request", 0) for v in vs) / len(vs), 2),
            "issues": issues, "judges": sorted(judged)}


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", required=True)
    ap.add_argument("--judge", default="auto", choices=["opus", "sol", "auto"])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    boards = collect_boards(a.round)
    if not boards:
        log(f"no finished runs for round {a.round}")
        return
    key = assign_ids(a.round, boards)
    rev = {(v["member"], v["case"]): k for k, v in key.items()}
    by_anon = {rev[(b["member"], b["case"])]: b for b in boards
               if (b["member"], b["case"]) in rev}

    raw_dir = JUDGE_DIR / a.round / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stored = {}
    for p in raw_dir.glob("*.json"):
        try:
            m = re.fullmatch(r"(B\d+)\.(opus|sol)", p.stem)
            if m:
                stored[(m.group(1), m.group(2))] = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    anons = sorted(by_anon)
    batches = [anons[i:i + BATCH_SIZE] for i in range(0, len(anons), BATCH_SIZE)]
    log(f"round {a.round}: {len(anons)} boards in {len(batches)} batches")

    auto_flip = 0
    for i, batch in enumerate(batches):
        bid = f"b{i + 1:02d}"
        haiku = any(by_anon[x]["member"] == HAIKU_MEMBER for x in batch)
        if haiku:
            judges = ["opus", "sol"]
        elif a.judge == "auto":
            judges = ["sol" if auto_flip % 2 else "opus"]
            auto_flip += 1
        else:
            judges = [a.judge]
        need = [j for j in judges
                if a.force or not all((x, j) in stored for x in batch)]
        if not need:
            log(f"skip {bid} ({' '.join(batch)} already judged by {'+'.join(judges)})")
            continue
        bdir = write_batch(a.round, bid, batch, by_anon)
        for j in need:
            try:
                log(f"judge {bid} [{','.join(batch)}] with {j} ...")
                verdicts = RUNNERS[j](bdir, judge_prompt(batch, by_anon, bdir, j), batch)
                for v in verdicts:
                    p = raw_dir / f"{v['id']}.{j}.json"
                    p.write_text(json.dumps(v, ensure_ascii=False, indent=1) + "\n",
                                 encoding="utf-8")
                    stored[(v["id"], j)] = v
                log(f"judge {bid} with {j}: ok")
            except Exception as e:
                log(f"judge {bid} with {j} FAILED: {e}")

    # Rebuild combined verdicts from all raw files.
    per_anon: dict = {}
    for (anon, judge), v in stored.items():
        per_anon.setdefault(anon, {})[judge] = v
    vpath = JUDGE_DIR / a.round / "verdicts.jsonl"
    with open(vpath, "w", encoding="utf-8") as f:
        for anon in sorted(per_anon):
            board = by_anon.get(anon)
            if board is None:
                continue
            c = combine(per_anon[anon])
            f.write(json.dumps({"round": a.round, "anon": anon,
                                "member": board["member"], "case": board["case"],
                                "split": board.get("split"), **c},
                               ensure_ascii=False) + "\n")
    log(f"wrote {vpath} ({len(per_anon)} boards)")

    # Merge judge scores back into results.jsonl records.
    rpath = DATA / "results.jsonl"
    if rpath.exists():
        lines = [ln for ln in rpath.read_text(encoding="utf-8").splitlines()
                 if ln.strip()]
        verdict = {}
        for ln in lines:
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if r.get("round") == a.round:
                verdict[(r.get("member"), r.get("case"))] = r
        for line in vpath.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            v = json.loads(line)
            r = verdict.get((v["member"], v["case"]))
            if r is not None:
                r["judge"] = {k: v[k] for k in
                              ("correct", "clarity", "fits_request", "issues", "judges")
                              if k in v}
        with open(rpath, "w", encoding="utf-8") as f:
            for ln in lines:
                try:
                    r = json.loads(ln)
                except json.JSONDecodeError:
                    f.write(ln + "\n")
                    continue
                if r.get("round") == a.round:
                    upd = verdict.get((r.get("member"), r.get("case")))
                    f.write(json.dumps(upd if upd is not None else r,
                                       ensure_ascii=False) + "\n")
                else:
                    f.write(ln + "\n")
        log(f"merged judge scores into {rpath}")


if __name__ == "__main__":
    sys.exit(main())
