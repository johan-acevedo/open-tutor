"""Render the nine example screens (+patches) with a given shell, dump lint issues.

Usage: python screen/tools/check_examples.py <shell-dir-or-empty-for-current> <out-json>
"""
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server"))
sys.path.insert(0, str(REPO))
from playwright.sync_api import sync_playwright
from screen.tools import screenkit

SIZES = ((370, 610), (840, 743))


def main():
    shell = pathlib.Path(sys.argv[1]) if sys.argv[1] else None
    out = pathlib.Path(sys.argv[2])
    bodies = sorted((REPO / "screen" / "examples").glob("*.html"))
    bodies = [b for b in bodies if not b.name.endswith(".patch.html")]
    report = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for body_path in bodies:
            name = body_path.name.removesuffix(".html")
            pp = body_path.with_name(name + ".patch.html")
            doc = screenkit.compose(body_path.read_text(), shell=shell)
            row = {}
            for (w, h) in SIZES:
                key = f"{w}x{h}"
                page = browser.new_page(viewport={"width": w, "height": h})
                page.set_content(screenkit.host_page(doc))
                frame = page.frames[1] if len(page.frames) > 1 else page.main_frame
                try:
                    frame.wait_for_function("() => document.documentElement.dataset.otReady === '1'", timeout=30000)
                except Exception as e:
                    row[key] = {"error": f"not-ready: {e}"}
                    page.close()
                    continue
                info = frame.evaluate("() => ({fontPx: ot.fontPx, issues: ot.issues})")
                entry = {"fontPx": info["fontPx"], "issues": info["issues"]}
                if pp.exists():
                    patch_issues = frame.evaluate("(p) => ot.patch(p)", pp.read_text())
                    page.wait_for_timeout(2800)
                    entry["patch_issues"] = patch_issues
                    entry["fontPx_after"] = frame.evaluate("() => ot.fontPx")
                row[key] = entry
                page.close()
            report[name] = row
            print(name, json.dumps(row, ensure_ascii=False)[:400], flush=True)
        browser.close()
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print("wrote", out)


main()
