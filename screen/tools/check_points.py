"""Coordinate pairing for ot-polygon/ot-segment, and the shape sliver lint.

The model writes point lists in whatever form it likes. Production showed
`points="0 0,4 0,4 3,0 3"` (pairs separated by a bare comma) turned into a thin
slanted line, because the shell split on whitespace only and read `0,4` as the
Swedish decimal 0.4. This tool pins the forms that must pair:

  uv run --project server python screen/tools/check_points.py --out /tmp/points
  uv run --project server python screen/tools/check_points.py --out /tmp/points --prior-ref <sha>
  uv run --project server python screen/tools/check_points.py --out /tmp/points --examples

Each case renders a synthetic page in headless Chromium with the worktree shell,
then compares what the shell drew (the drawn figure's pixel box) against an
independent pure-python pairing of the same attribute - never against the
shell's own helpers. A case passes when the drawn figure has the proportion its
attribute describes and the `shape` lint agrees with the independent verdict.
`--prior-ref` exports that git ref's shell and renders the same cases there: the
comma-only rectangle must already draw as a sliver-and-silent there, which is
the gap this change closes. `--examples` renders the real example bodies so a
new lint cannot start shouting about figures that are fine.

Chromium still fetches the usual public shell CDN assets (JSXGraph, KaTeX,
fonts); this is a browser evidence tool, not a network-free CI test. The CI
counterpart is screen/tests/test_points_parse.py, which imports only the pure
functions below and needs no browser or key.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIZES = ((355, 320), (1000, 700))

# --------------------------------------------------------------------------
# Independent decision logic (pure python, no browser, no shell code).
# Written from the documented forms and the production bug, not copied from
# screen/shell/shell.js; the CI test imports these names.
# --------------------------------------------------------------------------

TRUE_MINUS = "\u2212"
# The forms that worked before this fix: whitespace, ';', ", " between pairs and
# a comma between decimal commas ("0,5,1,5").
LEGACY_SPLIT_RE = re.compile(r"[\s;]+|,\s+|,(?=-?\d+,)")
FRACTION_RE = re.compile(r"^(-?\d+)/(\d+)$")
DECIMAL_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
PARENS_RE = re.compile(r"[()]")

# A polygon whose mean width is under this share of its longest side is a line.
SLIVER = 0.03
# A figure drawn smaller than this across cannot be read.
TINY_PX = 4


def num(token) -> float | None:
    """One coordinate: Swedish decimal comma, true minus, `a/b`. None if unusable.

    Approximates JavaScript's Number() for the inputs a points list holds.
    """
    if token is None:
        return None
    text = re.sub(r"\s", "", str(token).replace(TRUE_MINUS, "-"))
    fraction = FRACTION_RE.match(text)
    if fraction:
        denominator = int(fraction.group(2))
        if denominator == 0:
            return None
        return int(fraction.group(1)) / denominator
    if text == "":
        return 0.0
    text = text.replace(",", ".")
    if not DECIMAL_RE.match(text):
        return None
    return float(text)


def legacy_tokens(attr: str) -> list[str]:
    """The old split: no comma-only pair separator."""
    text = PARENS_RE.sub(" ", str(attr or "")).replace(TRUE_MINUS, "-")
    return [t for t in LEGACY_SPLIT_RE.split(text) if t != ""]


def pair_commas(attr: str) -> list[tuple[float, float]] | None:
    """Pairs split by a bare comma: `x y,x y,x y`. None when it is something else.

    Only taken when every comma-separated chunk is exactly one `x y` pair, so
    decimal commas ("1,5 2, 3 4,5") and ';' lists keep their old reading.
    """
    text = PARENS_RE.sub(" ", str(attr or "")).replace(TRUE_MINUS, "-")
    if ";" in text:
        return None
    chunks = [c.strip() for c in text.split(",")]
    chunks = [c for c in chunks if c]
    if len(chunks) < 2:
        return None
    pairs: list[tuple[float, float]] = []
    for chunk in chunks:
        tokens = chunk.split()
        if len(tokens) != 2:
            return None
        x, y = num(tokens[0]), num(tokens[1])
        if x is None or y is None:
            return None
        pairs.append((x, y))
    return pairs


def parse_points(attr: str) -> list[tuple[float, float]]:
    """The pairs the shell must draw for one points attribute."""
    paired = pair_commas(attr)
    if paired is not None:
        return paired
    values = [v for v in (num(t) for t in legacy_tokens(attr)) if v is not None]
    return [(values[i], values[i + 1]) for i in range(0, len(values) - 1, 2)]


def drawn_extent(pairs: list[tuple[float, float]]) -> tuple[float, float]:
    """Width and height of the figure in the units it was written in."""
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    return max(xs) - min(xs), max(ys) - min(ys)


def shape_verdict(attr: str, *, polygon: bool = True) -> dict:
    """Independent verdict for one figure: quiet (with reason) or one finding.

    Returns {"points": n, "kind": "points"|"identical"|"sliver"|None,
    "skipped": reason}.
    """
    pairs = parse_points(attr)
    if len(pairs) < 2:
        return {"points": len(pairs), "kind": None, "skipped": "needs points"}
    if any(not (math.isfinite(x) and math.isfinite(y)) for x, y in pairs):
        return {"points": len(pairs), "kind": None, "skipped": "non-finite coordinates"}
    if not polygon:
        return {"points": len(pairs), "kind": None, "skipped": "a segment has no area"}
    if len(pairs) < 3:
        return {"points": len(pairs), "kind": "points", "skipped": None}
    longest = 0.0
    area = 0.0
    for i, (x, y) in enumerate(pairs):
        nx, ny = pairs[(i + 1) % len(pairs)]
        area += x * ny - nx * y
        longest = max(longest, math.hypot(nx - x, ny - y))
    if longest <= 0:
        return {"points": len(pairs), "kind": "identical", "skipped": None}
    width = abs(area) / 2 / longest
    if width / longest < SLIVER:
        return {"points": len(pairs), "kind": "sliver", "skipped": None}
    return {"points": len(pairs), "kind": None, "skipped": None}


# --------------------------------------------------------------------------
# Cases: one figure each, plus the shape the attribute describes.
# --------------------------------------------------------------------------

CASES: list[dict] = [
    # Documented form (screen/REFERENCE.md): comma + space between pairs.
    {"name": "doc-comma-space", "points": "1 3, 2 3, 2 5"},
    # Production 2026-11-22: a bare comma between pairs drew a slanted line.
    {"name": "comma-only", "points": "0 0,4 0,4 3,0 3"},
    # Semicolons between pairs.
    {"name": "semicolon", "points": "0 0; 4 0; 4 3"},
    # Whitespace only.
    {"name": "spaces-only", "points": "0 0 4 0 4 3"},
    # Decimal comma inside a pair, ", " between pairs.
    {"name": "decimal-comma", "points": "1,5 2, 3 4,5 5 2"},
    # Parenthesised pairs.
    {"name": "parens", "points": "(0 0) (4 0) (4 3)"},
    # True minus (U+2212) as the shell prints it.
    {"name": "true-minus", "points": "0 0, \u22124 0, \u22124 3"},
    # Agent decimal comma plus ", " between pairs, mixed with plain pairs.
    {"name": "mixed-decimal-pairs", "points": "0 0, 2,5 0, 0 2"},
    # Segment written as from/to, including a fractional coordinate.
    {"name": "segment-from-to", "tag": "ot-segment", "from": "0 0", "to": "1/2 3"},
    # Two points cannot bound a plane figure: that is how the production
    # mis-pairing ended up, so it must be reported even after the parse is fixed.
    {"name": "polygon-two-points", "points": "0 0, 4 0"},
    # Nearly flat triangle: a real drawing mistake, must be reported.
    {"name": "sliver", "points": "0 0, 4 0, 4 0,1"},
    # Figure collapsed to a few pixels by an explicit wide range.
    {"name": "tiny", "points": "0 0, 1 0, 1 1", "graph": ' x="0 1000" y="0 1000"',
     "expect": "tiny"},
    # A deliberate sketch may be a sliver: schematic opts out.
    {"name": "schematic-sliver", "points": "0 0, 4 0, 4 0,1", "poly_attrs": " schematic",
     "expect": "quiet"},
]


def case_body(case: dict) -> tuple[str, str]:
    """One synthetic page body for a case, and the attribute its pairs come from."""
    if case.get("tag") == "ot-segment":
        figure = (f'<ot-segment id="fig" from="{case["from"]}" to="{case["to"]}">'
                  f'</ot-segment>')
        attr = f'{case["from"]}, {case["to"]}'
    else:
        figure = (f'<ot-polygon id="fig" points="{case["points"]}" fill="none"'
                  f'{case.get("poly_attrs", "")}></ot-polygon>')
        attr = case["points"]
    graph = f'<ot-graph id="graf" axes="off"{case.get("graph", "")}>{figure}</ot-graph>'
    return f"<h1>Figur</h1>{graph}", attr


# --------------------------------------------------------------------------
# Rendered evidence.
# --------------------------------------------------------------------------

_MEASURE_JS = """() => {
  const host = document.querySelector('ot-graph');
  let box = null;
  for (const el of host.querySelectorAll('svg polygon, svg line, svg path, svg ellipse, svg circle')) {
    if (el.closest('defs, clipPath')) continue;
    let bb; try { bb = el.getBBox(); } catch (e) { continue; }
    if (!bb || !(bb.width || bb.height)) continue;
    const x0 = bb.x, y0 = bb.y, x1 = bb.x + bb.width, y1 = bb.y + bb.height;
    box = box ? {x0: Math.min(box.x0, x0), y0: Math.min(box.y0, y0),
                 x1: Math.max(box.x1, x1), y1: Math.max(box.y1, y1)}
              : {x0: x0, y0: y0, x1: x1, y1: y1};
  }
  return box ? {w: box.x1 - box.x0, h: box.y1 - box.y0} : null;
}"""


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


def render_case(body: str, shell, browser, sizes=SIZES) -> dict:
    """Render one body at each size: the drawn box and the shell's own issues."""
    sys.path.insert(0, str(ROOT / "tools"))
    import screenkit

    doc = screenkit.compose(body, shell)
    out: dict = {}
    for (w, h) in sizes:
        page = browser.new_page(viewport={"width": w, "height": h})
        try:
            page.set_content(screenkit.host_page(doc))
            frame = page.frames[1]
            frame.wait_for_function(
                "() => document.documentElement.dataset.otReady === '1'", timeout=30000)
            info = frame.evaluate("() => ({fontPx: ot.fontPx, issues: ot.issues})")
            assert isinstance(info.get("fontPx"), (int, float)) and info["fontPx"] > 0, \
                f"page did not settle: {info}"
            kinds = {i.get("kind") for i in info.get("issues") or []}
            assert not (kinds & {"boot", "load", "draw", "graph"}), \
                f"figure failed to draw, measurement untrusted: {info['issues']}"
            out[f"{w}x{h}"] = {"box": frame.evaluate(_MEASURE_JS), "issues": info["issues"]}
        finally:
            page.close()
    return out


def issue_kind(issue) -> str:
    if isinstance(issue, dict):
        return str(issue.get("kind") or "").strip().lower()
    m = re.match(r"\s*([A-Za-z_-]+)\s*:", str(issue or ""))
    return m.group(1).lower() if m else ""


def shape_issues(issues: list) -> list:
    return [i for i in issues if issue_kind(i) == "shape"]


def run_cases(shell, tag: str) -> tuple[list[str], list[str], list[dict]]:
    """Every form must draw the figure its own coordinates describe."""
    failures: list[str] = []
    records: list[dict] = []
    with _browser() as browser:
        for case in CASES:
            body, attr = case_body(case)
            expected_pairs = parse_points(attr)
            verdict = shape_verdict(attr, polygon=case.get("tag") != "ot-segment")
            want = case.get("expect") or ("issue" if verdict["kind"] else "quiet")
            try:
                rendered = render_case(body, shell, browser)
            except AssertionError as e:
                failures.append(f"{tag} {case['name']}: untrusted measurement: {e}")
                continue
            ew, eh = drawn_extent(expected_pairs)
            wanted_aspect = ew / eh if eh else math.inf  # 0-height figures have no ratio
            for size, measurement in rendered.items():
                box = measurement["box"]
                got = shape_issues(measurement["issues"])
                records.append({"case": case["name"], "tag": tag, "size": size,
                                "box": box, "shape": got})
                if box is None:
                    failures.append(f"{tag} {case['name']} {size}: nothing was drawn")
                    continue
                if want == "tiny":
                    if not got:
                        failures.append(
                            f"{tag} {case['name']} {size}: drawn {box['w']:.1f}x{box['h']:.1f} px"
                            f" with no shape issue: {measurement['issues']}")
                    continue
                if want == "quiet" and got:
                    failures.append(
                        f"{tag} {case['name']} {size}: must stay quiet, got {got}")
                    continue
                if want == "issue" and not got:
                    failures.append(
                        f"{tag} {case['name']} {size}: collapsed figure drew"
                        f" {box['w']:.1f}x{box['h']:.1f} px with no shape issue")
                    continue
                # The drawn box must have the proportion the attribute describes.
                if box["w"] >= 6 and box["h"] >= 6 and math.isfinite(wanted_aspect):
                    got_aspect = box["w"] / box["h"]
                    if abs(got_aspect / wanted_aspect - 1) > 0.06:
                        failures.append(
                            f"{tag} {case['name']} {size}: drew {box['w']:.1f}x{box['h']:.1f} px"
                            f" (ratio {got_aspect:.2f}), the coordinates say"
                            f" {ew:g}x{eh:g} (ratio {wanted_aspect:.2f});"
                            f" independent pairs {expected_pairs}")
                elif box["w"] < 6 and box["h"] < 6:
                    failures.append(
                        f"{tag} {case['name']} {size}: figure is only"
                        f" {box['w']:.1f}x{box['h']:.1f} px")
    return failures, [], records


def run_lifecycle(shell) -> list[str]:
    """A sliver stays quiet while hidden, is reported once revealed, and clears
    when a patch repairs it - the same lifecycle the other lints follow."""
    failures: list[str] = []
    sliver = case_body([c for c in CASES if c["name"] == "sliver"][0])[0]
    hidden = sliver.replace('id="fig"', 'id="fig" later')
    with _browser() as browser:
        sys.path.insert(0, str(ROOT / "tools"))
        import screenkit

        def measured(body: str, reveal: str | None = None) -> dict:
            doc = screenkit.compose(body, shell)
            page = browser.new_page(viewport={"width": 355, "height": 320})
            try:
                page.set_content(screenkit.host_page(doc))
                frame = page.frames[1]
                frame.wait_for_function(
                    "() => document.documentElement.dataset.otReady === '1'", timeout=30000)
                if reveal:
                    frame.evaluate("(id) => ot.reveal(id)", reveal)
                    frame.wait_for_timeout(300)
                return frame.evaluate("() => ({issues: ot.issues})")["issues"]
            finally:
                page.close()

        if shape_issues(measured(hidden)):
            failures.append("hidden sliver warned before it was revealed")
        if not shape_issues(measured(hidden, reveal="fig")):
            failures.append("revealed sliver was not reported")
        repaired = ('<ot-patch target="fig"><ot-polygon id="fig" points="0 0,4 0,4 3,0 3"'
                    ' fill="none"></ot-polygon></ot-patch>')
        doc = screenkit.compose(sliver, shell)
        page = browser.new_page(viewport={"width": 355, "height": 320})
        try:
            page.set_content(screenkit.host_page(doc))
            frame = page.frames[1]
            frame.wait_for_function(
                "() => document.documentElement.dataset.otReady === '1'", timeout=30000)
            frame.evaluate("(p) => ot.patch(p)", repaired)
            frame.wait_for_timeout(400)
            if shape_issues(frame.evaluate("() => ({issues: ot.issues})")["issues"]):
                failures.append("a repaired figure kept its shape warning")
        finally:
            page.close()
    return failures


def run_examples(shell, out: Path) -> tuple[list[str], list[dict]]:
    """Real example bodies: the shell agrees with the independent verdict."""
    failures: list[str] = []
    records: list[dict] = []
    bodies = {p.name.removesuffix(".html"): p for p in sorted((ROOT / "examples").glob("*.html"))
              if not p.name.endswith(".patch.html")}
    with _browser() as browser:
        for name, path in bodies.items():
            body = path.read_text()
            if not re.search(r"<ot-(polygon|segment)\b", body, re.IGNORECASE):
                continue
            try:
                rendered = render_case(body, shell, browser, sizes=((370, 610),))
            except AssertionError as e:
                failures.append(f"examples {name}: untrusted measurement: {e}")
                continue
            for size, measurement in rendered.items():
                got = shape_issues(measurement["issues"])
                records.append({"case": f"example {name}", "size": size,
                                "box": measurement["box"], "shape": got})
                if got:
                    failures.append(f"examples {name} {size}: {got}")
            out.joinpath(f"example-{name}.json").write_text(
                json.dumps(rendered, ensure_ascii=False, indent=1))
    return failures, records


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "review/2026-11-22-points"))
    ap.add_argument("--shell", default=None)
    ap.add_argument("--prior-ref", default=None)
    ap.add_argument("--examples", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    shell = Path(args.shell) if args.shell else None
    failures, _, records = run_cases(shell, "new")
    if not failures:
        failures.extend(run_lifecycle(shell))
    if args.examples:
        ex_failures, ex_records = run_examples(shell, out)
        failures.extend(ex_failures)
        records.extend(ex_records)
    result: dict = {"shell": str(shell or "worktree"), "failures": failures,
                    "cases": records}
    if args.prior_ref:
        tmp = out / "_prior_shell"
        (tmp / "data").mkdir(parents=True, exist_ok=True)
        repo = ROOT.parent
        for f in ("frame.html", "shell.css", "shell.js"):
            blob = subprocess.run(
                ["git", "-C", str(repo), "show", f"{args.prior_ref}:screen/shell/{f}"],
                capture_output=True, check=True).stdout
            (tmp / f).write_bytes(blob)
        sys.path.insert(0, str(ROOT / "tools"))
        import screenkit
        (tmp / "data" / "lan-sverige.json").write_bytes(
            (screenkit.SHELL / "data" / "lan-sverige.json").read_bytes())
        prior_failures, _, prior_records = run_cases(tmp, "prior")
        result["prior_shell"] = {"failures": prior_failures, "cases": prior_records}
        # The gap this change closes: on the prior shell the comma-only
        # rectangle still draws (no crash) but has the wrong proportion.
        comma_only = [f for f in prior_failures
                      if "comma-only" in f and "drew" in f and "ratio" in f]
        if not comma_only:
            result["failures"] = failures + [
                "prior shell does not show the bug: the comma-only rectangle"
                " should draw with the wrong ratio there"]
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    if failures:
        print("FAIL:")
        for failure in failures:
            print("  " + failure)
        raise SystemExit(1)
    print("OK: every accepted points form draws the figure its coordinates describe;"
          " collapsed figures are reported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
