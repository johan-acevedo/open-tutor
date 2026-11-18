"""Check the served companion review with real assets, frame themes and answers.

uv run --project server python scripts/check_band_design.py --url URL
The review has fictional content and uses no voice or model providers.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8796")
    args = parser.parse_args()
    out = ROOT / "design" / "bands" / "verification"
    out.mkdir(exist_ok=True)
    report = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for band in ("primary", "middle", "upper"):
            for width, height in ((1366, 768), (390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height}, reduced_motion="reduce")
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"{args.url}/band-review.html?band={band}")
                page.locator(".ot-bcard-page.is-ready").wait_for(timeout=45000)
                for pose in ("greeting", "listening", "speaking", "thinking", "working", "waiting", "pointing"):
                    page.get_by_role("button", name=pose, exact=True).click()
                    page.wait_for_function("() => {const i=document.querySelector('.ot-avatar-img');return i && i.complete && i.naturalWidth>0}")
                    src = page.locator(".ot-avatar-img").get_attribute("src")
                    expected = f"/character/{'' if band == 'primary' else band + '/'}{pose}.webp"
                    assert src == expected, (src, expected)
                    assert bool(page.locator(".ot-bars").count()) == (pose in ("speaking", "pointing"))
                frame = page.frames[1]
                colours = page.locator(".ot-root").evaluate("e=>({background:getComputedStyle(e).backgroundColor,text:getComputedStyle(e).color,font:getComputedStyle(e).fontFamily})")
                frame_colours = frame.evaluate("()=>({background:getComputedStyle(document.body).backgroundColor,text:getComputedStyle(document.body).color})")
                assert colours["background"] == frame_colours["background"], (band, colours, frame_colours)
                frame.get_by_role("textbox").fill("meter")
                frame.get_by_role("textbox").press("Enter")
                page.locator("output").filter(has_text="meter").wait_for()
                assert not errors, errors
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                name = f"{band}-{width}x{height}"
                page.screenshot(path=str(out / f"{name}.png"))
                report.append({"view": name, "poses": 7, "colours": colours, "frame": frame_colours, "answer": "received", "errors": errors})
                page.close()
        browser.close()
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Verified {len(report)} served views, all poses, matching frame themes, and answer events.")


if __name__ == "__main__":
    main()
