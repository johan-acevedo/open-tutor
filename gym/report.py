#!/usr/bin/env python3
"""Board gym report: aggregates + private progress site.

    python3 gym/report.py [--round r0]

Reads $GYM_DATA/results.jsonl (with judge scores merged in) and writes:
  - gym/scores/<round>.json   aggregates only (numbers, no conversation
                              quotes) — committed to git
  - $GYM_DATA/site/            private static site (PNGs + judge notes live
                              here, never in git): index.html serving
    (a) leaderboard with targets (median wall <= 15 s, >= 90% correct,
        clarity >= 4.5), (b) per-member quality/speed charts per round
        (inline SVG), (c) case browser with side-by-side PNGs + judge notes,
    (d) "what changed" per round from the notes: field in gym/configs/.
"""
import argparse
import datetime
import json
import os
import shutil
import statistics
import sys
from pathlib import Path

import yaml

GYM = Path(__file__).resolve().parent
DATA = Path(os.environ.get("GYM_DATA", Path.home() / "gym-data" / "board-gym"))
SITE = DATA / "site"
SCORES = GYM / "scores"

TARGET_WALL = 15.0
TARGET_CORRECT = 90.0
TARGET_CLARITY = 4.5


def log(*a):
    print(*a, flush=True)


def median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def p90(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = min(len(xs) - 1, int(0.9 * (len(xs) - 1) + 0.5))
    return round(xs[k], 2)


def load_results():
    p = DATA / "results.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def round_notes(round_id: str) -> str:
    for ext in ("yaml", "yml"):
        p = GYM / "configs" / f"{round_id}.{ext}"
        if p.exists():
            try:
                return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("notes", "") or ""
            except yaml.YAMLError:
                return ""
    return ""


def aggregate(records: list) -> dict:
    """{(round, member, split): stats}."""
    groups: dict = {}
    for r in records:
        groups.setdefault((r.get("round"), r.get("member"), r.get("split")), []).append(r)
    out = {}
    for (rnd, member, split), rs in sorted(groups.items()):
        walls = [r.get("wall_s") for r in rs if r.get("wall_s") is not None]
        judged = [r for r in rs if isinstance(r.get("judge"), dict)]
        correct = [r for r in judged if r["judge"].get("correct")]
        clars = [r["judge"].get("clarity") for r in judged
                 if r["judge"].get("clarity") is not None]
        out[(rnd, member, split)] = {
            "n": len(rs),
            "judged": len(judged),
            "fail": sum(1 for r in rs if not r.get("ok")),
            "pct_correct": round(100 * len(correct) / len(judged), 1) if judged else None,
            "mean_clarity": mean(clars),
            "median_wall": median(walls),
            "p90_wall": p90(walls),
        }
    return out


# ---------------------------------------------------------------- svg charts

def svg_line(series: dict, title: str, fmt: str = "{:.2f}") -> str:
    """series: {label: {round: value}}. One polyline per label. Small dark SVG."""
    rounds = sorted({r for vals in series.values() for r in vals})
    vals = [v for m in series.values() for v in m.values() if v is not None]
    if not rounds or not vals:
        return f"<p class=muted>{title}: no data yet</p>"
    lo, hi = min(vals), max(vals)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    W, H, P = 520, 180, 34
    def x(i): return P + i * (W - 2 * P) / max(1, len(rounds) - 1)
    def y(v): return H - P - (v - lo) / (hi - lo) * (H - 2 * P)
    colors = ["#22D3EE", "#A78BFA", "#34D399", "#F59E0B", "#F3F5F8", "#DC4A4A"]
    s = [f"<svg viewBox='0 0 {W} {H}' class=chart role=img aria-label='{title}'>"]
    for i, r in enumerate(rounds):
        s.append(f"<text x={x(i):.0f} y={H-8:.0f} class=axis>{r}</text>")
        s.append(f"<line x1={x(i):.0f} y1=8 x2={x(i):.0f} y2={H-P} class=grid />")
    s.append(f"<text x=4 y=14 class=axis>{fmt.format(hi)}</text>")
    s.append(f"<text x=4 y={H-P+4:.0f} class=axis>{fmt.format(lo)}</text>")
    for k, (label, m) in enumerate(sorted(series.items())):
        pts = [(x(i), y(m[r])) for i, r in enumerate(rounds) if m.get(r) is not None]
        if not pts:
            continue
        c = colors[k % len(colors)]
        if len(pts) == 1:
            s.append(f"<circle cx={pts[0][0]:.1f} cy={pts[0][1]:.1f} r=4 fill='{c}' />")
        else:
            s.append("<polyline points='" + " ".join(f"{a:.1f},{b:.1f}" for a, b in pts) +
                     f"' fill=none stroke='{c}' stroke-width=2 />")
            for a, b in pts:
                s.append(f"<circle cx={a:.1f} cy={b:.1f} r=3 fill='{c}' />")
    s.append("</svg>")
    return "\n".join(s)


# ---------------------------------------------------------------- site

CSS = """
:root{color-scheme:dark}*{box-sizing:border-box}
body{background:#181B22;color:#F3F5F8;font-family:"Segoe UI",Roboto,system-ui,sans-serif;margin:0;padding:16px;max-width:1100px}
h1{font-size:1.4rem;margin:.2em 0}h2{font-size:1.1rem;margin:1.4em 0 .5em;color:#9BA3B4;text-transform:uppercase;letter-spacing:.06em;font-size:.85rem}
a{color:#22D3EE}.muted{color:#9BA3B4}.card{background:#222731;border:1px solid #2E3543;border-radius:12px;padding:12px;margin:8px 0}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{text-align:left;padding:8px;border-bottom:1px solid #2E3543}
th{color:#9BA3B4;font-weight:600}.pass{color:#34D399}.fail{color:#DC4A4A}
.chart{width:100%;max-width:560px;height:auto;background:#181B22;border:1px solid #2E3543;border-radius:8px}
.chart .axis{fill:#9BA3B4;font-size:11px}.chart .grid{stroke:#2E3543}
.grid2{display:grid;grid-template-columns:1fr;gap:12px}@media(min-width:760px){.grid2{grid-template-columns:1fr 1fr}}
img.board{width:100%;height:auto;border-radius:8px;border:1px solid #2E3543}
select{background:#222731;color:#F3F5F8;border:1px solid #2E3543;border-radius:8px;padding:10px;font-size:1rem;width:100%}
.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:.8rem;border:1px solid #2E3543}
"""

SITE_TMPL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Board gym</title><style>{css}</style></head>
<body>
<h1>Board gym</h1>
<p class=muted>Generated {at} · targets: hidden &ge;90% correct · clarity &ge;4.5 · median wall &le;15 s</p>

<h2>Leaderboard</h2>
<div class=card><table id=lb>
<tr><th>Member</th><th>Best round</th><th>Hidden % correct</th><th>Clarity</th><th>Median wall</th></tr>
{lb_rows}
</table></div>

<h2>Quality &amp; speed per round</h2>
<div class=grid2>{charts}</div>

<h2>What changed</h2>
{notes}

<h2>Case browser</h2>
<div class=card>
<select id=case></select>
<div id=boards></div>
</div>

<script>
const DATA = {data};
const sel = document.getElementById('case'), box = document.getElementById('boards');
DATA.cases.forEach(c => {{ const o = document.createElement('option'); o.value = c.id; o.textContent = c.label; sel.appendChild(o); }});
function show() {{
  const id = sel.value;
  box.innerHTML = '';
  DATA.boards.filter(b => b.case === id).forEach(b => {{
    const d = document.createElement('div'); d.className = 'card';
    const ok = b.correct === null ? '<span class=pill>unjudged</span>'
      : b.correct ? '<span class="pill pass">correct</span>' : '<span class="pill fail">not correct</span>';
    d.innerHTML = `<b>${{b.member}}</b> · round ${{b.round}} · ${{b.split}} · ${{ok}}`
      + ` · clarity ${{b.clarity ?? '–'}} · fits ${{b.fits ?? '–'}} · wall ${{b.wall ?? '–'}} s`
      + (b.issues && b.issues.length ? `<br><span class=muted>${{b.issues.map(i => '• ' + i).join('<br>')}}</span>` : '')
      + `<br><a href="${{b.png}}"><img class=board loading=lazy src="${{b.png}}" alt="board ${{b.case}} ${{b.member}}"></a>`;
    box.appendChild(d);
  }});
}}
sel.addEventListener('change', show);
if (DATA.cases.length) {{ sel.value = DATA.cases[0].id; show(); }}
</script>
</body></html>
"""


def build_site(records: list, agg: dict, rounds: list):
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "boards").mkdir(exist_ok=True)

    # Copy PNGs into the site (private dir, never git).
    boards = []
    for r in records:
        png = RUNS_DIR / r["round"] / r["member"] / r["case"] / "board.png"
        dest = SITE / "boards" / r["round"] / r["member"] / f"{r['case']}.png"
        if png.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(png, dest)
            rel = f"boards/{r['round']}/{r['member']}/{r['case']}.png"
        else:
            rel = ""
        j = r.get("judge") or {}
        boards.append({"round": r["round"], "member": r["member"], "case": r["case"],
                       "split": r.get("split"), "wall": r.get("wall_s"),
                       "correct": j.get("correct"), "clarity": j.get("clarity"),
                       "fits": j.get("fits_request"), "issues": j.get("issues", []),
                       "png": rel})

    # Leaderboard: best round per member by hidden pct_correct.
    members = sorted({r["member"] for r in records})
    lb_rows = []
    for m in members:
        hidden = {rnd: agg[(rnd, m, sp)] for (rnd, mm, sp) in agg
                  if mm == m and sp == "hidden" and agg[(rnd, mm, sp)]["judged"]}
        if hidden:
            best = max(hidden, key=lambda r: (hidden[r]["pct_correct"] or -1,
                                              -(hidden[r]["median_wall"] or 1e9)))
            s = hidden[best]
            pc, cl, w = s["pct_correct"], s["mean_clarity"], s["median_wall"]
        else:
            best, pc, cl, w = "–", None, None, None
        def cell(v, tgt, low_good=False, suffix=""):
            if v is None:
                return "<td>–</td>"
            good = (v <= tgt) if low_good else (v >= tgt)
            cls = "pass" if good else "fail"
            return f"<td class={cls}>{v}{suffix}</td>"
        lb_rows.append(f"<tr><td>{m}</td><td>{best}</td>"
                       f"{cell(pc, TARGET_CORRECT, suffix='%')}"
                       f"{cell(cl, TARGET_CLARITY)}"
                       f"{cell(w, TARGET_WALL, low_good=True, suffix=' s')}</tr>")

    # Per-member charts (quality = mean clarity, speed = median wall per round).
    charts = []
    for m in members:
        q, s = {}, {}
        for (rnd, mm, sp) in agg:
            if mm != m:
                continue
            q.setdefault(sp, {})[rnd] = agg[(rnd, mm, sp)]["mean_clarity"]
            s.setdefault(sp, {})[rnd] = agg[(rnd, mm, sp)]["median_wall"]
        charts.append(f"<div class=card><b>{m}</b>"
                      f"<p class=muted>clarity per round</p>{svg_line(q, 'clarity')}"
                      f"<p class=muted>median wall (s) per round</p>"
                      f"{svg_line(s, 'wall', fmt='{:.1f}')}</div>")

    notes = []
    for rnd in rounds:
        n = round_notes(rnd) or "(no notes)"
        notes.append(f"<div class=card><b>{rnd}</b><br>{n}</div>")

    # Case labels (private site may carry titles/grades).
    cases = {}
    for r in records:
        c = cases.setdefault(r["case"], {"rounds": set(), "members": set()})
        c["rounds"].add(r["round"])
        c["members"].add(r["member"])
    case_list = []
    for cid in sorted(cases):
        info = cases[cid]
        label = cid
        try:
            cj = json.loads((CASES_DIR / f"{cid}.json").read_text(encoding="utf-8"))
            lg = cj.get("learner", {}).get("grade")
            tool = (cj.get("request") or {}).get("tool")
            title = (cj.get("request") or {}).get("title")
            label = f"{cid} · grade {lg} · {tool} · {title}"
        except (OSError, json.JSONDecodeError):
            pass
        case_list.append({"id": cid, "label": label})

    data = {"cases": case_list, "boards": sorted(boards, key=lambda b: (b["case"], b["round"], b["member"]))}
    html = SITE_TMPL.format(
        css=CSS, at=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        lb_rows="\n".join(lb_rows), charts="\n".join(charts),
        notes="\n".join(notes),
        data=json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    (SITE / "index.html").write_text(html, encoding="utf-8")
    log(f"wrote {SITE / 'index.html'} ({len(boards)} boards)")


RUNS_DIR = DATA / "runs"
CASES_DIR = DATA / "cases"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", default=None)
    a = ap.parse_args()

    records = load_results()
    if a.round:
        records = [r for r in records if r.get("round") == a.round]
    if not records:
        log("no results yet")
        return
    agg = aggregate(records)
    rounds = sorted({r["round"] for r in records})

    SCORES.mkdir(parents=True, exist_ok=True)
    for rnd in rounds:
        doc = {"round": rnd,
               "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               "notes": round_notes(rnd),
               "targets": {"median_wall_s": TARGET_WALL, "pct_correct": TARGET_CORRECT,
                           "mean_clarity": TARGET_CLARITY},
               "members": {}}
        for (r2, m, sp), s in sorted(agg.items()):
            if r2 != rnd:
                continue
            doc["members"].setdefault(m, {})[sp] = s
        p = SCORES / f"{rnd}.json"
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        log(f"wrote {p}")

    build_site(records, agg, rounds)


if __name__ == "__main__":
    sys.exit(main())
