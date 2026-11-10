#!/usr/bin/env python3
"""Board gym runner: member models render self-contained 1920x1080 HTML boards.

    python3 gym/run.py --config gym/configs/r0.yaml
    python3 gym/run.py --config gym/configs/r0.yaml --panel tune --members muse-spark-1.3-contributor --cases OBK5VCNGuYtO-b2,n8F-ELseR-_x-b1
    python3 gym/run.py --config gym/configs/r0.yaml --panel tune --members muse-spark-1.3-contributor --cases OBK5VCNGuYtO-b2 --force

Session data is private and never enters git. Everything run-local lands in
$GYM_DATA (default ~/gym-data/board-gym):
    runs/<round>/<member>/<case_id>/   prompt-system.md, prompt-user.md,
                                       board.html, board.png, cli.log,
                                       timing.json, render-meta.json, lint.json
    results.jsonl                      one record per run (appended)
"""
import argparse
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
GYM = Path(__file__).resolve().parent
DATA = Path(os.environ.get("GYM_DATA", Path.home() / "gym-data" / "board-gym"))
CASES = DATA / "cases"
RENDER_MJS = GYM / "render" / "render.mjs"
CHECK_MJS = GYM / "render" / "check.mjs"

TIMEOUT_S = 180

_results_lock = threading.Lock()


def utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- templates

def format_learner(learner: dict) -> str:
    name = learner.get("name") or "Barnet"
    grade = learner.get("grade")
    grade_s = f"årskurs {grade}" if grade is not None else "okänd årskurs"
    return f"{name}, {grade_s}, talar svenska"


def format_conversation(convo: list) -> str:
    lines = []
    for turn in convo:
        role = turn.get("role")
        text = (turn.get("text") or "").strip()
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


def format_homework(homework: list) -> str:
    if not homework:
        return "Ingen."
    out = []
    for h in homework:
        kind = h.get("kind") or "läxa"
        desc = (h.get("description") or "").strip()
        line = f"- {kind}: {desc}" if desc else f"- {kind}"
        if not h.get("image_available"):
            line += " (bilden sparades ej)"
        out.append(line)
    out.append("")
    out.append("(Bilder sparades ej – endast beskrivningar ges.)")
    return "\n".join(out)


def format_request(request: dict) -> str:
    payload = {"title": request.get("title", "")}
    content = request.get("content") or {}
    if isinstance(content, dict):
        payload.update(content)
    else:
        payload["content"] = content
    return json.dumps(payload, ensure_ascii=False, indent=2)


def fill_template(text: str, case: dict) -> str:
    learner = format_learner(case.get("learner", {}))
    convo = format_conversation(case.get("conversation", []))
    hw = format_homework(case.get("homework", []))
    req = case.get("request", {})
    tool = req.get("tool", "")
    return (text.replace("{learner}", learner)
                .replace("{conversation}", convo)
                .replace("{homework}", hw)
                .replace("{tool}", tool)
                .replace("{request}", format_request(req)))


def homework_image_args(case: dict) -> list:
    """Extra @file args if a case ever carries image files (none do yet)."""
    args = []
    for h in case.get("homework", []) or []:
        for key in ("path", "file", "image_path", "local_path"):
            p = h.get(key)
            if p and Path(p).exists():
                args.append(f"@{p}")
    return args


# ---------------------------------------------------------------- pi parsing

def parse_pi_jsonl(text: str) -> dict:
    out = {"reply": "", "input_tokens": None, "output_tokens": None,
           "reasoning_tokens": None, "api_ms": None}
    texts = []
    for line in text.splitlines():
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
                content = msg.get("content", [])
                if isinstance(content, list):
                    texts = [c.get("text", "") for c in content
                             if isinstance(c, dict) and c.get("type") == "text"]
                usage = msg.get("usage", {}) or {}
                if usage:
                    out["input_tokens"] = usage.get("input")
                    out["output_tokens"] = usage.get("output")
                    out["reasoning_tokens"] = usage.get("reasoning")
                if msg.get("durationMs") is not None:
                    try:
                        out["api_ms"] = float(msg["durationMs"])
                    except (TypeError, ValueError):
                        pass
    out["reply"] = "\n".join(texts)
    return out


def extract_html(reply: str) -> str | None:
    t = (reply or "").strip()
    if not t:
        return None
    m = re.search(r"```html\s*(.*?)```", t, re.DOTALL | re.IGNORECASE)
    if m:
        t = m.group(1).strip()
    else:
        m = re.search(r"```\s*(.*?)```", t, re.DOTALL)
        if m and "<html" in m.group(1).lower():
            t = m.group(1).strip()
    low = t.lower()
    if "<!doctype html" not in low and "<html" not in low:
        return None
    i = low.find("<!doctype html")
    if i < 0:
        i = low.find("<html")
    if i > 0:
        t = t[i:]
    # Trim trailing junk after </html> when present.
    low = t.lower()
    j = low.rfind("</html>")
    if j >= 0:
        t = t[:j + len("</html>")]
    return t


# ---------------------------------------------------------------- process

def spawn(argv: list, cwd: Path, log_path: Path, timeout_s: int):
    """Run argv, streaming output to log_path. Returns (rc, wall_s, err)."""
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
    wall_s = datetime.datetime.now(datetime.timezone.utc).timestamp() - t0
    return rc, wall_s, err


def run_node_render(run_dir: Path, toolkit_file: str | None,
                    toolkit_url: str | None, timeout_s: int = 120) -> dict:
    env = dict(os.environ)
    if toolkit_file:
        env["TOOLKIT_FILE"] = toolkit_file
    if toolkit_url:
        env["TOOLKIT_URL"] = toolkit_url
    html = run_dir / "board.html"
    png = run_dir / "board.png"
    meta = run_dir / "render-meta.json"
    t0 = datetime.datetime.now(datetime.timezone.utc).timestamp()
    try:
        p = subprocess.run(
            ["node", str(RENDER_MJS), "--html", str(html),
             "--png", str(png), "--meta", str(meta)],
            cwd=str(run_dir), capture_output=True, text=True,
            timeout=timeout_s, env=env)
        err = None if p.returncode == 0 else (p.stderr or p.stdout or f"exit={p.returncode}")[:500]
    except subprocess.TimeoutExpired:
        p = None
        err = f"render timeout after {timeout_s}s"
    wall = datetime.datetime.now(datetime.timezone.utc).timestamp() - t0
    info: dict = {"wall_s": round(wall, 2), "error": err}
    if meta.exists():
        try:
            info["meta"] = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            info["meta"] = {}
    else:
        info["meta"] = {}
    if png.exists():
        info["png_bytes"] = png.stat().st_size
    return info


def run_node_lint(run_dir: Path, toolkit_file: str | None,
                  toolkit_url: str | None, timeout_s: int = 120) -> dict:
    env = dict(os.environ)
    if toolkit_file:
        env["TOOLKIT_FILE"] = toolkit_file
    if toolkit_url:
        env["TOOLKIT_URL"] = toolkit_url
    html = run_dir / "board.html"
    try:
        p = subprocess.run(
            ["node", str(CHECK_MJS), "--html", str(html), "--json"],
            cwd=str(run_dir), capture_output=True, text=True,
            timeout=timeout_s, env=env)
        out = (p.stdout or "").strip()
        data = None
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        if data is None:
            data = {"clean": None, "error": (p.stderr or out or f"exit={p.returncode}")[:500]}
        data["exit"] = p.returncode
        return data
    except subprocess.TimeoutExpired:
        return {"clean": None, "error": f"lint timeout after {timeout_s}s"}


def lint_findings_text(lint: dict, render_meta: dict) -> str:
    parts = []
    for key in ("console_errors", "page_errors"):
        vals = (lint.get(key) or []) + ((render_meta.get(key) or []) if isinstance(render_meta, dict) else [])
        vals = [v for v in vals if v]
        if vals:
            parts.append(f"{key}: " + "; ".join(str(v)[:200] for v in vals[:6]))
    for key in ("outside", "near_edge", "small_text", "overlaps", "blocked"):
        vals = lint.get(key) or []
        if vals:
            parts.append(f"{key}: " + "; ".join(str(v)[:200] for v in vals[:8]))
    if lint.get("scrolls"):
        parts.append(f"scroll: page scrolls {lint.get('scroll')}")
    return "\n".join(parts) if parts else "no findings"


def count_lint(lint: dict) -> int:
    n = 0
    for key in ("console_errors", "page_errors", "outside", "near_edge",
                "small_text", "overlaps", "blocked"):
        vals = lint.get(key) or []
        if isinstance(vals, list):
            n += len(vals)
    return n


# ---------------------------------------------------------------- one run

def member_argv(member: str, thinking: str, system_text: str,
                user_file: Path, extra_args: list,
                use_append_system: bool, system_file: Path) -> list:
    base = ["pi", "-p", "--model", f"opencode-go/{member}",
            "--thinking", thinking,
            "--no-tools", "--no-session", "--no-context-files",
            "--no-skills", "--no-extensions", "--mode", "json"]
    if use_append_system:
        base += ["--append-system-prompt", str(system_file)]
    else:
        base += ["--system-prompt", system_text]
    return base + [f"@{user_file}", *extra_args, "Make the board now."]


def do_run(round_id: str, member: str, case_id: str, case: dict,
           system_text: str, thinking: str, fix_pass: bool,
           toolkit_file: str | None, toolkit_url: str | None,
           force: bool) -> dict:
    run_dir = DATA / "runs" / round_id / member / case_id
    run_dir.mkdir(parents=True, exist_ok=True)

    needed = [run_dir / "board.html", run_dir / "board.png",
              run_dir / "timing.json", run_dir / "lint.json"]
    if not force and all(p.exists() for p in needed):
        log(f"skip {member} {case_id} (finished)")
        try:
            timing = json.loads((run_dir / "timing.json").read_text(encoding="utf-8"))
            wall = timing.get("wall_s")
        except (OSError, json.JSONDecodeError):
            wall = None
        return {"round": round_id, "member": member, "case": case_id,
                "skipped": True, "wall_s": wall}

    sys_path = run_dir / "prompt-system.md"
    user_path = run_dir / "prompt-user.md"
    sys_path.write_text(system_text, encoding="utf-8")
    # prompt-user.md was written by main() before dispatch.
    if not user_path.exists():
        raise FileNotFoundError(f"missing {user_path}")

    for stale in ("board.html", "board.png", "cli.log", "cli2.log",
                  "timing.json", "render-meta.json", "lint.json",
                  "fix-prompt.md"):
        try:
            (run_dir / stale).unlink()
        except OSError:
            pass

    extra = homework_image_args(case)
    # Long system prompts exceed argv limits: fall back to --append-system-prompt
    # with the file path (keeps pi's default preamble, acceptable fallback).
    use_append = len(system_text.encode("utf-8")) > 80000
    argv = member_argv(member, thinking, system_text, user_path, extra,
                       use_append, sys_path)

    rc, wall1, err = spawn(argv, run_dir, run_dir / "cli.log", TIMEOUT_S)
    total_wall = wall1
    raw = (run_dir / "cli.log").read_text(encoding="utf-8", errors="replace")
    parsed = parse_pi_jsonl(raw)
    reply = parsed.get("reply", "")
    error = err
    if error is None and rc != 0:
        error = f"exit={rc}"
    html = extract_html(reply) if error is None else None
    if error is None and html is None:
        error = "no HTML extracted"
    if html is not None:
        (run_dir / "board.html").write_text(html, encoding="utf-8")

    fix_used = False
    render_info: dict = {}
    lint: dict = {}
    if error is None:
        render_info = run_node_render(run_dir, toolkit_file, toolkit_url)
        # Production one-shot never renders server-side: the render only counts
        # toward wall time when a fix pass needs it.
        if fix_pass:
            total_wall += render_info.get("wall_s", 0)
        if render_info.get("error"):
            error = f"render failed: {render_info['error']}"
        else:
            lint = run_node_lint(run_dir, toolkit_file, toolkit_url)
            (run_dir / "lint.json").write_text(
                json.dumps(lint, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            # Fix only on findings a child would notice: text off screen, overlaps, JS errors.
            found = bool(lint.get("outside") or lint.get("overlaps") or
                         (render_info.get("meta", {}) or {}).get("page_errors"))
            if fix_pass == "always" or (fix_pass and found):
                # ONE follow-up call with the PNG attached + lint findings.
                fix_used = True
                findings = lint_findings_text(
                    lint, render_info.get("meta", {}) or {})
                head = ("The board you made has these problems on its 1920x1080 screenshot:\n\n"
                        f"{findings}\n\n") if found else (
                        "Before the child sees it, look at the attached settled screenshot of your "
                        "board as the child will. Check every number, every claim, every drawn "
                        "quantity and position, the language, and that everything is readable and "
                        "inside the screen. If anything is wrong or unclear, fix it; if it is right, "
                        "return it unchanged.\n\n")
                fix_md = (
                    head +
                    "Your HTML was:\n\n```html\n"
                    + (run_dir / "board.html").read_text(encoding="utf-8") +
                    "\n```\n\n"
                    "The settled screenshot of it is attached. The original request comes first. "
                    "Return the corrected full HTML document only, "
                    "starting with <!doctype html>. No explanation before or after."
                )
                (run_dir / "fix-prompt.md").write_text(fix_md, encoding="utf-8")
                # Order: original request, then the fix note with the HTML, then the PNG.
                argv2 = member_argv(member, thinking, system_text, user_path,
                                    [f"@{run_dir / 'fix-prompt.md'}", f"@{run_dir / 'board.png'}", *extra],
                                    use_append, sys_path)
                rc2, wall2, err2 = spawn(argv2, run_dir, run_dir / "cli2.log", TIMEOUT_S)
                total_wall += wall2
                # Re-render counts toward total wall too (measured inside).
                raw2 = (run_dir / "cli2.log").read_text(encoding="utf-8", errors="replace")
                parsed2 = parse_pi_jsonl(raw2)
                reply2 = parsed2.get("reply", "")
                # Merge token usage across both calls when available.
                for k in ("input_tokens", "output_tokens", "reasoning_tokens"):
                    a, b = parsed.get(k), parsed2.get(k)
                    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                        parsed[k] = a + b
                    elif b is not None:
                        parsed[k] = b
                if err2 is not None:
                    error = f"fix call: {err2}"
                elif rc2 != 0:
                    error = f"fix call exit={rc2}"
                else:
                    html2 = extract_html(reply2)
                    if html2 is None:
                        error = "fix call: no HTML extracted"
                    else:
                        (run_dir / "board.html").write_text(html2, encoding="utf-8")
                        parsed["reply"] = reply2
                if error is None or error.startswith("render failed"):
                    error = None
                    render_info = run_node_render(run_dir, toolkit_file, toolkit_url)
                    total_wall += render_info.get("wall_s", 0)
                    if render_info.get("error"):
                        error = f"re-render failed: {render_info['error']}"
                    else:
                        lint = run_node_lint(run_dir, toolkit_file, toolkit_url)
                        (run_dir / "lint.json").write_text(
                            json.dumps(lint, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
    else:
        # No HTML: still write empty lint + render-meta for shape consistency.
        (run_dir / "lint.json").write_text(
            json.dumps({"clean": None, "error": error}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        (run_dir / "render-meta.json").write_text(
            json.dumps(render_info.get("meta", {}), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")

    if not (run_dir / "render-meta.json").exists():
        (run_dir / "render-meta.json").write_text(
            json.dumps(render_info.get("meta", {}), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
    if not (run_dir / "lint.json").exists():
        (run_dir / "lint.json").write_text(
            json.dumps(lint or {"clean": None}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")

    html_bytes = 0
    if (run_dir / "board.html").exists():
        html_bytes = (run_dir / "board.html").stat().st_size

    timing = {"wall_s": round(total_wall, 2),
              "first_wall_s": round(wall1, 2),
              "fix_used": fix_used,
              "thinking": thinking,
              "timeout_s": TIMEOUT_S,
              "input_tokens": parsed.get("input_tokens"),
              "output_tokens": parsed.get("output_tokens"),
              "reasoning_tokens": parsed.get("reasoning_tokens"),
              "api_ms": parsed.get("api_ms")}
    (run_dir / "timing.json").write_text(
        json.dumps(timing, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    ok = error is None
    record = {"round": round_id, "member": member, "case": case_id,
              "split": case.get("split"),
              "wall_s": round(total_wall, 2),
              "ok": ok, "error": error,
              "lint_clean": (lint or {}).get("clean"),
              "lint_findings": count_lint(lint or {}),
              "html_bytes": html_bytes,
              "input_tokens": parsed.get("input_tokens"),
              "output_tokens": parsed.get("output_tokens")}
    append_result(record)
    log(f"{'ok' if ok else 'FAIL'} {member} {case_id} wall={total_wall:.1f}s {error or ''}")
    return record


def append_result(record: dict):
    RESULTS = DATA / "results.jsonl"
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with _results_lock:
        with open(RESULTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--panel", default=None, help="tune|hidden")
    ap.add_argument("--members", default=None, help="comma-separated member ids")
    ap.add_argument("--cases", default=None, help="comma-separated case ids")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    cfg_path = Path(a.config)
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    round_id = cfg["round"]
    prompt_rel = cfg.get("prompt", "prompts/r0")
    thinking = cfg.get("thinking", "low")
    fix_pass = cfg.get("fix_pass", False)  # bool, "always", or {member: ...}
    toolkit = cfg.get("toolkit")
    toolkit_file = toolkit_url = None
    if isinstance(toolkit, dict):
        toolkit_file = toolkit.get("file")
        toolkit_url = toolkit.get("url")

    prompt_cfg = prompt_rel if isinstance(prompt_rel, dict) else {"default": prompt_rel}
    def tpl_for(member):
        d = prompt_cfg.get(member, prompt_cfg.get("default", "prompts/r0"))
        return ((GYM / d / "system.md").read_text(encoding="utf-8"),
                (GYM / d / "user.md").read_text(encoding="utf-8"))
    sys_tpl, user_tpl = tpl_for("default")

    panels_data = json.loads((CASES / "panels.json").read_text(encoding="utf-8"))
    if a.cases:
        case_ids = [c.strip() for c in a.cases.split(",") if c.strip()]
    else:
        wanted = [a.panel] if a.panel else cfg.get("panels", ["tune", "hidden"])
        case_ids = []
        for p in wanted:
            case_ids.extend(panels_data.get(p, []))

    if a.members:
        members = [m.strip() for m in a.members.split(",") if m.strip()]
    else:
        members = list(cfg.get("members", []))

    # Load cases + write prompts up front (cheap, fails fast on bad ids).
    jobs = []
    for member in members:
        for cid in case_ids:
            cpath = CASES / f"{cid}.json"
            if not cpath.exists():
                log(f"missing case {cid}, skipping")
                continue
            case = json.loads(cpath.read_text(encoding="utf-8"))
            run_dir = DATA / "runs" / round_id / member / cid
            run_dir.mkdir(parents=True, exist_ok=True)
            m_sys, m_user = tpl_for(member)
            system_text = fill_template(m_sys, case)
            user_text = fill_template(m_user, case)
            (run_dir / "prompt-system.md").write_text(system_text, encoding="utf-8")
            (run_dir / "prompt-user.md").write_text(user_text, encoding="utf-8")
            jobs.append((member, cid, case, system_text))

    log(f"round {round_id}: {len(jobs)} runs ({len(members)} members x {len(case_ids)} cases) "
        f"fix_pass={fix_pass} thinking={thinking}")

    global_sem = threading.Semaphore(4)  # at most 4 pi calls in flight
    member_locks = {m: threading.Lock() for m in members}

    def one(job):
        member, cid, case, system_text = job
        with global_sem:
            with member_locks[member]:
                try:
                    th = (thinking.get(member, thinking.get("default", "low"))
                          if isinstance(thinking, dict) else thinking)
                    fx = (fix_pass.get(member, fix_pass.get("default", False))
                          if isinstance(fix_pass, dict) else fix_pass)
                    return do_run(round_id, member, cid, case, system_text,
                                  th, fx, toolkit_file, toolkit_url,
                                  a.force)
                except Exception as e:  # never let one run kill the batch
                    log(f"ERROR {member} {cid}: {e}")
                    rec = {"round": round_id, "member": member, "case": cid,
                           "split": case.get("split"), "wall_s": None,
                           "ok": False, "error": f"harness: {e}"}
                    append_result(rec)
                    return rec

    # At most 4 workers: matches the in-flight cap; per-member locks keep
    # each member serial so timings don't interfere within a member.
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(jobs)))) as ex:
        list(ex.map(one, jobs))


if __name__ == "__main__":
    sys.exit(main())
