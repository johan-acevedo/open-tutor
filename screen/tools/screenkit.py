"""Compose and render Smart Screen pages.

compose(body) wraps a page body in the shell (screen/shell/frame.html with the
shell CSS and JS inlined). render() loads it the way the app does - inside an
<iframe sandbox="allow-scripts" srcdoc=...> - in headless Chromium, waits until
the shell reports ready, and screenshots it; optionally applies a patch.

CLI:
  uv run --project server python screen/tools/screenkit.py render BODY.html [--patch P.html] [--out DIR] [--sizes 1366x768,390x844]
"""

from __future__ import annotations

import argparse
import html as htmllib
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHELL = ROOT / "shell"
DATA = SHELL / "data"

# Proposed frame policy for Smart Screen pages (see screen/README.md).
CSP = ("default-src 'none'; "
       "script-src 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
       "style-src 'unsafe-inline' https://cdn.jsdelivr.net; "
       "font-src https://cdn.jsdelivr.net; "
       "img-src data: https:; "
       "connect-src https://cdn.jsdelivr.net https://commons.wikimedia.org")


def compose(body: str) -> str:
    frame = (SHELL / "frame.html").read_text()
    css = (SHELL / "shell.css").read_text()
    js = (SHELL / "shell.js").read_text()
    # Sweden's 21 län travel with the shell, not with the page body (RPC keeps to ~15 kB).
    lan = json.loads((DATA / "lan-sverige.json").read_text())
    lan_text = json.dumps(lan, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    # Replace BODY last so a body can never inject into the shell slots.
    return (frame.replace("{{CSP}}", CSP).replace("{{CSS}}", css)
            .replace("{{LAN}}", lan_text)
            .replace("{{JS}}", js.replace("</script", "<\\/script"))
            .replace("{{BODY}}", htmllib.escape(body, quote=False)))


def host_page(doc: str) -> str:
    return ("<!doctype html><html><head><meta charset='utf-8'><style>html,body{margin:0;height:100%;background:#181b22}"
            "iframe{border:0;width:100%;height:100%;display:block}</style></head><body>"
            f"<iframe sandbox='allow-scripts' srcdoc=\"{htmllib.escape(doc, quote=True)}\"></iframe></body></html>")


def _frame(page):
    return page.frames[1] if len(page.frames) > 1 else page.main_frame


def render(body: str, out: pathlib.Path, name: str, sizes=((1366, 768), (390, 844)),
           patch: str | None = None, browser=None) -> dict:
    """Render a body at each size (and after its patch). Returns timings and issues."""
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    doc = compose(body)
    report: dict = {"name": name, "sizes": {}}
    own = None
    if browser is None:
        own = sync_playwright().start()
        browser = own.chromium.launch()
    try:
        for (w, h) in sizes:
            key = f"{w}x{h}"
            page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            t0 = time.monotonic()
            page.set_content(host_page(doc))
            frame = _frame(page)
            frame.wait_for_function("() => document.documentElement.dataset.otReady === '1'", timeout=30000)
            ready_ms = round((time.monotonic() - t0) * 1000)
            info = frame.evaluate("() => ({fontPx: ot.fontPx, issues: ot.issues})")
            page.screenshot(path=str(out / f"{name}-{key}.png"))
            entry = {"ready_ms": ready_ms, "fontPx": info["fontPx"], "issues": info["issues"]}
            if patch:
                patch_issues = frame.evaluate("(p) => ot.patch(p)", patch)
                page.wait_for_timeout(500)
                page.screenshot(path=str(out / f"{name}-{key}-patching.png"))
                page.wait_for_timeout(2300)
                page.screenshot(path=str(out / f"{name}-{key}-patched.png"))
                entry["patch_issues"] = patch_issues
                entry["fontPx_after"] = frame.evaluate("() => ot.fontPx")
            report["sizes"][key] = entry
            page.close()
    finally:
        if own:
            browser.close()
            own.stop()
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("body")
    r.add_argument("--patch")
    r.add_argument("--out", default=str(ROOT / "gallery" / "site" / "shots"))
    r.add_argument("--sizes", default="1366x768,390x844")
    a = sub.add_parser("render-all")
    a.add_argument("--dir", default=str(ROOT / "examples"))
    a.add_argument("--out", default=str(ROOT / "gallery" / "site" / "shots"))
    a.add_argument("--only", default="")
    c = sub.add_parser("compose")
    c.add_argument("body")
    args = ap.parse_args(argv)
    if args.cmd == "compose":
        sys.stdout.write(compose(pathlib.Path(args.body).read_text()))
        return 0
    if args.cmd == "render-all":
        from playwright.sync_api import sync_playwright
        only = [s for s in args.only.split(",") if s]
        reports = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for body_path in sorted(pathlib.Path(args.dir).glob("*.html")):
                if body_path.name.endswith(".patch.html"):
                    continue
                name = body_path.name.removesuffix(".html")
                if only and name not in only:
                    continue
                pp = body_path.with_name(name + ".patch.html")
                rep = render(body_path.read_text(), pathlib.Path(args.out), name,
                             patch=pp.read_text() if pp.exists() else None, browser=browser)
                reports.append(rep)
                print(name, json.dumps({k: {kk: vv for kk, vv in v.items()} for k, v in rep["sizes"].items()}, ensure_ascii=False))
            browser.close()
        (pathlib.Path(args.out) / "report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=1))
        return 0
    body_path = pathlib.Path(args.body)
    sizes = [tuple(int(v) for v in s.split("x")) for s in args.sizes.split(",")]
    patch = pathlib.Path(args.patch).read_text() if args.patch else None
    name = body_path.name.removesuffix(".html")
    rep = render(body_path.read_text(), pathlib.Path(args.out), name, sizes, patch)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
