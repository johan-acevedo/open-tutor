"""Graph side/segment label placement: render, measure and lint, without model calls.

Renders the unedited Hydrogen regression bodies (screen/review/2026-11-13-graph-labels/inputs/)
plus small synthetic crowding cases at 370x610 and 1000x700, measures every side label
against straight outlines, neighboring side labels, the outlined shape and the pane, and requires
every remaining defect to be named by a `crowded: label ...` lint issue.

  uv run --project server python screen/tools/check_graph_labels.py --out /tmp/graph-labels
  uv run --project server python screen/tools/check_graph_labels.py --out /tmp/graph-labels --shell DIR
  uv run --project server python screen/tools/check_graph_labels.py --out /tmp/graph-labels --prior-ref 848f8c1

--prior-ref exports that git ref's shell and runs the same measurement there: the check
must FAIL on the prior shell (unreported defects) and PASS here (defects fixed, the rest
reported with actionable lint). Reported-but-unresolved crowding prints as CROWD lines
and still passes: the shell must flag what it cannot place, not pretend it is clean.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

import screenkit

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "review/2026-11-13-graph-labels/inputs"
SIZES = ((370, 610), (1000, 700))

SYNTHETIC = {
    # Same L as Hydrogen wrote, vertices reversed: winding must still point outward.
    "l-cw": ('<h1>L-form, omvänd ordning</h1><ot-graph id="figurer" axes="off">'
             '<ot-polygon id="l-form" points="6 2, 7 2, 7 1, 9 1, 9 0, 6 0"'
             ' sides="2 cm | 1 cm | 1 cm | 2 cm | 3 cm | 1 cm" color="violet" fill="none">'
             '</ot-polygon></ot-graph>'),
    # Narrow notch, long labels: there is no clean placement, the shell must say so.
    "notch-long": ('<h1>Smalt hack</h1><ot-graph id="figurer" axes="off">'
                   '<ot-polygon id="l-form" points="6 0, 9 0, 9 1, 7 1, 7 2, 6 2"'
                   ' sides="3 centimeter | ett cm | två centimeter | en cm | en cm | två cm"'
                   ' color="violet" fill="none"></ot-polygon></ot-graph>'),
    # Short edges with wordy labels next to each other.
    "short-edges": ('<h1>Korta sidor</h1><ot-graph id="graf" axes="off">'
                    '<ot-polygon id="tri" points="0 0, 1 0, 0 1"'
                    ' sides="en centimeter | en centimeter | diagonalen" color="cyan" fill="none">'
                    '</ot-polygon></ot-graph>'),
}

MEASURE_JS = """() => {
  const F = 1.9 * (ot.fontPx || 16);
  const out = { fontPx: ot.fontPx, issues: ot.issues, graphs: [] };
  document.querySelectorAll('ot-graph').forEach(el => {
    const lay = el.querySelector(':scope > .ot-vis');
    const W = lay ? lay.clientWidth : 0, H = lay ? lay.clientHeight : 0;
    const px = el._px || ((x, y) => ({x: 0, y: 0}));
    const g = { id: el.id || '', w: W, h: H, labels: [], edges: [] };
    const nums = s => (s || '').trim().split(/[\\s,]+/).filter(Boolean).map(Number);
    el.querySelectorAll(':scope > ot-polygon, :scope > ot-segment').forEach(ch => {
      const tag = ch.tagName.toLowerCase();
      const pts = tag === 'ot-polygon' ? nums(ch.getAttribute('points'))
                                       : nums((ch.getAttribute('from') || '') + ' ' + (ch.getAttribute('to') || ''));
      const P = [];
      for (let k = 0; k + 1 < pts.length; k += 2) P.push(px(pts[k], pts[k + 1]));
      if (tag === 'ot-segment') {
        if (P.length === 2) g.edges.push({ for: ch.id || '', kind: 'seg', edge: 0,
          ax: P[0].x, ay: P[0].y, bx: P[1].x, by: P[1].y, sides: !!ch.textContent.trim(), poly: null });
      } else if (P.length >= 3) {
        const sides = (ch.getAttribute('sides') || '').split('|').map(s => s.trim());
        for (let k = 0; k < P.length; k++) {
          const a = P[k], b = P[(k + 1) % P.length];
          g.edges.push({ for: ch.id || '', kind: 'side', edge: k,
            ax: a.x, ay: a.y, bx: b.x, by: b.y,
            sides: !!(sides[k] || ''), poly: P.map(p => ({x: p.x, y: p.y})) });
        }
      }
    });
    const exact = [...el.querySelectorAll('.ot-side-lbl')];
    if (exact.length) {
      const labeledEdges = g.edges.filter(e => e.sides);
      exact.forEach((nd, index) => {
        const edge = labeledEdges[index];
        if (!edge || edge.kind !== nd.dataset.kind || edge.edge !== +nd.dataset.edge || edge.for !== (nd.dataset.for || ''))
          throw new Error('label/source edge association changed');
        g.labels.push({ text: (nd.textContent || '').trim(),
          cx: parseFloat(nd.style.left) || 0, cy: parseFloat(nd.style.top) || 0,
          w: nd.offsetWidth || 0, h: nd.offsetHeight || 0,
          for: nd.dataset.for || '', kind: nd.dataset.kind || 'side', edge: +(nd.dataset.edge || 0),
          ax: edge.ax, ay: edge.ay, bx: edge.bx, by: edge.by,
          assoc: 'exact' });
      });
    } else {
      // Prior shell: no metadata. Nearest edge midpoint, like the research probe.
      el.querySelectorAll('.ot-graph-labels .ot-lbl').forEach(nd => {
        const cx = parseFloat(nd.style.left) || 0, cy = parseFloat(nd.style.top) || 0;
        let best = -1, bd = 1e9;
        g.edges.forEach((e, i) => {
          if (!e.sides) return;
          const d = Math.hypot(cx - (e.ax + e.bx) / 2, cy - (e.ay + e.by) / 2);
          if (d < bd) { bd = d; best = i; }
        });
        if (best < 0 || bd > F) return;
        const e = g.edges[best];
        g.labels.push({ text: (nd.textContent || '').trim(), cx, cy,
          w: nd.offsetWidth || 0, h: nd.offsetHeight || 0,
          for: e.for, kind: e.kind, edge: e.edge,
          ax: e.ax, ay: e.ay, bx: e.bx, by: e.by, assoc: 'guess' });
      });
    }
    out.graphs.push(g);
  });
  return out;
}"""


def seg_dist(cx, cy, e):
    dx, dy = e["bx"] - e["ax"], e["by"] - e["ay"]
    span = dx * dx + dy * dy or 1.0
    t = max(0.0, min(1.0, ((cx - e["ax"]) * dx + (cy - e["ay"]) * dy) / span))
    return math.hypot(cx - (e["ax"] + t * dx), cy - (e["ay"] + t * dy))


def in_poly(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi, xj, yj = poly[i]["x"], poly[i]["y"], poly[j]["x"], poly[j]["y"]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def stroke_hits_box(edge, box, pad):
    """Clip a finite segment against the text rectangle (Liang–Barsky)."""
    left, top, right, bottom = box
    left -= pad; top -= pad; right += pad; bottom += pad
    x, y = edge["ax"], edge["ay"]
    dx, dy = edge["bx"] - x, edge["by"] - y
    lo, hi = 0.0, 1.0
    for p, q in ((-dx, x-left), (dx, right-x), (-dy, y-top), (dy, bottom-y)):
        if abs(p) < 1e-9:
            if q < 0:
                return False
        elif p < 0:
            lo = max(lo, q/p)
        else:
            hi = min(hi, q/p)
        if lo > hi:
            return False
    return True


def analyse(info):
    """Independent geometry recomputation: returns (defects, reported)."""
    f = float(info.get("fontPx") or 16)
    defects, reported = [], []
    for issue in info.get("issues") or []:
        if str(issue.get("kind")) == "crowded" and str(issue.get("msg", "")).startswith(("label ", "labels ")):
            reported.append(str(issue.get("msg")))
    for g in info.get("graphs", []):
        W, H = g["w"], g["h"]
        boxes = []
        for lb in g.get("labels", []):
            if not lb["w"] or not lb["h"]:
                continue
            box = (lb["cx"] - lb["w"] / 2, lb["cy"] - lb["h"] / 2,
                   lb["cx"] + lb["w"] / 2, lb["cy"] + lb["h"] / 2)
            boxes.append((lb, box))
            ex, ey = lb["bx"] - lb["ax"], lb["by"] - lb["ay"]
            nl = math.hypot(ex, ey) or 1.0
            nx, ny = -ey / nl, ex / nl
            reach = (abs(nx) * lb["w"] + abs(ny) * lb["h"]) / 2
            dist = seg_dist(lb["cx"], lb["cy"], lb)
            if reach - dist > 1.0:
                defects.append(f"{g['id'] or 'graph'}: label '{lb['text']}' crosses its own line")
            if any(stroke_hits_box(edge, box, max(1, f * 0.083)) for edge in g["edges"]):
                defects.append(f"{g['id'] or 'graph'}: label '{lb['text']}' crosses an outline")
            if lb.get("kind") == "side" and g.get("edges"):
                poly = next((e["poly"] for e in g["edges"]
                             if e["for"] == lb["for"] and e["poly"]), None)
                if poly and in_poly(lb["cx"], lb["cy"], poly):
                    defects.append(f"{g['id'] or 'graph'}: label '{lb['text']}' is inside the outlined shape")
            if box[0] < -0.5 or box[1] < -0.5 or box[2] > W + 0.5 or box[3] > H + 0.5:
                defects.append(f"{g['id'] or 'graph'}: label '{lb['text']}' does not fit inside the pane")
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                (l1, b1), (l2, b2) = boxes[i], boxes[j]
                ox = min(b1[2], b2[2]) - max(b1[0], b2[0]) + 1
                oy = min(b1[3], b2[3]) - max(b1[1], b2[1]) + 1
                if ox > 0 and oy > 0:
                    defects.append(f"{g['id'] or 'graph'}: labels '{l1['text']}' and '{l2['text']}' overlap")
    uncovered = [d for d in defects if not any(
        d.split("label '", 1)[-1].split("'")[0] in r or
        (d.split("labels '", 1)[-1].split("'")[0] in r if "labels '" in d else False)
        for r in reported)]
    return defects, reported, uncovered


def run_shell(shell, out, tag, prior_fail_expected):
    bodies = {p.stem: p.read_text() for p in sorted(INPUTS.glob("*.html"))}
    bodies.update(SYNTHETIC)
    failures, notes, crowding = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for name, body in bodies.items():
                doc = screenkit.compose(body, shell)
                for (w, h) in SIZES:
                    page = browser.new_page(viewport={"width": w, "height": h})
                    try:
                        page.set_content(screenkit.host_page(doc))
                        frame = screenkit._frame(page)
                        frame.wait_for_function("document.documentElement.dataset.otReady==='1'", timeout=30000)
                        info = frame.evaluate(MEASURE_JS)
                        pointable = frame.evaluate(
                            "() => [...document.querySelectorAll('ot-graph [id]')].slice(0,3).map(e => e.id)")
                        for pid in pointable:
                            if pid and not frame.evaluate(f"() => ot.point('{pid}')"):
                                failures.append(f"{tag} {name} {w}x{h}: ot.point('{pid}') failed")
                        frame.evaluate('() => ot.point(null)')
                        info["issues"] = frame.evaluate("() => ot.issues")
                        if any(i.get('kind') in {'draw', 'load', 'boot'} for i in info['issues']):
                            failures.append(f"{tag} {name} {w}x{h}: drawing failed: {info['issues']}")
                        defects, reported, uncovered = analyse(info)
                        if uncovered:
                            failures.append(f"{tag} {name} {w}x{h}: UNREPORTED: {'; '.join(uncovered)}")
                        for r in reported:
                            crowding.append(f"CROWD {tag} {name} {w}x{h}: {r}")
                        for d in defects:
                            if d not in uncovered:
                                notes.append(f"fixed-or-flagged {tag} {name} {w}x{h}: {d}")
                    finally:
                        if tag == "new":
                            page.screenshot(path=str(out / f"{name}-{w}x{h}.png"))
                        page.close()
        finally:
            browser.close()
    return failures, notes, crowding


def check_warning_lifecycle(shell):
    """Warnings must update over RPC, clear after repair, and ignore hidden work."""
    long = "Original long label " * 20
    body = ('<h1>Etikett</h1><ot-graph id="g" x="-1 1" y="-1 2" axes="off">'
            f'<ot-segment id="s" from="0 0" to="0 1">{long}</ot-segment></ot-graph>')
    fixed = '<ot-patch target="s"><ot-segment from="0 0" to="0 1">1</ot-segment></ot-patch>'
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 370, "height": 610})
            page.set_content(screenkit.host_page(screenkit.compose(body, shell)))
            frame = screenkit._frame(page)
            frame.wait_for_function("document.documentElement.dataset.otReady==='1'")
            assert frame.evaluate('() => ot.issues.some(i => i.kind === "crowded")'), "missing initial crowding"
            changed = frame.evaluate('(p) => ot.patch(p)',
                '<ot-patch target="s"><ot-segment from="0 0" to="0 1">'
                + "Changed long label " * 20 + '</ot-segment></ot-patch>')
            assert any('Changed' in i.get('msg', '') for i in changed), "new warning lost after replacing old issues"
            frame.evaluate('(p) => ot.patch(p)', fixed)
            assert not frame.evaluate('() => ot.issues'), "repaired warning remained"
            for wrapper, target in ((body.replace('id="g"', 'id="g" later'), 'g'),
                                    ('<ot-hidden id="secret">' + body + '</ot-hidden>', 'secret')):
                page.set_content(screenkit.host_page(screenkit.compose(wrapper, shell)))
                frame = screenkit._frame(page)
                frame.wait_for_function("document.documentElement.dataset.otReady==='1'")
                assert not frame.evaluate('() => ot.issues'), "hidden labels reported as visible crowding"
                assert frame.evaluate('(id) => ot.reveal(id)', target)
                assert frame.evaluate('() => ot.issues.some(i => i.kind === "crowded")'), "revealed warning missing"
            page.set_content(screenkit.host_page(screenkit.compose(body.replace('id="s"', 'id="s" later'), shell)))
            frame = screenkit._frame(page)
            frame.wait_for_function("document.documentElement.dataset.otReady==='1'")
            assert not frame.evaluate('() => document.querySelectorAll(".ot-side-lbl").length'), "hidden part label was drawn"
            assert not frame.evaluate('() => ot.issues'), "hidden part produced crowding"
            assert frame.evaluate('() => ot.reveal("s")')
            assert frame.evaluate('() => document.querySelectorAll(".ot-side-lbl").length === 1'), "revealed part did not redraw"
            assert frame.evaluate('() => ot.issues.some(i => i.kind === "crowded")'), "revealed part warning missing"
        finally:
            browser.close()

    # Real server preview must replace its initial label warnings with final lint.
    import asyncio
    import sys
    import tempfile
    sys.path.insert(0, str(ROOT.parent / 'server'))
    from open_tutor.screen import Screen

    async def preview():
        with tempfile.TemporaryDirectory() as directory:
            screen = Screen({}, directory)
            try:
                _, issues = await screen._default_render_page(body, fixed, 370, 610)
                assert not issues, f"server returned repaired label warnings: {issues}"
            finally:
                await screen.aclose()

    asyncio.run(preview())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "review/2026-11-13-graph-labels/shots"))
    ap.add_argument("--shell", default=None)
    ap.add_argument("--prior-ref", default=None)
    ap.add_argument("--skip-prior", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    shell = Path(args.shell) if args.shell else None
    failures, notes, crowding = run_shell(shell, out, "new", False)
    check_warning_lifecycle(shell)
    result = {"shell": str(shell or "worktree"), "failures": failures,
              "crowding_reported": crowding, "notes": notes}
    if args.prior_ref and not args.skip_prior:
        tmp = out / "_prior_shell"
        (tmp / "data").mkdir(parents=True, exist_ok=True)
        repo = Path(__file__).resolve().parents[2]
        for f in ("frame.html", "shell.css", "shell.js"):
            blob = subprocess.run(["git", "-C", str(repo), "show", f"{args.prior_ref}:screen/shell/{f}"],
                                  capture_output=True, check=True).stdout
            (tmp / f).write_bytes(blob)
        (tmp / "data" / "lan-sverige.json").write_bytes(
            (screenkit.SHELL / "data" / "lan-sverige.json").read_bytes())
        prior_failures, _, _ = run_shell(tmp, out, "prior", True)
        result["prior_shell_failures"] = prior_failures
        if not prior_failures:
            failures.append("prior shell passes too: the check does not pin the new placement/lint")
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print("\n".join(crowding) if crowding else "(no crowding reported)")
    for n in notes:
        print(n)
    if failures:
        print("FAIL:")
        for fl in failures:
            print("  " + fl)
        raise SystemExit(1)
    print("OK: no unreported label defects.")


if __name__ == "__main__":
    raise SystemExit(main())
