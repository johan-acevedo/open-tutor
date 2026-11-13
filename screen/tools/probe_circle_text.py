"""Compare two candidate reference lines against the unsteered reference.

Circle and positioned text in a graph: what the page writer does with the
current ``screen/REFERENCE.md``, and what changes when two short candidate
lines are added to the same static prompt. Each ask is run twice - baseline
and candidate - with the same lesson, pane and request controls.

  run      Real Screen jobs (the deployed writer, the real prompt and
           renderer). Saves the model's unedited first answer (``raw.html``),
           the delivered page (``delivered.html``, after any look/lint
           repair), its meta and timings, then measures ``raw.html`` at
           370x610 and 1000x700.
  measure  Re-render saved bodies and measure them, without provider calls or
           keys. Chromium still fetches the usual public shell CDN assets.
  patch    One real tutor follow-up on a delivered page: a real patch, applied,
           then measured and pointed at.
  selftest Render a hand-written body that uses the candidate syntax, to check
           what the shell really does with it (no provider call).

The candidate text is appended to the static system prompt for the steered
case only. Nothing under ``screen/`` besides the case folder is written, and
``REFERENCE.md`` itself is not touched: the comparison injects the candidate
in this process, so the baseline and the candidate run in the same batch.

  # real jobs (needs the provider key; never in CI)
  OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env env \
    SCREEN_MODEL=gemini-4-hydrogen SCREEN_API=chat SCREEN_REASONING=low SCREEN_THINKING= \
    uv run --project server python screen/tools/probe_circle_text.py run \
      --out /tmp/circle-text --cases cirkel-bas,cirkel-ref,vinkel-bas,vinkel-ref
  # one tutor follow-up on the delivered candidate page
  ... probe_circle_text.py patch --dir /tmp/circle-text --case vinkel-ref
  # re-render and re-measure saved bodies (no key)
  uv run --project server python screen/tools/probe_circle_text.py measure --dir /tmp/circle-text

Measurements are shallow and honest: they compare the drawn shape with its
label, the drawn angle with the given one, and each label's box with the line
it sits next to. They do not judge whether the picture teaches well.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import pathlib
import re
import hashlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT.parent / "server"))

SIZES = ((370, 610), (1000, 700))

# Historical Swedish candidate, preserved to reproduce the original arms.
CANDIDATE = """**Cirkel.** Det finns ingen cirkeltagg: rita bågen som två kurvor i en `ot-graph`, med samma färg.
`<ot-point id="medelpunkt" x="0" y="0">`, `<ot-segment id="radie" from="0 0" to="4 0">4 cm</ot-segment>`,
`<ot-fn color="cyan" domain="-4 4">sqrt(16 - x^2)</ot-fn>` och `<ot-fn color="cyan" domain="-4 4">-sqrt(16 - x^2)</ot-fn>`
(16 är radien i kvadrat; flytta x och y för en annan medelpunkt). Givna mått skrivs ut, arean ritas inte.

`<ot-text id="…" x="2" y="2">60°</ot-text>` skriver en text centrerad på punkten (x, y) i grafens
koordinater. Den flyttas bara in i grafens ruta, aldrig undan från linjer: välj en punkt med luft runt."""

# v2: the same two blocks, with the measured constraint on a wide label spelled out.
# v1 and v2 use different positions for the wide text.
# The original projection-only measurement called this overlap; parent review
# corrected that false positive. Both wordings are kept as observed evidence.
CANDIDATE_V2 = CANDIDATE.replace(
    "Den flyttas bara in i grafens ruta, aldrig undan från linjer: välj en punkt med luft runt.",
    "Inget flyttar texten undan en linje, och en bred text når tillbaka halva sin bredd: "
    "lägg punkten utanför figuren, inte på en linje och inte vid en linjes ände.")

CHILD = "Jag har prov på geometri imorgon och blandar ihop begreppen."
LEARNER = {"name": "Nova", "grade": 6}

# Baseline asks: only documented reference syntax, phrased as a tutor would say it.
# The same ask is used for the baseline and the candidate case.
ASKS = {
    "cirkel": (
        "Rita en cirkel med radien 4 cm. Visa radien som ett streck från medelpunkten med måttet "
        "4 cm, och eleven ska kunna peka på radien. Det givna måttet ska synas. Arean får inte synas."
    ),
    "vinkel": (
        "Visa en vinkel som är 60 grader. Det ena vinkelbenet går från spetsen till (5, 0), det andra "
        "till (2,5, 4,3). Skriv 60° strax innanför spetsen, inne i vinkeln, och skriv Vinkelben vid "
        "slutet av det sneda benet. Eleven ska kunna peka på vinkelspetsen. Rita ingen båge och räkna "
        "inte ut något."
    ),
}

# Forbidden visible text per ask: a result the child has not been asked for.
FORBID = {
    "cirkel": ["area", "50,2", "50.2", "12,5", "cm²", "cm2", "omkrets"],
    "vinkel": ["cos", "sin", "tan", "30°", "30 grader", "120°"],
}

CASES = {
    "cirkel-bas": {"base": "cirkel", "steer": False},
    "cirkel-ref": {"base": "cirkel", "steer": True},
    "vinkel-bas": {"base": "vinkel", "steer": False},
    "vinkel-ref": {"base": "vinkel", "steer": True},
    "vinkel-ref2": {"base": "vinkel", "steer": True, "candidate": CANDIDATE_V2},
    "cirkel-final": {"base": "cirkel", "steer": True, "shipped": True},
    "vinkel-final": {"base": "vinkel", "steer": True, "shipped": True},
}

PATCH = {
    "vinkel-ref": (
        "Lägg Vinkelben utanför det sneda benets ände så att texten inte rör linjen, och flytta 60° "
        "närmare spetsen. Eleven ska kunna peka på vinkelspetsen. Ändra bara etiketternas läge."
    ),
}


def ask_for(case_id: str) -> tuple[str, str, bool]:
    case = CASES[case_id]
    return ASKS[case["base"]], case["base"], case["steer"]


def candidate_for(case_id: str) -> str:
    if CASES[case_id].get("shipped"):
        ref = (ROOT / "REFERENCE.md").read_text()
        return ref[ref.index("**Circle:"):ref.index("\n**Chart**")].strip()
    return CASES[case_id].get("candidate", CANDIDATE)


def baseline_prompt() -> str:
    """Pin the baseline reference so adding the candidate cannot contaminate it."""
    from screen.tools import prompt as screen_prompt
    current = (ROOT / "REFERENCE.md").read_text().strip()
    baseline = subprocess.run(
        ["git", "show", "848f8c1:screen/REFERENCE.md"], cwd=ROOT.parent,
        check=True, capture_output=True, text=True).stdout.strip()
    prompt = screen_prompt.system_prompt()
    if prompt.count(current) != 1:
        raise ValueError("reference is not present exactly once in the static prompt")
    return prompt.replace(current, baseline, 1)


def spec_for(name: str) -> tuple[str, bool]:
    """(base ask name, steered?) for a case folder, including patched folders."""
    for case_id in sorted(CASES, key=len, reverse=True):
        if name == case_id or name.startswith(case_id + "-"):
            return CASES[case_id]["base"], CASES[case_id]["steer"]
    return name.split("-")[0], "-ref" in name


# --------------------------------------------------------------------- pages

MEASURE_JS = r"""
() => {
  const num = v => parseFloat(String(v || '').replace(',', '.'));
  // The shell's own attribute reading (shell.js nums/points), so decimal commas
  // and pair separators are split exactly as the page is drawn.
  const nums = s => String(s || '').replace(/[()]/g, ' ').replace(/−/g, '-')
      .split(/[\s;]+|,\s+|,(?=-?\d+,)/).filter(t => t !== '').map(num)
      .filter(n => !isNaN(n));
  const pairs = s => { const a = nums(s), out = [];
    for (let i = 0; i + 1 < a.length; i += 2) out.push([a[i], a[i + 1]]); return out; };
  const graphs = [...document.querySelectorAll('ot-graph')].map(g => {
    const gr = g.getBoundingClientRect();
    const b = g._board;
    const origin = g._px ? g._px(0, 0) : null;
    const shapes = [...g.children].filter(c => c.tagName.startsWith('OT-')).map(c => {
      const tag = c.tagName;
      const xy = tag === 'OT-SEGMENT' ? pairs((c.getAttribute('from') || '') + ', ' + (c.getAttribute('to') || ''))
        : tag === 'OT-POLYGON' ? pairs(c.getAttribute('points'))
        : tag === 'OT-TEXT' ? pairs((c.getAttribute('x') || '') + ' ' + (c.getAttribute('y') || ''))
        : tag === 'OT-POINT' ? pairs((c.getAttribute('x') || '') + ' ' + (c.getAttribute('y') || ''))
        : [];
      const px = xy.map(([x, y]) => {
        if (isNaN(x) || isNaN(y) || !g._px) return null;
        const p = g._px(x, y); return {x: p.x, y: p.y, ux: x, uy: y};
      });
      const drawn = (c._jxg || []).map(o => {
        let box = null;
        try {
          const n = o.rendNode;
          if (n && n.getBoundingClientRect) {
            const r = n.getBoundingClientRect();
            box = {x: r.left - gr.left, y: r.top - gr.top, w: r.width, h: r.height};
          }
        } catch (e) { /* no node */ }
        let sw = null;
        try { sw = o.visProp ? o.visProp.strokewidth : null; } catch (e) { /* none */ }
        return {type: o.elType || null, box, strokeWidth: sw};
      });
      return {tag: tag.toLowerCase(), id: c.id || null, points: c.getAttribute('points'),
              sides: c.getAttribute('sides'), from: c.getAttribute('from'), to: c.getAttribute('to'),
              x: c.getAttribute('x'), y: c.getAttribute('y'), domain: c.getAttribute('domain'),
              color: c.getAttribute('color'), text: (c.textContent || '').trim(), px, drawn};
    });
    const labels = [...g.querySelectorAll('.ot-lbl')].map(l => {
      const r = l.getBoundingClientRect();
      return {text: (l.textContent || '').trim(), x: r.left - gr.left, y: r.top - gr.top,
              w: r.width, h: r.height};
    });
    return {id: g.id || null, w: g.clientWidth, h: g.clientHeight, x: g.getAttribute('x'),
            y: g.getAttribute('y'), axes: g.getAttribute('axes'),
            unitX: b ? b.unitX : null, unitY: b ? b.unitY : null,
            origin: origin ? {x: origin.x, y: origin.y} : null, shapes, labels};
  });
  // Lint before the pointing sweep: pointing at an id the page lacks would add issues.
  const issues = window.ot.issues.slice();
  const ids = [...document.querySelectorAll('[id]')].map(e => e.id).filter(id => !id.startsWith('jxg-'));
  const snap = () => {
    let kids = 0, sw = 0;
    [...document.querySelectorAll('ot-graph')].forEach(g => {
      try { kids += g.layer().children.length; } catch (e) { /* no layer */ }
      [...g.children].forEach(c => (c._jxg || []).forEach(o => {
        try { sw += o.visProp.strokewidth || 0; } catch (e) { /* none */ }
      }));
    });
    return {kids, sw: Math.round(sw * 100) / 100,
            pointed: document.querySelectorAll('.ot-pointed').length};
  };
  const point = {};
  ids.forEach(id => {
    const before = snap();
    let ok = false;
    try { ok = !!window.ot.point(id); } catch (e) { ok = false; }
    const after = snap();
    try { window.ot.point(null); } catch (e) { /* none */ }
    point[id] = {ok, effect: {kids: after.kids - before.kids,
                              pointed: after.pointed - before.pointed,
                              strokeWidth: Math.round((after.sw - before.sw) * 100) / 100}};
  });
  return {fontPx: window.ot.fontPx, issues, graphs, ids, point,
          text: document.body.innerText || '', hiddenText: document.body.textContent || ''};
}
"""


def _frame(page):
    return page.frames[1] if len(page.frames) > 1 else page.main_frame


def measure_body(body: str, name: str, out: pathlib.Path, browser,
                 patch: str | None = None) -> dict:
    """Render one body at both sizes, screenshot it and collect its geometry.
    With `patch`, the page is measured after the change, like the child's screen."""
    import screenkit

    report: dict = {"name": name, "sizes": {}}
    doc = screenkit.compose(body)
    out.mkdir(parents=True, exist_ok=True)
    for (w, h) in SIZES:
        key = f"{w}x{h}"
        page = browser.new_page(viewport={"width": w, "height": h})
        try:
            page.set_content(screenkit.host_page(doc))
            frame = _frame(page)
            frame.wait_for_function(
                "() => document.documentElement.dataset.otReady === '1'", timeout=30000)
            report["sizes"].setdefault(key, {})
            if patch:
                report["sizes"][key]["patch_issues"] = frame.evaluate("(p) => ot.patch(p)", patch)
                frame.evaluate("""async () => {
                    for (const a of document.getAnimations()) {
                        if (Number.isFinite(a.effect.getComputedTiming().endTime)) a.finish();
                    }
                    await new Promise(requestAnimationFrame);
                }""")
                page.wait_for_timeout(300)
            info = frame.evaluate(MEASURE_JS)
            page.screenshot(path=str(out / f"{name}-{key}{'-patched' if patch else ''}.png"))
        finally:
            page.close()
        report["sizes"][key].update(info)
    return report


# ------------------------------------------------------------------ analysis

NUM = re.compile(r"(\d+(?:[.,]\d+)?)")


def label_number(text: str) -> float | None:
    """The first number in a label, e.g. '4 cm', '$4$ cm', '4,5', '60°'."""
    found = NUM.search(text or "")
    if not found:
        return None
    return float(found.group(1).replace(",", "."))


def unit_len(a: dict, b: dict) -> float:
    return math.hypot(b["ux"] - a["ux"], b["uy"] - a["uy"])


def px_len(a: dict, b: dict) -> float:
    return math.hypot(b["x"] - a["x"], b["y"] - a["y"])


def seg_dist(p: dict, a: dict, b: dict) -> float:
    """Distance from point p to the segment ab, in pixels."""
    ax, ay, bx, by = a["x"], a["y"], b["x"], b["y"]
    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    t = 0.0 if not span else max(0.0, min(1.0, ((p["x"] - ax) * dx + (p["y"] - ay) * dy) / span))
    return math.hypot(p["x"] - (ax + t * dx), p["y"] - (ay + t * dy))


def label_centre(lb: dict) -> dict:
    return {"x": lb["x"] + lb["w"] / 2, "y": lb["y"] + lb["h"] / 2}


def clearance(lb: dict, a: dict, b: dict) -> tuple[float, float]:
    """(centre distance, finite-segment-to-text-box gap), in pixels.

    A gap of zero means intersection. Projecting half the box onto a line's
    normal gives false intersections beyond an endpoint; clip the actual
    segment first, then measure corners and endpoints for disjoint geometry.
    This measures the centreline, excluding stroke thickness.
    """
    centre = label_centre(lb)
    dist = seg_dist(centre, a, b)
    left, top = lb["x"], lb["y"]
    right, bottom = left + lb["w"], top + lb["h"]
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    lo, hi = 0.0, 1.0
    for v, q in ((-dx, a["x"]-left), (dx, right-a["x"]),
                 (-dy, a["y"]-top), (dy, bottom-a["y"])):
        if abs(v) < 1e-9:
            if q < 0:
                break
        elif v < 0:
            lo = max(lo, q/v)
        else:
            hi = min(hi, q/v)
        if lo > hi:
            break
    else:
        return dist, 0.0
    def point_box(p):
        return math.hypot(max(left-p["x"], 0, p["x"]-right),
                          max(top-p["y"], 0, p["y"]-bottom))
    gaps = [point_box(a), point_box(b)]
    gaps.extend(seg_dist({"x": x, "y": y}, a, b)
                for x, y in ((left, top), (right, top), (right, bottom), (left, bottom)))
    return dist, min(gaps)


def find_labels(info: dict, needle: str) -> list[dict]:
    found = []
    for g in info.get("graphs") or []:
        for lb in g["labels"]:
            if needle in lb["text"]:
                found.append(lb)
    return found


def angle_between(a0: dict, a1: dict, b0: dict, b1: dict) -> float | None:
    """Angle in degrees at the shared vertex a0 == b0 (rays to a1 and b1)."""
    import math as m

    if px_len(a0, b0) > 1.5:
        return None
    u = (a1["ux"] - a0["ux"], a1["uy"] - a0["uy"])
    v = (b1["ux"] - b0["ux"], b1["uy"] - b0["uy"])
    lu, lv = m.hypot(*u), m.hypot(*v)
    if not lu or not lv:
        return None
    cos = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (lu * lv)))
    return round(m.degrees(m.acos(cos)), 2)


def inside_wedge(p: dict, vertex: dict, r1: dict, r2: dict) -> bool | None:
    """Is p in the wedge between the rays vertex->r1 and vertex->r2 (the small one)?"""
    import math as m

    def ang(q):
        return m.atan2(q["y"] - vertex["y"], q["x"] - vertex["x"])

    a1, a2, ap = ang(r1), ang(r2), ang(p)
    span = (a2 - a1 + m.pi) % (2 * m.pi) - m.pi  # signed, small side
    off = (ap - a1 + m.pi) % (2 * m.pi) - m.pi
    if abs(span) < 1e-9:
        return None
    return 0 <= off / span <= 1


def analyse_circle(info: dict, base: str) -> dict:
    """Is a circle of radius r drawn, is the radius label on its line, is there a leak?"""
    f = float(info.get("fontPx") or 16)
    flags: list[str] = []
    text = (info.get("text") or "").lower()
    leaks = [w for w in FORBID.get(base, []) if w.lower() in text]
    if leaks:
        flags.append("possible answer leak in visible text: " + ", ".join(leaks))
    graphs = info.get("graphs") or []
    if not graphs:
        flags.append("no ot-graph on the page")
        return {"flags": flags, "graphs": []}
    g = graphs[0]
    out: dict = {"unitX": g["unitX"], "unitY": g["unitY"], "flags": flags, "curves": []}
    segs = [s for s in g["shapes"] if s["tag"] == "ot-segment" and s["px"] and len(s["px"]) == 2]
    for s in segs:
        out.setdefault("segments", []).append(
            {"id": s["id"], "text": s["text"], "units": round(unit_len(s["px"][0], s["px"][1]), 3),
             "number": label_number(s["text"]),
             "len_px": round(px_len(s["px"][0], s["px"][1]), 1)})
    # Drawn curve extents, in graph units, from the shell's own scale.
    ux, uy = g["unitX"] or 0, g["unitY"] or 0
    origin = g.get("origin")
    for s in g["shapes"]:
        for d in s.get("drawn") or []:
            box = d.get("box")
            if s["tag"] != "ot-fn" or not box or not ux or not uy or not origin:
                continue
            above = (origin["y"] - box["y"]) / uy
            below = (box["y"] + box["h"] - origin["y"]) / uy
            out["curves"].append({"text": s["text"], "id": s["id"], "domain": s["domain"],
                                  "widthU": round(box["w"] / ux, 2),
                                  "heightU": round(box["h"] / uy, 2),
                                  "aboveU": round(above, 2), "belowU": round(below, 2)})
    # The radius the page gives: the number on the radius segment, or in the ask.
    given = 4.0
    radius_seg = None
    for s in out.get("segments", []):
        if s["number"]:
            given = s["number"]
            radius_seg = s
            break
    curves = out["curves"]
    if not curves:
        flags.append("no curve drawn for the circle")
    else:
        widest = max(c["widthU"] for c in curves)
        up = max(c["aboveU"] for c in curves)
        down = max(c["belowU"] for c in curves)
        out["measured"] = {"widest_curve_units": widest, "up_units": up,
                           "down_units": down, "given_r": given}
        if abs(widest - 2 * given) > 0.25 * given:
            flags.append(f"widest curve spans {widest:.2f} units, 2r would be {2 * given:.2f}")
        if up < 0.8 * given or down < 0.8 * given:
            flags.append(f"arc halves reach {up:.2f}/{down:.2f} units, r is {given:.2f}: "
                         "circle not closed")
        elif abs((up + down) - 2 * given) > 0.25 * given:
            flags.append(f"arc halves span {up + down:.2f} units vertically, 2r is {2 * given:.2f}")
    # Radius label: is it clear of the radius line it names?
    if radius_seg:
        seg = next(s for s in segs if s["id"] == radius_seg["id"] and s["text"] == radius_seg["text"])
        lb = min((l for l in g["labels"] if l["text"] == radius_seg["text"]),
                 key=lambda l: seg_dist(label_centre(l), seg["px"][0], seg["px"][1]),
                 default=None)
        if lb:
            dist, gap = clearance(lb, seg["px"][0], seg["px"][1])
            out["radius_label"] = {"text": lb["text"], "edge_px": round(dist, 1),
                                   "box_gap_px": round(gap, 1)}
            if gap <= 0:
                flags.append(f"label '{lb['text']}' intersects the radius centreline")
    # Every other label against every drawn segment, for the record.
    out["labels"] = []
    for lb in g["labels"]:
        row = {"text": lb["text"], "x": round(lb["x"], 1), "y": round(lb["y"], 1),
               "w": round(lb["w"], 1), "h": round(lb["h"], 1)}
        worst = None
        for s in segs:
            dist, gap = clearance(lb, s["px"][0], s["px"][1])
            if worst is None or gap < worst["box_gap_px"]:
                worst = {"segment": s["id"], "edge_px": round(dist, 1),
                         "box_gap_px": round(gap, 1)}
        if worst:
            row.update(worst)
        out["labels"].append(row)
    out["fontPx"] = f
    return out


def analyse_angle(info: dict, base: str) -> dict:
    """Does the drawn angle match 60°, and are the two texts where the ask put them?"""
    f = float(info.get("fontPx") or 16)
    flags: list[str] = []
    text = (info.get("text") or "").lower()
    leaks = [w for w in FORBID.get(base, []) if w.lower() in text]
    if leaks:
        flags.append("possible answer leak in visible text: " + ", ".join(leaks))
    graphs = info.get("graphs") or []
    if not graphs:
        flags.append("no ot-graph on the page")
        return {"flags": flags, "graphs": []}
    g = graphs[0]
    out: dict = {"fontPx": f, "flags": flags}
    segs = [s for s in g["shapes"] if s["tag"] == "ot-segment" and s["px"] and len(s["px"]) == 2]
    out["segments"] = [{"id": s["id"], "from": s["from"], "to": s["to"], "text": s["text"],
                        "px": [{"x": round(p["x"], 1), "y": round(p["y"], 1)} for p in s["px"]]}
                       for s in segs]
    # Angle at every shared vertex; the page's own 60° label is the claim to check.
    angles = []
    for i, a in enumerate(segs):
        for b in segs[i + 1:]:
            for a0, a1 in ((a["px"][0], a["px"][1]), (a["px"][1], a["px"][0])):
                for b0, b1 in ((b["px"][0], b["px"][1]), (b["px"][1], b["px"][0])):
                    deg = angle_between(a0, a1, b0, b1)
                    if deg is not None:
                        angles.append({"vertex_px": {"x": round(a0["x"], 1), "y": round(a0["y"], 1)},
                                       "deg": deg, "legs": [a["id"], b["id"]],
                                       "far": [{"x": a1["x"], "y": a1["y"]},
                                               {"x": b1["x"], "y": b1["y"]}]})
    out["angles"] = angles
    if not angles:
        flags.append("no two segments share a vertex: no angle is drawn")
    else:
        best = min(angles, key=lambda r: abs(r["deg"] - 60))
        out["angle_deg"] = best["deg"]
        if abs(best["deg"] - 60) > 1.0:
            flags.append(f"drawn angle is {best['deg']:.1f}°, the ask gives 60°")
        vertex, far = best["vertex_px"], best["far"]
        # The 60° label: how far from the vertex, inside the wedge, clear of both legs?
        lb = min(find_labels(info, "60"), key=lambda l: seg_dist(label_centre(l), vertex, vertex),
                 default=None)
        if not lb:
            flags.append("no label with 60 on the page")
        else:
            centre = label_centre(lb)
            inside = inside_wedge(centre, vertex, far[0], far[1])
            dist_v = math.hypot(centre["x"] - vertex["x"], centre["y"] - vertex["y"])
            clear = []
            for a, b in ((vertex, far[0]), (vertex, far[1])):
                d, gap = clearance(lb, a, b)
                clear.append({"edge_px": round(d, 1), "box_gap_px": round(gap, 1)})
            out["label_60"] = {"text": lb["text"], "from_vertex_px": round(dist_v, 1),
                               "from_vertex_em": round(dist_v / f, 1), "inside_wedge": inside,
                               "legs": clear}
            if inside is False:
                flags.append("the 60 label is outside the angle")
            if any(c["box_gap_px"] <= 0 for c in clear):
                flags.append("the 60 label intersects a leg centreline")
        # "Vinkelben": the ask wants it at the far end of the slanted leg.
        lb2 = min(find_labels(info, "Vinkelben"), key=lambda l: min(
            math.hypot(label_centre(l)["x"] - p["x"], label_centre(l)["y"] - p["y"])
            for p in far), default=None)
        if not lb2:
            flags.append("no Vinkelben label on the page")
        else:
            centre = label_centre(lb2)
            near = min(range(len(far)), key=lambda k: math.hypot(
                centre["x"] - far[k]["x"], centre["y"] - far[k]["y"]))
            d_end = math.hypot(centre["x"] - far[near]["x"], centre["y"] - far[near]["y"])
            d_leg, gap = clearance(lb2, vertex, far[near])
            out["label_ben"] = {"text": lb2["text"], "from_end_px": round(d_end, 1),
                               "from_end_em": round(d_end / f, 1),
                               "edge_px": round(d_leg, 1), "box_gap_px": round(gap, 1)}
            if gap <= 0:
                flags.append("the Vinkelben label intersects its leg centreline")
            if d_end > 3 * f:
                flags.append(f"the Vinkelben label sits {d_end / f:.1f} em from the leg end")
    # All labels against all legs, for the record.
    out["labels"] = []
    for lb in g["labels"]:
        row = {"text": lb["text"], "x": round(lb["x"], 1), "y": round(lb["y"], 1),
               "w": round(lb["w"], 1), "h": round(lb["h"], 1)}
        worst = None
        for s in segs:
            d, gap = clearance(lb, s["px"][0], s["px"][1])
            if worst is None or gap < worst["box_gap_px"]:
                worst = {"segment": s["id"], "edge_px": round(d, 1), "box_gap_px": round(gap, 1)}
        if worst:
            row.update(worst)
        out["labels"].append(row)
    out["texts"] = [s["tag"] for s in g["shapes"]]
    return out


def analyse_page(report: dict) -> dict:
    """Per size: font, lint, the drawing, the labels, and what pointing does."""
    base, steer = spec_for(report["name"])
    verdict: dict = {"case": report["name"], "base_ask": base, "steered": steer, "sizes": {}}
    for key, info in report["sizes"].items():
        part = analyse_circle(info, base) if base == "cirkel" else analyse_angle(info, base)
        point = {k: v for k, v in (info.get("point") or {}).items()}
        part.update({"issues": info.get("issues"),
                     "ids": info.get("ids"),
                     "point": point,
                     "visible_text": (info.get("text") or "").strip()[:1200]})
        if "patch_issues" in info:
            part["patch_issues"] = info["patch_issues"]
        verdict["sizes"][key] = part
    return verdict


# ---------------------------------------------------------------- the two jobs


def run_cases(out: pathlib.Path, case_ids: list[str]) -> list[dict]:
    """Real Screen jobs: the deployed writer, the real prompt and renderer."""
    from open_tutor.screen import Screen, strip_fences
    from screen.tools import prompt as screen_prompt

    baseline_system = baseline_prompt()
    rows = []
    for case_id in case_ids:
        folder = out / case_id
        folder.mkdir(parents=True, exist_ok=True)
        ask, base, steer = ask_for(case_id)
        candidate = candidate_for(case_id)
        holder: dict = {}

        async def main() -> None:
            screen = Screen(LEARNER, folder, session_id=f"circletex-{case_id}",
                            get_pane_size=lambda: SIZES[0])
            screen.add_turn("child", CHILD)
            if not CASES[case_id].get("shipped"):
                screen._system = f"{baseline_system}\n\n{candidate}" if steer else baseline_system

            async def model(system, user, images, look_png):
                started = time.monotonic()
                text = await asyncio.to_thread(screen._default_model_call, system, user,
                                               images, look_png)
                holder.setdefault("calls", []).append(
                    {"look": bool(look_png), "seconds": round(time.monotonic() - started, 2),
                     "system_chars": len(system), "user_chars": len(user),
                     "answer_chars": len(text)})
                if not look_png:
                    holder.setdefault("raw", text)
                return text

            screen._model_call = model
            delivered, failures = [], []
            screen.on_page, screen.on_failure = delivered.append, failures.append
            wall = time.monotonic()
            screen.ask(ask)
            await screen.wait_idle()
            wall = time.monotonic() - wall
            try:
                meta = {"case": case_id, "base_ask": base, "steered": steer, "ask": ask,
                        "pane": list(SIZES[0]), "wall_s": round(wall, 2),
                        "spec": screen.model_spec(), "calls": holder.get("calls", []),
                        "failures": failures,
                        "system_chars": len(screen.system_prompt()),
                        "system_sha256": hashlib.sha256(screen.system_prompt().encode()).hexdigest(),
                        "reference_sha256": hashlib.sha256((ROOT / "REFERENCE.md").read_bytes()).hexdigest(),
                        "exact_shipped_prompt": bool(CASES[case_id].get("shipped")),
                        "candidate_chars": len(candidate) if steer else 0}
                raw = strip_fences(holder.get("raw", ""))
                (folder / "ask.txt").write_text(ask, encoding="utf-8")
                if steer:
                    (folder / "reference_candidate.txt").write_text(candidate, encoding="utf-8")
                (folder / "raw.html").write_text(raw, encoding="utf-8")
                if delivered:
                    result = delivered[0]
                    (folder / "delivered.html").write_text(result.body, encoding="utf-8")
                    meta.update(model_s=result.model_s, look_s=result.look_s,
                                retry_s=result.retry_s, render_s=result.render_s,
                                total_s=result.total_s, issues=result.issues,
                                residual_lint=result.residual_issues,
                                repaired=result.body != raw)
                (folder / "meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
                rows.append(meta)
                print(case_id, json.dumps({k: v for k, v in meta.items()
                                           if k in ("wall_s", "model_s", "look_s", "retry_s",
                                                    "total_s", "issues", "failures", "repaired")},
                                          ensure_ascii=False), flush=True)
            finally:
                await screen.aclose()

        asyncio.run(main())
        _measure_folder(folder, case_id)
    return rows


def _measure_folder(folder: pathlib.Path, name: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            raw = folder / "raw.html"
            if raw.is_file() and raw.read_text().strip():
                report = measure_body(raw.read_text(), name, folder, browser)
                (folder / "measure.json").write_text(
                    json.dumps(analyse_page(report), ensure_ascii=False, indent=1), encoding="utf-8")
            delivered = folder / "delivered.html"
            if delivered.is_file() and delivered.read_text().strip():
                body = delivered.read_text()
                raw_body = raw.read_text() if raw.is_file() else ""
                if body.strip() != raw_body.strip():
                    report = measure_body(body, f"{name}-delivered", folder, browser)
                    (folder / "measure-delivered.json").write_text(
                        json.dumps(analyse_page(report), ensure_ascii=False, indent=1),
                        encoding="utf-8")
        finally:
            browser.close()


def run_patch(out: pathlib.Path, case_id: str) -> dict:
    """One tutor follow-up on an already delivered page: a real patch, applied."""
    from open_tutor.screen import PageResult, Screen
    from screen.tools import prompt as screen_prompt

    base, steer = spec_for(case_id)
    folder = out / case_id
    source = folder / "delivered.html"
    if not source.is_file():
        source = folder / "raw.html"
    if not source.is_file():
        raise SystemExit(f"{case_id}: no page to patch; run that case first")
    body = source.read_text()
    ask = PATCH[case_id]
    result: dict = {}

    async def main() -> None:
        screen = Screen(LEARNER, folder, session_id=f"circletex-patch-{case_id}",
                        get_pane_size=lambda: SIZES[0])
        if steer:
            screen._system = f"{baseline_prompt()}\n\n{candidate_for(case_id)}"
        screen.pages["sida-1"] = PageResult(job_id="base", page_id="sida-1", title="bas",
                                            body=body, png=b"")
        screen.mark_visible("sida-1")
        screen.add_turn("child", CHILD)
        patches, pages, failures = [], [], []
        calls: list = []

        async def model(system, user, images, look_png):
            started = time.monotonic()
            text = await asyncio.to_thread(screen._default_model_call, system, user,
                                           images, look_png)
            calls.append({"look": bool(look_png), "seconds": round(time.monotonic() - started, 2),
                          "system_chars": len(system), "answer_chars": len(text)})
            return text

        screen._model_call = model
        screen.on_patch, screen.on_page = patches.append, pages.append
        screen.on_failure = failures.append
        wall = time.monotonic()
        screen.ask(ask)
        await screen.wait_idle()
        wall = time.monotonic() - wall
        try:
            meta = {"case": case_id, "ask": ask, "pane": list(SIZES[0]),
                    "wall_s": round(wall, 2), "spec": screen.model_spec(), "calls": calls,
                    "failures": failures, "new_pages": len(pages),
                    "visible_ids": re.findall(r'id="([^"]+)"', body)}
            patch = patches[0].patch if patches else ""
            (folder / "patch-ask.txt").write_text(ask, encoding="utf-8")
            (folder / "patch.html").write_text(patch, encoding="utf-8")
            if patches:
                meta.update(model_s=patches[0].model_s, render_s=patches[0].render_s,
                            total_s=patches[0].total_s, issues=patches[0].issues,
                            targets=re.findall(r'<ot-patch[^>]*target="([^"]+)"', patch))
                meta["missing_targets"] = [t for t in meta["targets"]
                                           if t not in meta["visible_ids"]]
            (folder / "patch-meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            result["patch"] = patch
            print(case_id, json.dumps(meta, ensure_ascii=False), flush=True)
        finally:
            await screen.aclose()

    asyncio.run(main())
    patch = result.get("patch", "")
    if patch:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                report = measure_body(body, f"{case_id}-delivered", folder, browser)
                (folder / "measure.json").write_text(
                    json.dumps(analyse_page(report), ensure_ascii=False, indent=1), encoding="utf-8")
                after = measure_body(body, f"{case_id}-patched", folder, browser, patch=patch)
                verdict = analyse_page(after)
                # Pointing proof: the patched page is in the frame the analysis just ran in,
                # so a second pass records what ot.point does on the ids that changed.
                (folder / "measure-after.json").write_text(
                    json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")
            finally:
                browser.close()
    return report_of(folder, "patch-meta.json")


def report_of(folder: pathlib.Path, name: str) -> dict:
    path = folder / name
    return json.loads(path.read_text()) if path.is_file() else {}


def measure_dir(directory: pathlib.Path) -> None:
    """Re-render and re-measure saved raw bodies; no provider call."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for folder in sorted(p for p in directory.iterdir() if p.is_dir()):
                name = folder.name
                bodies = [("raw.html", name), ("delivered.html", f"{name}-delivered")]
                for file, label in bodies:
                    path = folder / file
                    if not path.is_file() or not path.read_text().strip():
                        continue
                    if file == "delivered.html":
                        raw = folder / "raw.html"
                        if raw.is_file() and raw.read_text().strip() == path.read_text().strip():
                            continue
                        out_name = "measure-delivered.json"
                    else:
                        out_name = "measure.json"
                    report = measure_body(path.read_text(), label, folder, browser)
                    verdict = analyse_page(report)
                    (folder / out_name).write_text(
                        json.dumps(verdict, ensure_ascii=False, indent=1), encoding="utf-8")
                    print(label, json.dumps(
                        {k: {"flags": v["flags"], "issues": v["issues"]}
                         for k, v in verdict["sizes"].items()}, ensure_ascii=False), flush=True)
                patch = folder / "patch.html"
                base = folder / "delivered.html"
                if patch.is_file() and patch.read_text().strip() and base.is_file():
                    after = measure_body(base.read_text(), f"{name}-patched", folder, browser,
                                         patch=patch.read_text())
                    (folder / "measure-after.json").write_text(
                        json.dumps(analyse_page(after), ensure_ascii=False, indent=1),
                        encoding="utf-8")
                    print(f"{name}-patched", "measured", flush=True)
        finally:
            browser.close()


def selftest(out: pathlib.Path) -> None:
    """What the shell really does with the candidate syntax; no provider call."""
    body = """<h1>Cirkel och vinkel</h1>
<ot-graph id="cirkel" x="-5 5" y="-5 5" axes="off">
  <ot-point id="medelpunkt" x="0" y="0">M</ot-point>
  <ot-segment id="radie" from="0 0" to="4 0">4 cm</ot-segment>
  <ot-fn domain="-4 4">sqrt(16 - x^2)</ot-fn>
  <ot-fn domain="-4 4">-sqrt(16 - x^2)</ot-fn>
  <ot-text id="kant" x="3.2" y="2.4">kant</ot-text>
</ot-graph>
<ot-graph id="vinkel" x="-1 6" y="-1 5" axes="off">
  <ot-segment id="ben1" from="0 0" to="5 0"></ot-segment>
  <ot-segment id="ben2" from="0 0" to="2,5 4,3"></ot-segment>
  <ot-point id="spets" x="0" y="0">S</ot-point>
  <ot-text id="matt" x="1,4" y="0,9">60°</ot-text>
  <ot-text id="ben-sned" x="2,5" y="4,3">Vinkelben</ot-text>
</ot-graph>
<p class="tip">Prov: givna mått syns, svaret inte.</p>
"""
    out.mkdir(parents=True, exist_ok=True)
    (out / "recipe.html").write_text(body, encoding="utf-8")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            report = measure_body(body, "recipe", out, browser)
        finally:
            browser.close()
    verdict = {"case": "recipe", "base_ask": "cirkel", "steered": True, "sizes": {}}
    for key, info in report["sizes"].items():
        part = analyse_circle(info, "cirkel")
        # The angle graph is a second graph; the circle analysis only reads the first.
        part["second_graph_angle"] = analyse_angle(
            {"fontPx": info.get("fontPx"), "text": info.get("text"),
             "graphs": (info.get("graphs") or [])[1:]}, "vinkel")
        part.update({"issues": info.get("issues"), "ids": info.get("ids"),
                     "point": info.get("point"),
                     "visible_text": (info.get("text") or "").strip()[:800]})
        verdict["sizes"][key] = part
    (out / "measure.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    print(json.dumps({k: {"flags": v["flags"], "point": v["point"]}
                      for k, v in verdict["sizes"].items()}, ensure_ascii=False, indent=1))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="real Screen jobs, then measure their raw bodies")
    r.add_argument("--out", type=pathlib.Path, required=True)
    r.add_argument("--cases", default="cirkel-bas,cirkel-ref,vinkel-bas,vinkel-ref,vinkel-ref2")
    m = sub.add_parser("measure", help="re-render and measure saved bodies (no model call)")
    m.add_argument("--dir", type=pathlib.Path, required=True)
    p = sub.add_parser("patch", help="one real tutor follow-up on a delivered page")
    p.add_argument("--dir", type=pathlib.Path, required=True)
    p.add_argument("--case", default="vinkel-ref")
    s = sub.add_parser("selftest", help="render the candidate syntax by hand (no model call)")
    s.add_argument("--out", type=pathlib.Path, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "measure":
        measure_dir(args.dir)
        return 0
    if args.cmd == "selftest":
        selftest(args.out)
        return 0
    if args.cmd == "patch":
        run_patch(args.dir, args.case)
        return 0
    ids = [c.strip() for c in args.cases.split(",") if c.strip()]
    unknown = [c for c in ids if c not in CASES]
    if unknown:
        raise SystemExit(f"unknown cases: {', '.join(unknown)}")
    run_cases(args.out, ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
