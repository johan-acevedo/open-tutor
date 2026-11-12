"""Build the Smart Screen gallery into screen/gallery/site/.

  uv run --project server python screen/gallery/build.py [--no-shots]

Writes site/index.html (from template.html), site/frames/<name>.html (the composed
page exactly as the frame gets it), site/data.json and, unless --no-shots,
screenshots of every example, test page and small-model page.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))
import screenkit  # noqa: E402

SITE = HERE / "site"


def collect():
    groups = []
    ex = json.loads((ROOT / "examples" / "index.json").read_text())
    groups.append({"key": "examples", "title": "Example screens", "items": [
        {**e, "dir": "examples"} for e in ex]})
    tests = sorted(p.stem for p in (ROOT / "tests").glob("t-*.html"))
    groups.append({"key": "tests", "title": "Component test pages", "items": [
        {"name": t, "title": t.removeprefix("t-").capitalize(), "dir": "tests"} for t in tests]})
    small = ROOT / "smalltest" / "out"
    reqs = {r["id"]: r for r in json.loads((ROOT / "smalltest" / "requests.json").read_text())}
    results = json.loads((small / "results.json").read_text()) if (small / "results.json").exists() else {}
    for model in ("muse", "deepseek"):
        d = small / model
        if not d.exists():
            continue
        items = []
        for p in sorted(d.glob("*.html")):
            if p.name.endswith(".patch.html"):
                continue
            r = reqs.get(p.stem, {})
            items.append({"name": p.stem, "title": p.stem, "dir": f"smalltest/out/{model}",
                          "request": r.get("request", ""), "patch_request": r.get("patch", ""),
                          "grade": r.get("child", ""), "timing": find_timing(results, model, p.stem)})
        groups.append({"key": model, "title": f"Small-model test: {model}", "items": items})
    return groups


def find_timing(results, model, case):
    try:
        m = results.get(model) if isinstance(results, dict) else None
        if isinstance(m, dict):
            return m.get(case)
        if isinstance(m, list):
            return next((c for c in m if c.get("id") == case), None)
    except Exception:
        return None
    return None


def main() -> int:
    shots = "--no-shots" not in sys.argv
    SITE.mkdir(exist_ok=True)
    (SITE / "frames").mkdir(exist_ok=True)
    (SITE / "shots").mkdir(exist_ok=True)
    groups = collect()
    reports = {}
    browser = pw = None
    if shots:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
    for g in groups:
        for it in g["items"]:
            src = ROOT / it["dir"] / f"{it['name']}.html"
            patch_p = ROOT / it["dir"] / f"{it['name']}.patch.html"
            body = src.read_text()
            patch = patch_p.read_text() if patch_p.exists() else ""
            key = f"{g['key']}-{it['name']}"
            it["key"] = key
            it["body"] = body
            it["patch"] = patch
            (SITE / "frames" / f"{key}.html").write_text(screenkit.compose(body))
            if shots:
                rep = screenkit.render(body, SITE / "shots", key, patch=patch or None, browser=browser)
                reports[key] = rep
                print(key, {k: (v["ready_ms"], v["fontPx"], len(v["issues"]), len(v.get("patch_issues", []))) for k, v in rep["sizes"].items()})
    if browser:
        browser.close()
        pw.stop()
    old = json.loads((SITE / "data.json").read_text()) if (SITE / "data.json").exists() else {}
    for g in groups:
        for it in g["items"]:
            it["report"] = reports.get(it["key"]) or (old.get("reports", {}) or {}).get(it["key"])
    data = {"groups": groups, "reports": {it["key"]: it["report"] for g in groups for it in g["items"]}}
    (SITE / "data.json").write_text(json.dumps(data, ensure_ascii=False))
    shutil.copy(HERE / "template.html", SITE / "index.html")
    for extra in ("REFERENCE.md", "NOTES.md"):
        if (ROOT / extra).exists():
            shutil.copy(ROOT / extra, SITE / extra)
    print("built", SITE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
