"""Qualified length lint: drawn polygon sides vs their labels, without model calls.

Renders synthetic and real writer bodies at 370x610 and 1000x700 with the
worktree shell, collects the shell's `length` lint, and compares it against an
independent pure-python verdict computed from the page source (not from the
shell's DOM or its parsing helpers). A case passes when every inconsistency
the independent check finds is named by shell lint, and no consistent,
unknown, hidden or opted-out case warns.

  uv run --project server python screen/tools/check_lengths.py --out /tmp/lengths
  uv run --project server python screen/tools/check_lengths.py --out /tmp/lengths --prior-ref 950b3b0

--prior-ref exports that git ref's shell and renders the same bodies there:
the inconsistent case must render fine but stay silent (the gap this lint
closes), while consistent cases stay quiet on both shells.

Chromium still fetches the usual public shell CDN assets (JSXGraph, KaTeX,
fonts); this is a browser evidence tool, not a network-free CI test. The CI
counterpart is screen/tests/test_length_lint.py, which imports only the pure
decision functions below and needs no browser or key.
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
SIZES = ((370, 610), (1000, 700))

# --------------------------------------------------------------------------
# Independent decision logic (pure python, no browser, no shell code).
# Written from the design, not copied from screen/shell/shell.js; the CI test
# imports these names.
# --------------------------------------------------------------------------

LENGTH_UNITS = {"mm": 1.0, "cm": 10.0, "dm": 100.0, "m": 1000.0}
TOLERANCE = 0.15

_LABEL_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|dm|m)\s*$", re.IGNORECASE)
_DIMENSION_RE = re.compile(r"[°²³%]|(?:mm|cm|dm|m)\s*\d", re.IGNORECASE)
_TOKEN_SPLIT_RE = re.compile(r"[\s;]+|,\s+|,(?=-?\d+,)")


def parse_length_label(text: str) -> float | None:
    """A strict numeric length label in mm, else None (unknown, not a claim)."""
    m = _LABEL_RE.match(text or "")
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value * LENGTH_UNITS[m.group(2).lower()]


def split_coords(points_attr: str) -> list[float] | None:
    """Strict coordinate pairing: None unless every value is finite and paired."""
    toks = [t for t in _TOKEN_SPLIT_RE.split(
        (points_attr or "").replace("(", " ").replace(")", " ").replace("−", "-")) if t.strip()]
    if len(toks) < 6 or len(toks) % 2:
        return None
    try:
        nums = [float(t.replace(",", ".")) for t in toks]
    except ValueError:
        return None
    if any(not math.isfinite(n) for n in nums):
        return None
    return nums


def analyse_polygon(points_attr: str, sides_attr: str) -> dict:
    """Independent verdict for one polygon: quiet (with reason) or findings.

    Returns {"known": [...], "flags": [...], "skipped": reason-or-None}.
    A finding names 1-based side number(s) and direction, never a target value.
    """
    labels = [(s or "").strip() for s in (sides_attr or "").split("|")]
    if not any(labels):
        return {"known": [], "flags": [], "skipped": "no sides"}
    if _DIMENSION_RE.search(sides_attr or ""):
        return {"known": [], "flags": [], "skipped": "mixed dimensions"}
    coords = split_coords(points_attr or "")
    if coords is None:
        return {"known": [], "flags": [], "skipped": "missing/degenerate coordinates"}
    edges = [math.hypot(coords[(k + 2) % len(coords)] - coords[k],
                         coords[(k + 3) % len(coords)] - coords[k + 1])
             for k in range(0, len(coords), 2)]
    if any(not (e > 1e-9) for e in edges):
        return {"known": [], "flags": [], "skipped": "degenerate edge"}
    known = []
    for i, text in enumerate(labels):
        if i >= len(edges):
            break
        mm = parse_length_label(text)
        if mm is not None:
            known.append({"side": i + 1, "text": text, "scale": edges[i] / mm})
    if len(known) < 2:
        return {"known": known, "flags": [], "skipped": "fewer than two known measures"}
    if any(not (math.isfinite(r["scale"]) and r["scale"] > 0) for r in known):
        return {"known": known, "flags": [], "skipped": "non-finite scale"}
    scales = sorted(r["scale"] for r in known)
    if len(known) == 2:
        if scales[0] / scales[1] < 1 - TOLERANCE:
            return {"known": known, "flags": [
                {"sides": [known[0]["side"], known[1]["side"]], "direction": "disagree"}],
                "skipped": None}
        return {"known": known, "flags": [], "skipped": None}
    mid = len(scales) // 2
    med = scales[mid] if len(scales) % 2 else (scales[mid - 1] + scales[mid]) / 2
    if not med > 0:
        return {"known": known, "flags": [], "skipped": "non-finite median"}
    flags = []
    for r in known:
        dev = r["scale"] / med - 1
        if abs(dev) > TOLERANCE:
            flags.append({"sides": [r["side"]], "text": r["text"],
                          "direction": "shorter" if dev < 0 else "longer",
                          "pct": round(abs(dev) * 100)})
    return {"known": known, "flags": flags, "skipped": None}


# --------------------------------------------------------------------------
# Bodies: synthetic qualification cases plus real writer output.
# --------------------------------------------------------------------------

CASES: dict[str, str] = {
    # Consistent 4x3 rectangle: quiet (scale-free: drawing units are free).
    "ok-rect": ('<h1>Rektangel</h1><ot-graph id="figurer" axes="off">'
                '<ot-polygon id="rektangel" points="0 0, 4 0, 4 3, 0 3"'
                ' sides="4 cm | 3 cm | 4 cm | 3 cm" color="cyan" fill="none">'
                '</ot-polygon></ot-graph>'),
    # Canonical counterexample: one label a whole unit off (drawn 4, says 5).
    "bad-4vs5": ('<h1>Rektangel</h1><ot-graph id="figurer" axes="off">'
                 '<ot-polygon id="rektangel" points="0 0, 4 0, 4 3, 0 3"'
                 ' sides="5 cm | 3 cm | 4 cm | 3 cm" color="cyan" fill="none">'
                 '</ot-polygon></ot-graph>'),
    # Same rectangle 2.5x larger: ratios, not absolute scale, decide. Quiet.
    "ok-scaled": ('<h1>Rektangel</h1><ot-graph id="figurer" axes="off">'
                  '<ot-polygon id="rektangel" points="0 0, 10 0, 10 7,5, 0 7,5"'
                  ' sides="4 cm | 3 cm | 4 cm | 3 cm" color="cyan" fill="none">'
                  '</ot-polygon></ot-graph>'),
    # Rounded coordinates (height 2*sqrt(3) = 3.464... written 3,46). Quiet.
    "ok-tri-round": ('<h1>Triangel</h1><ot-graph id="tri" axes="off">'
                     '<ot-polygon id="triangel" points="0 0, 4 0, 2 3,46"'
                     ' sides="4 cm | 4 cm | 4 cm" color="amber" fill="none">'
                     '</ot-polygon></ot-graph>'),
    # Compatible mixed units (mm/cm/m with decimal comma). Quiet.
    "ok-mixed-units": ('<h1>Rektangel</h1><ot-graph id="figurer" axes="off">'
                       '<ot-polygon id="rektangel" points="0 0, 40 0, 40 30, 0 30"'
                       ' sides="4 cm | 30 mm | 0,04 m | 30 mm" color="cyan" fill="none">'
                       '</ot-polygon></ot-graph>'),
    # Unknown side: no claim, quiet (a "find x" exercise must never warn).
    "ok-unknown": ('<h1>Triangel</h1><ot-graph id="tri" axes="off">'
                   '<ot-polygon id="triangel" points="0 0, 4 0, 0 3"'
                   ' sides="4 cm | ? | 3 cm" color="amber" fill="none">'
                   '</ot-polygon></ot-graph>'),
    # Algebra side: unknown, quiet.
    "ok-algebra": ('<h1>Triangel</h1><ot-graph id="tri" axes="off">'
                   '<ot-polygon id="triangel" points="0 0, 4 0, 0 3"'
                   ' sides="4 cm | x + 2 | 3 cm" color="amber" fill="none">'
                   '</ot-polygon></ot-graph>'),
    # Angle marker among sides: mixed dimensions, whole polygon skipped. Quiet.
    "ok-angle": ('<h1>Triangel</h1><ot-graph id="tri" axes="off">'
                 '<ot-polygon id="triangel" points="0 0, 4 0, 0 3"'
                 ' sides="4 cm | 60° | 3 cm" color="amber" fill="none">'
                 '</ot-polygon></ot-graph>'),
    # Area marker among sides: mixed dimensions, skipped. Quiet.
    "ok-area": ('<h1>Triangel</h1><ot-graph id="tri" axes="off">'
                '<ot-polygon id="triangel" points="0 0, 4 0, 0 3"'
                ' sides="4 cm | 12 cm² | 3 cm" color="amber" fill="none">'
                '</ot-polygon></ot-graph>'),
    # Declared unequal units: ratios are meaningless. Quiet even when off.
    "ok-free": ('<h1>Rektangel</h1><ot-graph id="figurer" free axes="off">'
                '<ot-polygon id="rektangel" points="0 0, 4 0, 4 3, 0 3"'
                ' sides="5 cm | 3 cm | 4 cm | 3 cm" color="cyan" fill="none">'
                '</ot-polygon></ot-graph>'),
    # Deliberate schematic: opted out. Quiet even when off.
    "ok-schematic": ('<h1>Skiss</h1><ot-graph id="figurer" axes="off">'
                     '<ot-polygon id="rektangel" points="0 0, 4 0, 4 3, 0 3" schematic'
                     ' sides="5 cm | 3 cm | 4 cm | 3 cm" color="cyan" fill="none">'
                     '</ot-polygon></ot-graph>'),
    # Foreshortened 3D edges are segments, never side claims. Quiet.
    "ok-segments": ('<h1>Rätblock</h1><ot-graph id="ratblock" axes="off">'
                    '<ot-polygon points="0 0, 4 0, 4 2, 0 2" fill="none"></ot-polygon>'
                    '<ot-segment id="djup" from="4 0" to="5.5 1">3 cm</ot-segment>'
                    '</ot-graph>'),
    # Exactly two known sides, disagreeing: joint finding, no direction. Warns.
    "joint-two": ('<h1>Triangel</h1><ot-graph id="tri" axes="off">'
                  '<ot-polygon id="triangel" points="0 0, 4 0, 0 3"'
                  ' sides="5 cm | 3 cm | ?" color="amber" fill="none">'
                  '</ot-polygon></ot-graph>'),
    # Small labelled edges probe the rounding margin. Quiet.
    "ok-small": ('<h1>Triangel</h1><ot-graph id="tri" axes="off">'
                 '<ot-polygon id="triangel" points="0 0, 2 0, 0 1"'
                 ' sides="2 cm | 2,24 cm | 1 cm" color="amber" fill="none">'
                 '</ot-polygon></ot-graph>'),
    # Non-finite coordinates: no claim, never a crash. Quiet.
    "ok-nonfinite": ('<h1>Triangel</h1><ot-graph id="tri" axes="off">'
                     '<ot-polygon id="triangel" points="0 0, x 1, 4 0, 4 3"'
                     ' sides="5 cm | 3 cm | 4 cm | 3 cm" color="amber" fill="none">'
                     '</ot-polygon></ot-graph>'),
    # Zero-length edge: degenerate, a draw issue, not a length claim. Quiet.
    "ok-degenerate": ('<h1>Rektangel</h1><ot-graph id="figurer" axes="off">'
                      '<ot-polygon id="rektangel" points="0 0, 0 0, 4 0, 4 3"'
                      ' sides="5 cm | 3 cm | 4 cm | 3 cm" color="cyan" fill="none">'
                      '</ot-polygon></ot-graph>'),
}

# Real writer bodies (unedited Hydrogen output from the geometry research batch,
# now on main): the plane page is exactly consistent, the cuboid uses segments.
MODEL_BODIES: dict[str, str] = {
    "model-plan": (ROOT / "review/2026-11-13-geometry/raw/plan/raw.html").read_text(),
    "model-ratblock": (ROOT / "review/2026-11-13-geometry/raw/ratblock/raw.html").read_text(),
}

_POLYGON_RE = re.compile(r"<ot-polygon\b([^>]*)>", re.IGNORECASE)
_ATTR_RE = re.compile(r'([\w-]+)(?:\s*=\s*"([^"]*)")?')


def independent_verdict(body: str) -> dict[str, dict]:
    """Per-polygon independent verdicts from the page source, keyed by order."""
    graphs = re.split(r"(?i)(<ot-graph\b[^>]*>)", body)
    out: dict[str, dict] = {}
    graph_free = graph_schem = False
    poly_index = 0
    for part in graphs:
        if re.match(r"(?i)<ot-graph\b", part or ""):
            attrs = dict((k.lower(), v if v is not None else "")
                         for k, v in _ATTR_RE.findall(part))
            graph_free = "free" in attrs
            graph_schem = "schematic" in attrs
            continue
        for m in _POLYGON_RE.finditer(part or ""):
            attrs = dict((k.lower(), v if v is not None else "")
                         for k, v in _ATTR_RE.findall(m.group(1)))
            poly_index += 1
            pid = attrs.get("id", "") or f"polygon-{poly_index}"
            if graph_free or graph_schem or "schematic" in attrs:
                out[pid] = {"known": [], "flags": [],
                            "skipped": "opted out (free/schematic)"}
                continue
            out[pid] = analyse_polygon(attrs.get("points", ""), attrs.get("sides", ""))
    return out


# --------------------------------------------------------------------------
# Rendered evidence.
# --------------------------------------------------------------------------

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


def render_issues(body: str, shell, browser, patch: str | None = None,
                  reveal: str | None = None, shot_prefix: Path | None = None) -> dict:
    """Render at both sizes; assert boot success and finite inputs; return issues."""
    sys.path.insert(0, str(ROOT / "tools"))
    import screenkit

    doc = screenkit.compose(body, shell)
    report: dict = {}
    for (w, h) in SIZES:
        page = browser.new_page(viewport={"width": w, "height": h})
        try:
            page.set_content(screenkit.host_page(doc))
            frame = page.frames[1]
            frame.wait_for_function(
                "() => document.documentElement.dataset.otReady === '1'", timeout=30000)
            if patch:
                frame.evaluate("(p) => ot.patch(p)", patch)
                frame.wait_for_timeout(300)
            if reveal:
                assert frame.evaluate("(id) => ot.reveal(id)", reveal)
                frame.wait_for_timeout(300)
            info = frame.evaluate("() => ({fontPx: ot.fontPx, issues: ot.issues})")
            font = info.get("fontPx")
            assert isinstance(font, (int, float)) and math.isfinite(font) and font > 0, \
                f"non-finite fontPx: {font!r}"
            kinds = {i.get("kind") for i in info.get("issues") or []}
            assert not (kinds & {"boot", "load", "draw"}), \
                f"graph failed to boot, measurement untrusted: {info['issues']}"
            report[f"{w}x{h}"] = info.get("issues") or []
            if shot_prefix is not None:
                page.screenshot(path=str(shot_prefix) + f"-{w}x{h}.png")
        finally:
            page.close()
    return report


def length_issues(issues: list) -> list:
    return [i for i in issues if issue_kind(i) == "length"]


def issue_kind(issue) -> str:
    if isinstance(issue, dict):
        return str(issue.get("kind") or "").strip().lower()
    m = re.match(r"\s*([A-Za-z_-]+)\s*:", str(issue or ""))
    return m.group(1).lower() if m else ""


def fixed_body(body: str, patch: str) -> str:
    """Apply a single replace-patch to the source (test helper, not the shell)."""
    m = re.search(r'<ot-patch\b[^>]*target="([^"]+)"[^>]*>(.*)</ot-patch>', patch, re.S)
    assert m, f"cannot read patch: {patch[:80]}"
    target, replacement = m.group(1), m.group(2)
    full = re.compile(r'<ot-polygon\b[^>]*id="' + re.escape(target) + r'"[^>]*>.*?</ot-polygon>', re.S)
    assert full.search(body), f"patch target {target} missing"
    return full.sub(lambda _: replacement, body, count=1)


def check_lifecycle(shell, out: Path) -> list[str]:
    """Hidden/reveal, patch replacement/repair and resizing; schematic survival."""
    from playwright.sync_api import sync_playwright

    sys.path.insert(0, str(ROOT / "tools"))
    import screenkit

    failures: list[str] = []
    bad = CASES["bad-4vs5"]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            # Hidden inconsistent figure stays quiet until revealed.
            hidden = bad.replace('id="rektangel"', 'id="rektangel" later')
            issues = render_issues(hidden, shell, browser)
            if any(length_issues(v) for v in issues.values()):
                failures.append("hidden inconsistent polygon warned before reveal")
            revealed = render_issues(hidden, shell, browser, reveal="rektangel")
            if not all(len(length_issues(v)) == 1 for v in revealed.values()):
                failures.append(f"revealed inconsistency not flagged at both sizes: {revealed}")
            # Hidden consistent figure stays quiet after reveal too.
            ok_hidden = CASES["ok-rect"].replace('id="rektangel"', 'id="rektangel" later')
            ok_revealed = render_issues(ok_hidden, shell, browser, reveal="rektangel")
            if any(length_issues(v) for v in ok_revealed.values()):
                failures.append(f"revealed consistent polygon warned: {ok_revealed}")
            # Patch repair: fix the label, final lint must be clean.
            fixed = ('<ot-patch target="rektangel"><ot-polygon id="rektangel" points="0 0, 4 0, 4 3, 0 3"'
                     ' sides="4 cm | 3 cm | 4 cm | 3 cm" color="cyan" fill="none"></ot-polygon></ot-patch>')
            after = render_issues(bad, shell, browser, patch=fixed)
            if any(length_issues(v) for v in after.values()):
                failures.append(f"repaired warning retained: {after}")
            # Resizing never changes an attribute-only verdict.
            wide = render_issues(bad, shell, browser)
            if ([len(length_issues(v)) for v in wide.values()] != [1, 1]):
                failures.append(f"verdict differs by size: {wide}")
        finally:
            browser.close()

    # Schematic opt-out survives composition on the worktree shell, native path.
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            sys.path.insert(0, str(ROOT / "tools"))
            import screenkit
            doc = screenkit.compose(CASES["ok-schematic"], shell)
            page = browser.new_page(viewport={"width": 370, "height": 610})
            try:
                page.set_content(screenkit.host_page(doc))
                frame = page.frames[1]
                frame.wait_for_function("() => document.documentElement.dataset.otReady === '1'",
                                        timeout=30000)
                if not frame.evaluate("() => document.querySelector('ot-polygon').hasAttribute('schematic')"):
                    failures.append("schematic did not survive composition (native sanitizer)")
            finally:
                page.close()
            # Forced DOMPurify fallback path (real CDN download, like check_sanitizer).
            context = browser.new_context(viewport={"width": 370, "height": 610})
            context.add_init_script("delete Element.prototype.setHTML")
            page = context.new_page()
            try:
                page.set_content(screenkit.host_page(doc))
                page.wait_for_function("() => frames.length === 1")
                frame = page.frames[1]
                frame.wait_for_function("() => document.documentElement.dataset.otReady === '1'",
                                        timeout=30000)
                if not frame.evaluate("() => document.querySelector('ot-polygon').hasAttribute('schematic')"):
                    failures.append("schematic did not survive composition (DOMPurify fallback)")
            finally:
                context.close()
        finally:
            browser.close()

    # Real server preview: the repaired body passes the real server renderer.
    # (Patch-job preview returns on main accumulate the first render's issues
    # for every lint kind, pre-existing and owned by PR56's final-lint preview
    # change; the frame-level repair above is what this lint owns. No
    # length-side change is needed there: lintLengths() already keeps final
    # lint current by dropping stale length findings before re-adding.)
    import asyncio
    import tempfile
    sys.path.insert(0, str(ROOT.parent / "server"))
    from open_tutor.screen import Screen

    async def preview():
        with tempfile.TemporaryDirectory() as directory:
            screen = Screen({}, Path(directory))
            try:
                _, issues = await screen._default_render_page(
                    fixed_body(bad, fixed), None, 370, 610)
                if [i for i in issues if issue_kind(i) == "length"]:
                    failures.append(f"server render of repaired body warns: {issues}")
            finally:
                await screen.aclose()

    asyncio.run(preview())
    return failures


def run_shell(shell, out: Path, tag: str) -> tuple[list[str], list[str]]:
    """Render every case; independent flags must all be reported, quiet cases silent."""
    failures, notes = [], []
    with _browser() as browser:
        for name, body in {**CASES, **MODEL_BODIES}.items():
            verdict = independent_verdict(body)
            expected = sum(len(v["flags"]) for v in verdict.values())
            try:
                issues = render_issues(body, shell, browser, shot_prefix=(
                    out / f"{name}-{tag}" if name in {
                        "bad-4vs5", "ok-rect", "joint-two", "ok-schematic"} else None))
            except AssertionError as e:
                failures.append(f"{tag} {name}: untrusted measurement: {e}")
                continue
            for size, size_issues in issues.items():
                got = length_issues(size_issues)
                if len(got) != expected:
                    failures.append(
                        f"{tag} {name} {size}: independent check finds {expected} "
                        f"finding(s), shell reports {len(got)}: {got}")
                for g in got:
                    msg = g.get("msg", "")
                    if "ot-polygon" not in msg or ("side" not in msg and "sides" not in msg):
                        failures.append(f"{tag} {name} {size}: issue does not name the polygon/side: {msg}")
                    if re.search(r"\d+(\.\d+)?\s*(mm|cm|dm|m)\b.*(?:should|correct|be )", msg):
                        failures.append(f"{tag} {name} {size}: issue states a target value: {msg}")
            if expected and not any(length_issues(v) for v in issues.values()):
                notes.append(f"{tag} {name}: independent flags {verdict} never surfaced")
            (out / f"{name}-{tag}.json").write_text(
                json.dumps({"independent": verdict,
                            "shell": {k: v for k, v in issues.items()}},
                           ensure_ascii=False, indent=1))
    return failures, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(ROOT / "review/2026-11-13-lengths/shots"))
    ap.add_argument("--shell", default=None)
    ap.add_argument("--prior-ref", default=None)
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    shell = Path(args.shell) if args.shell else None
    failures, notes = run_shell(shell, out, "new")
    if not failures:
        failures.extend(check_lifecycle(shell, out))
    result: dict = {"shell": str(shell or "worktree"), "failures": failures, "notes": notes}
    if args.prior_ref:
        tmp = out / "_prior_shell"
        (tmp / "data").mkdir(parents=True, exist_ok=True)
        repo = ROOT.parent
        for f in ("frame.html", "shell.css", "shell.js"):
            blob = subprocess.run(["git", "-C", str(repo), "show", f"{args.prior_ref}:screen/shell/{f}"],
                                  capture_output=True, check=True).stdout
            (tmp / f).write_bytes(blob)
        sys.path.insert(0, str(ROOT / "tools"))
        import screenkit
        (tmp / "data" / "lan-sverige.json").write_bytes(
            (screenkit.SHELL / "data" / "lan-sverige.json").read_bytes())
        prior_failures, _ = run_shell(tmp, out, "prior")
        # The gap this lint closes: the inconsistent case renders fine on the
        # prior shell (no boot failure) but silent. prior "failures" here are
        # exactly the unreported independent findings we expect.
        unreported = [f for f in prior_failures if "independent check finds" in f]
        broken = [f for f in prior_failures if f not in unreported]
        result["prior_shell_unreported"] = unreported
        result["prior_shell_broken"] = broken
        if broken:
            failures.append(f"prior shell could not render the bodies: {broken}")
        if not any("bad-4vs5" in u and "shell reports 0" in u for u in unreported):
            failures.append("prior shell does not demonstrate the gap: bad-4vs5 should be silent there")
        result["failures"] = failures
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    for n in notes:
        print(n)
    if failures:
        print("FAIL:")
        for fl in failures:
            print("  " + fl)
        raise SystemExit(1)
    print("OK: every independent length finding is reported; quiet cases stay quiet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
