#!/usr/bin/env python3
"""Re-render and re-lint every finished run of a round without calling any member.

    python3 gym/rerender.py --round r0

Also resets wall_s to model time (+ render only when the run used a fix pass),
and drops that round's judge verdicts so judge.py scores the new PNGs.
"""
import argparse, json, shutil, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import DATA, run_node_render, run_node_lint, count_lint  # noqa: E402


def one(d: Path):
    r = run_node_render(d, None, None)
    lint = run_node_lint(d, None, None)
    (d / "lint.json").write_text(json.dumps(lint, ensure_ascii=False, indent=1) + "\n")
    t = json.loads((d / "timing.json").read_text())
    if not t.get("fix_used"):
        t["wall_s"] = t.get("first_wall_s", t["wall_s"])
    (d / "timing.json").write_text(json.dumps(t, indent=1) + "\n")
    return d, r.get("error"), lint, t["wall_s"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--round", required=True)
    a = ap.parse_args()
    dirs = sorted(p.parent for p in (DATA / "runs" / a.round).glob("*/*/board.html"))
    with ThreadPoolExecutor(6) as ex:
        done = {(d.parent.name, d.name): (err, lint, w) for d, err, lint, w in ex.map(one, dirs)}
    rp = DATA / "results.jsonl"
    out = []
    for ln in rp.read_text().splitlines():
        r = json.loads(ln)
        k = (r.get("member"), r.get("case"))
        if r.get("round") == a.round:
            r.pop("judge", None)
            if k in done:
                err, lint, w = done[k]
                r["wall_s"] = w
                r["lint_clean"] = lint.get("clean")
                r["lint_findings"] = count_lint(lint)
                r["rerendered"] = True
                if err:
                    r["ok"], r["error"] = False, f"render failed: {err}"
        out.append(json.dumps(r, ensure_ascii=False))
    rp.write_text("\n".join(out) + "\n")
    jd = DATA / "judge" / a.round
    if jd.exists():
        shutil.move(str(jd), str(jd) + ".stale-1.5s-screenshots")
    print(f"re-rendered {len(dirs)} boards; judge dir moved aside")


if __name__ == "__main__":
    main()
