"""Check visual fitting and resizing in Chromium, without model calls.

uv run --project server python screen/tools/check_fit.py --out /tmp/fit-check
Use --shell DIR for an exported previous shell, --case mindmap for the short regression.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

import screenkit

ROOT = Path(__file__).resolve().parents[1]
SIZES = ((603, 743), (370, 610), (1000, 700))
MINDMAP = (ROOT / "tests/fit/mindmap.html").read_text()
CASES = {
    "mindmap": MINDMAP,
    "cycle": MINDMAP.replace("ot-mindmap", "ot-cycle").replace("ot-node", "ot-item"),
    "graph": '<h1>En linje</h1><ot-graph x="-1 5" y="-1 7"><ot-fn>2x+1</ot-fn></ot-graph>',
    "map": '<h1>Sverige</h1><ot-map view="sverige"><ot-country name="Sweden"></ot-country></ot-map>',
    "chart": '<h1>En undersökning</h1><ot-chart type="bar"><table><tr><th>Val</th><th>Antal</th></tr><tr><td>A</td><td>4</td></tr><tr><td>B</td><td>7</td></tr></table></ot-chart>',
    "image": '<h1>En färgruta</h1><ot-image src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII=" credit="Syntetisk testbild" alt="En ruta"></ot-image>',
    "clock": '<h1>Visarna</h1><ot-clock time="7:45" minutes></ot-clock>',
    "balance": '<h1>Jämvikt</h1><ot-balance left="3x+5" right="20"></ot-balance>',
    "numberline": '<h1>Tallinjen</h1><ot-numberline from="0" to="1" step="1/12"><ot-mark at="3/4">Tre fjärdedelar</ot-mark></ot-numberline>',
    "fraction": '<h1>Delar av en hel</h1><ot-fraction value="3/4" shape="circle"></ot-fraction>',
}
METRICS = """() => {
  const page = document.getElementById('page');
  const scale = page.getBoundingClientRect().width / page.offsetWidth;
  const boxes = [...document.querySelectorAll('.ot-node-box')].map(b => b.getBoundingClientRect());
  return {font:ot.fontPx, effective:ot.fontPx*scale, transform:page.style.transform,
    issues:ot.issues, pageHeight:page.scrollHeight,
    boxes:boxes.map(b=>({left:b.left,top:b.top,right:b.right,bottom:b.bottom})),
    nodesVisible:boxes.length && boxes.every(b=>b.width>0 && b.height>0 && b.top>=0 && b.bottom<=innerHeight+1)};
}"""


def run(args):
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    results, failures = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for name, body in CASES.items():
                if args.case and name != args.case:
                    continue
                page = browser.new_page(viewport={"width": SIZES[0][0], "height": SIZES[0][1]}, reduced_motion="reduce")
                try:
                    page.set_content(screenkit.host_page(screenkit.compose(body, args.shell)))
                    frame = screenkit._frame(page)
                    frame.wait_for_function("document.documentElement.dataset.otReady==='1'")
                    # Refit wide -> phone too: old pixel positions may not size the next fit.
                    for index, (w, h) in enumerate((*SIZES, SIZES[1])):
                        if index:
                            page.set_viewport_size({"width": w, "height": h})
                            frame.evaluate("() => {ot.issues.length=0;window.dispatchEvent(new Event('resize'));}")
                            page.wait_for_timeout(300)  # shell debounces resize for 120 ms
                        info = frame.evaluate(METRICS)
                        entry = {"case": name, "pane": [w, h], "resize": index > 0, **info}
                        results.append(entry)
                        label = f"{name}-{w}x{h}{'-resized' if index == 3 else ''}"
                        if name in {"mindmap", "cycle"}:
                            page.screenshot(path=str(out / f"{label}.png"))
                        bad = [i for i in info["issues"] if i["kind"] in {"overflow", "dense", "draw", "crowded"}]
                        if bad or info["effective"] < 16 or (name in {"mindmap", "cycle"} and not info["nodesVisible"]):
                            failures.append({"case": label, "font": info["effective"], "issues": bad,
                                             "nodesVisible": info["nodesVisible"]})
                        print(json.dumps({"case": label, "font": round(info["effective"], 2), "issues": info["issues"]}, ensure_ascii=False), flush=True)
                finally:
                    page.close()
        finally:
            browser.close()
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    assert not failures, failures
    print("Fit checks passed: readable visual content, no false overflow, portrait/wide resize.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell", type=Path, default=screenkit.SHELL)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case", choices=CASES)
    run(parser.parse_args())
