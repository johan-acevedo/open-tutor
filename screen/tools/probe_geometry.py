"""Probe geometry pages: what the page writer draws, rendered and measured.

Two jobs, kept apart on purpose:

  run      Real Screen jobs (the deployed writer, the real prompt and renderer).
           Saves the model's unedited first answer (``raw.html``), the delivered
           page (``delivered.html``, after any look/lint repair), its meta and
           timings, then measures ``raw.html`` at 370x610 and 1000x700.
  measure  Re-render saved bodies and measure them, without provider calls or
           keys. Chromium still fetches the usual public shell CDN assets.

A case is a small fictional lesson ask. Baseline cases use only what
``screen/REFERENCE.md`` documents. Steered cases append candidate reference
lines to the same ask, to test whether syntax alone closes a gap; their output
is reported apart from the baseline and never edited by hand. None of the
steered cases was run in the 2026-11-13 batch: the writer produced the circle
recipe itself after one lint line, so there was nothing left to steer.

  # real jobs (needs the provider key; never in CI)
  OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env env \
    SCREEN_MODEL=gemini-4-hydrogen SCREEN_API=chat SCREEN_REASONING=low SCREEN_THINKING= \
    uv run --project server python screen/tools/probe_geometry.py run \
      --out /tmp/geometry --cases cirkel,vinkel,ratblock,cylinder

  # measure saved bodies again (no key)
  uv run --project server python screen/tools/probe_geometry.py measure --dir /tmp/geometry

Measurements are honest but shallow: they compare a drawn edge in graph units
with the number in its label, and the pixel position of each label against the
shape it belongs to. They do not judge whether the picture teaches well, and
they cannot tell a deliberate perspective sketch from a plane figure drawn out
of scale - a flat figure with mismatched sides is reported, a 3D sketch of a
solid is not treated as one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT.parent / "server"))

SIZES = ((370, 610), (1000, 700))

# Baseline asks: only documented reference syntax, phrased as a tutor would say it.
CASES: dict[str, dict] = {
    "cirkel": {
        "ask": ("Rita en cirkel med radien 4 cm. Visa radien som ett streck från medelpunkten "
                "med etiketten 4 cm, och eleven ska kunna peka på radien. Arean får inte synas."),
        "forbid": ["area", "50,2", "50.2", "12,5", "cm²", "cm2"],
        "pointable": ["radie", "r"],
    },
    "vinkel": {
        "ask": ("Visa en vinkel som är 60 grader. Rita vinkelbenen från spetsen och markera "
                "vinkeln vid spetsen med 60°, så att eleven ser vilken vinkel det är. Eleven ska "
                "kunna peka på vinkelspetsen. Räkna inte ut något svar."),
        "forbid": ["cos", "sin", "tan", "area"],
        "pointable": ["spets", "vinkel", "v"],
    },
    "ratblock": {
        "ask": ("Visa ett rätblock som är 4 cm långt, 3 cm brett och 2 cm högt. Måtten ska stå vid "
                "sina kanter och eleven ska kunna peka på höjden. Volymen får inte synas."),
        "forbid": ["volym", "24 cm", "24cm", "cm³", "cm3"],
        "pointable": ["hojd", "höjd", "h"],
    },
    "plan": {
        "ask": ("Rita en rektangel som är 4 cm bred och 3 cm hög, och en L-form med måtten "
                "3 cm, 2 cm och 1 cm. Måtten ska stå vid sidorna. En svarsruta för rektangelns "
                "omkrets. Rita inget svar."),
        "forbid": ["omkrets =", "= 14", "14 cm"],
        "pointable": ["rektangel", "sida", "langd", "höjd"],
    },
    "cylinder": {
        "ask": ("Visa en cylinder med radie 3 cm och höjd 5 cm. Markera radien och höjden med mått "
                "och eleven ska kunna peka på radien. Volymen får inte synas."),
        "forbid": ["volym", "141", "45", "cm³", "cm3", "π"],
        "pointable": ["radie", "r"],
    },
}

# The patch ask: a second tutor turn on a page the writer already delivered. It
# reuses that saved page as the visible one, so it is one model call, not a new page.
PATCH = {
    "ratblock-patch": {
        "base": "ratblock",
        "ask": ("Gör höjden tydlig: lägg en punkt på höjdkannten och skriv måttet 2 cm "
                "utanför figuren, så att etiketten inte ligger på linjen."),
    },
}

# Steered variants: the baseline ask plus candidate reference lines. Each is a
# possible REFERENCE.md paragraph written in the same voice as the real one.
STEERED: dict[str, dict] = {
    "cirkel-styrd": {
        "base": "cirkel",
        "steer": ("Om du ritar en cirkel: sätt medelpunkten som `<ot-point x=\"0\" y=\"0\">`, "
                  "radien som `<ot-segment from=\"0 0\" to=\"4 0\">4 cm</ot-segment>` och "
                  "cirkelbågen som två grafer, `<ot-fn domain=\"-4 4\">sqrt(16 - x^2)</ot-fn>` "
                  "och `<ot-fn domain=\"-4 4\">-sqrt(16 - x^2)</ot-fn>`."),
    },
    "vinkel-styrd": {
        "base": "vinkel",
        "steer": ("Om du ritar en vinkel: två `<ot-segment>` från spetsen, till exempel "
                  "`from=\"0 0\" to=\"4 0\"` och `from=\"0 0\" to=\"2 3.464\"`, och etiketten "
                  "`<ot-text x=\"1,4\" y=\"0,9\">60°</ot-text>` vid spetsen."),
    },
}


def ask_for(case_id: str) -> tuple[str, str | None]:
    """The ask to send and the steered text that was added, if any."""
    if case_id in STEERED:
        case = STEERED[case_id]
        base = CASES[case["base"]]
        return f"{base['ask']}\n\n{case['steer']}", case["steer"]
    return CASES[case_id]["ask"], None


def spec_for(name: str) -> dict:
    """The ask's expectations, for a case folder, a steered case or a patched page."""
    for case_id, case in {**CASES, **{k: {"base": v["base"]} for k, v in STEERED.items()},
                          **{k: {"base": v["base"]} for k, v in PATCH.items()}}.items():
        if name == case_id or name.startswith(case_id + "-"):
            return CASES.get(case.get("base", case_id), {})
    return {}


# --------------------------------------------------------------------- pages

MEASURE_JS = r"""
() => {
  const num = v => parseFloat(String(v || '').replace(',', '.'));
  const pairs = s => String(s || '').split(',').map(p => p.trim()).filter(Boolean)
      .map(p => { const q = p.split(/\s+/); return [num(q[0]), num(q[1])]; });
  const graphs = [...document.querySelectorAll('ot-graph')].map(g => {
    const gr = g.getBoundingClientRect();
    const shapes = [...g.children].filter(c => c.tagName.startsWith('OT-')).map(c => {
      const isSeg = c.tagName === 'OT-SEGMENT';
      const xy = isSeg ? pairs((c.getAttribute('from') || '') + ',' + (c.getAttribute('to') || ''))
                       : c.tagName === 'OT-POLYGON' ? pairs(c.getAttribute('points'))
                       : c.tagName === 'OT-POINT' ? pairs((c.getAttribute('x') || '') + ' ' + (c.getAttribute('y') || ''))
                       : [];
      const px = xy.map(([x, y]) => {
        if (isNaN(x) || isNaN(y) || !g._px) return null;
        const p = g._px(x, y);
        return {x: p.x, y: p.y, ux: x, uy: y};
      });
      return {tag: c.tagName.toLowerCase(), id: c.id || null,
              points: c.getAttribute('points'), sides: c.getAttribute('sides'),
              vertices: c.getAttribute('vertices'), from: c.getAttribute('from'),
              to: c.getAttribute('to'), x: c.getAttribute('x'), y: c.getAttribute('y'),
              text: (c.textContent || '').trim(), px};
    });
    const labels = [...g.querySelectorAll('.ot-lbl')].map(l => {
      const r = l.getBoundingClientRect();
      return {text: (l.textContent || '').trim(), x: r.left - gr.left, y: r.top - gr.top,
              w: r.width, h: r.height};
    });
    return {id: g.id || null, w: g.clientWidth, h: g.clientHeight, shapes, labels};
  });
  // Snapshot lint before the pointing sweep: pointing at an id the page does not
  // carry would otherwise be reported as a page issue.
  const issues = window.ot.issues.slice();
  // Only ids the writer chose; JSXGraph's own internal ids are not the page's.
  const ids = [...document.querySelectorAll('[id]')].map(e => e.id)
      .filter(id => !id.startsWith('jxg-'));
  const pointable = {};
  ids.forEach(id => { try { pointable[id] = !!window.ot.point(id); } catch (e) { pointable[id] = false; } });
  try { window.ot.point(null); } catch (e) {}
  return {fontPx: window.ot.fontPx, issues, graphs, ids, pointable,
          text: document.body.innerText || '', hiddenText: document.body.textContent || ''};
}
"""


def measure_body(body: str, name: str, out: pathlib.Path, browser,
                 patch: str | None = None) -> dict:
    """Render one body at both sizes, screenshot it and collect its geometry.
    With `patch`, the page is measured after the change, like the child's screen."""
    import screenkit

    report: dict = {"name": name, "sizes": {}}
    doc = screenkit.compose(body)
    for (w, h) in SIZES:
        key = f"{w}x{h}"
        page = browser.new_page(viewport={"width": w, "height": h})
        try:
            page.set_content(screenkit.host_page(doc))
            frame = page.frames[1]
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
    """The first number in a side label, e.g. '4 cm', '$4$ cm', '4,5'."""
    found = NUM.search(text or "")
    if not found:
        return None
    return float(found.group(1).replace(",", "."))


def unit_len(a: dict, b: dict) -> float:
    return math.hypot(b["ux"] - a["ux"], b["uy"] - a["uy"])


def seg_dist(p: dict, a: dict, b: dict) -> tuple[float, float]:
    """Distance from point p to segment ab, plus the signed side (-1/0/1)."""
    ax, ay, bx, by = a["x"], a["y"], b["x"], b["y"]
    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    t = 0.0 if not span else max(0.0, min(1.0, ((p["x"] - ax) * dx + (p["y"] - ay) * dy) / span))
    nx, ny = ax + t * dx, ay + t * dy
    cross = dx * (p["y"] - ay) - dy * (p["x"] - ax)
    return math.hypot(p["x"] - nx, p["y"] - ny), (0 if abs(cross) < 1e-9 else (1 if cross > 0 else -1))


def in_polygon(p: dict, poly: list[dict]) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi, xj, yj = poly[i]["x"], poly[i]["y"], poly[j]["x"], poly[j]["y"]
        if (yi > p["y"]) != (yj > p["y"]) and p["x"] < (xj - xi) * (p["y"] - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def analyse_graph(graph: dict, f: float) -> dict:
    """Length/label agreement and label placement for one ot-graph."""
    found: dict = {"flags": [], "lengths": [], "labels": [], "kinds": []}
    for shape in graph["shapes"]:
        found["kinds"].append(shape["tag"])
        px = [p for p in shape["px"] if p]
        if shape["tag"] == "ot-polygon" and len(px) >= 3:
            labels = [s.strip() for s in (shape["sides"] or "").split("|")]
            matched = []
            for k in range(len(px)):
                a, b = px[k], px[(k + 1) % len(px)]
                length = unit_len(a, b)
                text = labels[k] if k < len(labels) else ""
                number = label_number(text)
                row = {"side": k, "label": text, "units": round(length, 3),
                       "number": number}
                if number:
                    row["implied_scale"] = round(length / number, 3) if number else None
                    matched.append(row["implied_scale"])
                found["lengths"].append(row)
            if matched:
                med = sorted(matched)[len(matched) // 2]
                worst = max(abs(s / med - 1.0) for s in matched) if med else 0.0
                found["scale_median"] = med
                found["scale_spread"] = round(worst, 3)
                if worst > 0.05:
                    found["flags"].append(
                        f"label/length mismatch: labels imply {min(matched):.2f}-{max(matched):.2f} "
                        f"units per labelled cm (spread {worst * 100:.0f}%)")
            # labels that sit on, or inside, the outlined shape. Only a polygon that
            # declares `sides` gets labels of its own; the label check would otherwise
            # blame a face outline for the labels of the segments drawn on top of it.
            if (shape["sides"] or "").strip():
                found["kinds"].append("sides-labels")
                # Only this polygon's own labels: the ones its side labels put within
                # reach of an edge midpoint (the shell places them 1.05 em out). A graph
                # with two polygons otherwise blames one shape for the other's labels.
                edges = [(px[k], px[(k + 1) % len(px)]) for k in range(len(px))]
                mids = [{"x": (a["x"] + b["x"]) / 2, "y": (a["y"] + b["y"]) / 2}
                        for a, b in edges]
                for lb in graph["labels"]:
                    centre = {"x": lb["x"] + lb["w"] / 2, "y": lb["y"] + lb["h"] / 2}
                    k = min(range(len(mids)), key=lambda i: math.hypot(
                        centre["x"] - mids[i]["x"], centre["y"] - mids[i]["y"]))
                    if math.hypot(centre["x"] - mids[k]["x"], centre["y"] - mids[k]["y"]) > 1.9 * f:
                        continue
                    a, b = edges[k]
                    dist, _ = seg_dist(centre, a, b)
                    inside = in_polygon(centre, px)
                    # The label is centred 1.05 em out along the edge normal, so the half
                    # that matters is the half along that normal: a wide label on a
                    # vertical side reaches back over the line.
                    nx, ny = -(b["y"] - a["y"]), b["x"] - a["x"]
                    nl = math.hypot(nx, ny) or 1
                    reach = (abs(nx / nl) * lb["w"] + abs(ny / nl) * lb["h"]) / 2
                    overlap = reach - dist
                    found["labels"].append({"text": lb["text"],
                                            "edge_px": round(dist, 1), "inside": inside,
                                            "overlap_px": round(overlap, 1)})
                    if inside:
                        found["flags"].append(f"label '{lb['text']}' is inside the outlined shape")
                    elif overlap > 1:
                        found["flags"].append(f"label '{lb['text']}' crosses its own outline by "
                                              f"{overlap:.0f} px")
        elif shape["tag"] == "ot-segment" and len(px) == 2:
            length = unit_len(px[0], px[1])
            number = label_number(shape["text"])
            row = {"tag": shape["tag"], "id": shape["id"], "label": shape["text"],
                   "units": round(length, 3), "number": number}
            if number:
                row["implied_scale"] = round(length / number, 3)
            found["lengths"].append(row)
            # Its own label: the one nearest the segment's middle.
            matching = [lb for lb in graph["labels"] if lb["text"] == shape["text"]]
            if shape["text"] and matching:
                mid = {"x": (px[0]["x"] + px[1]["x"]) / 2, "y": (px[0]["y"] + px[1]["y"]) / 2}
                lb = min(matching, key=lambda l: math.hypot(
                    l["x"] + l["w"] / 2 - mid["x"], l["y"] + l["h"] / 2 - mid["y"]))
                centre = {"x": lb["x"] + lb["w"] / 2, "y": lb["y"] + lb["h"] / 2}
                dist, _ = seg_dist(centre, px[0], px[1])
                nx, ny = -(px[1]["y"] - px[0]["y"]), px[1]["x"] - px[0]["x"]
                nl = math.hypot(nx, ny) or 1
                reach = (abs(nx / nl) * lb["w"] + abs(ny / nl) * lb["h"]) / 2
                overlap = reach - dist
                found["labels"].append({"text": lb["text"], "segment": shape["id"],
                                        "edge_px": round(dist, 1), "inside": False,
                                        "overlap_px": round(overlap, 1)})
                if overlap > 1:
                    found["flags"].append(f"label '{lb['text']}' on segment {shape['id'] or '?'} "
                                          f"crosses its own line by {overlap:.0f} px")
    return found


def analyse_page(report: dict) -> dict:
    """Turn one rendered page's measurements into a verdict per size."""
    spec = spec_for(report["name"])
    verdict: dict = {"case": report["name"], "sizes": {}}
    for key, info in report["sizes"].items():
        f = float(info.get("fontPx") or 16)
        graphs = [analyse_graph(g, f) for g in info["graphs"]]
        flags = [flag for g in graphs for flag in g["flags"]]
        text = (info.get("text") or "").lower()
        leaks = [word for word in spec.get("forbid", []) if word.lower() in text]
        if leaks:
            flags.append("possible answer leak in visible text: " + ", ".join(leaks))
        named = [i for i in info.get("ids", []) if any(
            word.lower() in i.lower() for word in spec.get("pointable", []))]
        if not named:
            flags.append("no pointable part named for: " + ", ".join(spec.get("pointable", [])))
        if any(len(g["kinds"]) == 0 for g in graphs):
            flags.append("an ot-graph has no drawable children")
        verdict["sizes"][key] = {
            "fontPx": f, "issues": info.get("issues"), "graphs": graphs, "flags": flags,
            "ids": info.get("ids"), "pointable": info.get("pointable"),
            "pointable_named": named,
            "visible_text": (info.get("text") or "").strip()[:1200],
        }
    return verdict


# ---------------------------------------------------------------- the two jobs


def run_cases(out: pathlib.Path, case_ids: list[str]) -> list[dict]:
    """Real Screen jobs: the deployed writer, the real prompt and renderer."""
    from open_tutor.screen import Screen, strip_fences

    rows = []
    for case_id in case_ids:
        folder = out / case_id
        folder.mkdir(parents=True, exist_ok=True)
        ask, steer = ask_for(case_id)
        holder: dict = {}

        async def main() -> None:
            screen = Screen({"name": "Nova", "grade": 6}, folder, session_id=f"geom-{case_id}",
                            get_pane_size=lambda: SIZES[0])
            screen.add_turn("child", "Jag har prov på geometri imorgon och blandar ihop begreppen.")

            async def model(system, user, images, look_png):
                started = time.monotonic()
                text = await asyncio.to_thread(screen._default_model_call, system, user,
                                               images, look_png)
                holder.setdefault("calls", []).append(
                    {"look": bool(look_png), "seconds": round(time.monotonic() - started, 2),
                     "user_chars": len(user), "answer_chars": len(text)})
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
                meta = {"case": case_id, "ask": ask, "steer": steer,
                        "pane": list(SIZES[0]), "wall_s": round(wall, 2),
                        "spec": screen.model_spec(), "calls": holder.get("calls", []),
                        "failures": failures}
                raw = strip_fences(holder.get("raw", ""))
                (folder / "ask.txt").write_text(ask, encoding="utf-8")
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
        body = (folder / "raw.html")
        if body.is_file() and body.read_text().strip():
            with _browser() as browser:
                report = measure_body(body.read_text(), case_id, folder, browser)
            (folder / "measure.json").write_text(
                json.dumps(analyse_page(report), ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def run_patch(out: pathlib.Path, case_ids: list[str]) -> list[dict]:
    """One tutor follow-up on an already delivered page: a real patch, applied."""
    from open_tutor.screen import PageResult, Screen

    rows = []
    for case_id in case_ids:
        spec = PATCH[case_id]
        base = out / spec["base"]
        source = base / "delivered.html"
        if not source.is_file():
            source = base / "raw.html"
        if not source.is_file():
            raise SystemExit(f"{case_id}: no {spec['base']} page to patch; run that case first")
        body = source.read_text()
        folder = out / case_id
        folder.mkdir(parents=True, exist_ok=True)
        result: dict = {}

        async def main() -> None:
            screen = Screen({"name": "Nova", "grade": 6}, folder, session_id=f"geom-{case_id}",
                            get_pane_size=lambda: SIZES[0])
            screen.pages["sida-1"] = PageResult(job_id="base", page_id="sida-1",
                                                title="bas", body=body, png=b"")
            screen.mark_visible("sida-1")
            screen.add_turn("child", "Jag har prov på geometri imorgon och blandar ihop begreppen.")
            patches, pages, failures = [], [], []

            async def model(system, user, images, look_png):
                started = time.monotonic()
                text = await asyncio.to_thread(screen._default_model_call, system, user,
                                               images, look_png)
                holder.append({"look": bool(look_png), "seconds": round(time.monotonic() - started, 2),
                               "chars": len(text)})
                return text

            holder: list = []
            screen._model_call = model
            screen.on_patch, screen.on_page = patches.append, pages.append
            screen.on_failure = failures.append
            wall = time.monotonic()
            screen.ask(spec["ask"])
            await screen.wait_idle()
            wall = time.monotonic() - wall
            try:
                meta = {"case": case_id, "base_case": spec["base"], "ask": spec["ask"],
                        "pane": list(SIZES[0]), "wall_s": round(wall, 2),
                        "spec": screen.model_spec(), "calls": holder, "failures": failures,
                        "new_pages": len(pages)}
                (folder / "ask.txt").write_text(spec["ask"], encoding="utf-8")
                patch = patches[0].patch if patches else ""
                (folder / "patch.html").write_text(patch, encoding="utf-8")
                if patches:
                    meta.update(model_s=patches[0].model_s, render_s=patches[0].render_s,
                                total_s=patches[0].total_s, issues=patches[0].issues,
                                visible_ids=re.findall(r'id="([^"]+)"', body),
                                targets=re.findall(r'<ot-patch[^>]*target="([^"]+)"', patch))
                    missing = [t for t in meta["targets"] if t not in meta["visible_ids"]]
                    meta["missing_targets"] = missing
                (folder / "meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
                result["patch"] = patch
                rows.append(meta)
                print(case_id, json.dumps(meta, ensure_ascii=False), flush=True)
            finally:
                await screen.aclose()

        asyncio.run(main())
        patch = result.get("patch", "")
        if patch:
            # the child's screen: the delivered page, then this change
            with _browser() as browser:
                report = measure_body(body, f"{case_id}-delivered", folder, browser)
                (folder / "measure.json").write_text(
                    json.dumps(analyse_page(report), ensure_ascii=False, indent=1), encoding="utf-8")
                after = measure_body(body, case_id, folder, browser, patch=patch)
            (folder / "measure-after.json").write_text(
                json.dumps(analyse_page(after), ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def _browser():
    from playwright.sync_api import sync_playwright

    class Ctx:
        def __enter__(self):
            self._pw = sync_playwright().start()
            self.browser = self._pw.chromium.launch()
            return self.browser

        def __exit__(self, *exc):
            self.browser.close()
            self._pw.stop()

    return Ctx()


def measure_dir(directory: pathlib.Path) -> None:
    """Re-render and re-measure saved raw bodies; no provider call."""
    with _browser() as browser:
        for folder in sorted(p for p in directory.iterdir() if p.is_dir()):
            body = folder / "raw.html"
            if not body.is_file() or not body.read_text().strip():
                continue
            report = measure_body(body.read_text(), folder.name, folder, browser)
            (folder / "measure.json").write_text(
                json.dumps(analyse_page(report), ensure_ascii=False, indent=1), encoding="utf-8")
            print(folder.name, json.dumps({k: {"fontPx": v["fontPx"], "flags": v["flags"],
                                               "issues": v["issues"]}
                                           for k, v in json.loads(
                                               (folder / "measure.json").read_text())["sizes"].items()},
                                          ensure_ascii=False), flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="real Screen jobs, then measure their raw bodies")
    r.add_argument("--out", type=pathlib.Path, required=True)
    r.add_argument("--cases", default=",".join(CASES))
    m = sub.add_parser("measure", help="re-render and measure saved bodies (no model call)")
    m.add_argument("--dir", type=pathlib.Path, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "measure":
        measure_dir(args.dir)
        return 0
    ids = [c.strip() for c in args.cases.split(",") if c.strip()]
    unknown = [c for c in ids if c not in CASES and c not in STEERED and c not in PATCH]
    if unknown:
        raise SystemExit(f"unknown cases: {', '.join(unknown)}")
    pages = [c for c in ids if c not in PATCH]
    patches = [c for c in ids if c in PATCH]
    if pages:
        run_cases(args.out, pages)
    if patches:
        run_patch(args.out, patches)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
