"""Check reading order and lint in the real shell, without provider calls.

Run from the repo root:
  uv run --project server python screen/tools/check_readability.py
The two lesson bodies are unedited DeepSeek V4.1 Flash outputs, 2026-11-13.
"""

from __future__ import annotations

import pathlib

from playwright.sync_api import sync_playwright

import screenkit


def check(browser, body: str, size: tuple[int, int], inspect) -> None:
    page = browser.new_page(viewport={"width": size[0], "height": size[1]})
    try:
        page.set_content(screenkit.host_page(screenkit.compose(body)))
        page.wait_for_function("() => frames.length === 1")
        frame = page.frames[1]
        frame.wait_for_function("() => document.documentElement.dataset.otReady === '1'")
        inspect(frame)
    finally:
        page.close()


def main() -> None:
    fixtures = pathlib.Path(__file__).resolve().parents[1] / "tests" / "readability"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            def single_column(frame):
                pairs = frame.evaluate("""() => [...document.querySelectorAll('.row,.grid')].map(row =>
                  [...row.children].map(child => {
                    const r = child.getBoundingClientRect();
                    return {left:r.left, top:r.top, bottom:r.bottom, width:r.width};
                  }))""")
                for first, second in pairs:
                    assert abs(first["left"] - second["left"]) < 1, pairs
                    assert second["top"] >= first["bottom"], pairs
                    assert first["width"] > 250, pairs

            body = '<h1>En sak i taget</h1>' + "".join(
                f'<div class="{kind}"><p>Först läser du frågan.</p><p>Sedan räknar du själv.</p></div>'
                for kind in ("row", "row keep", "grid")
            )
            # Width matters even when the pane is short enough to be landscape.
            check(browser, body, (370, 300), single_column)

            def small_text_warns(frame):
                info = frame.evaluate("() => ({font:ot.fontPx, issues:ot.issues})")
                assert 14 <= info["font"] < 16, info
                assert any(i["kind"] == "dense" for i in info["issues"]), info

            check(browser, (fixtures / "line.html").read_text(), (370, 610), small_text_warns)

            def dense_page_warns(frame):
                info = frame.evaluate("() => ({font:ot.fontPx, issues:ot.issues})")
                assert info["font"] < 14, info
                assert any(i["kind"] == "dense" for i in info["issues"]), info

            check(browser, (fixtures / "fractions-dense.html").read_text(), (370, 610), dense_page_warns)

            def title_warns(frame):
                issues = frame.evaluate("() => ot.issues")
                assert any(i["kind"] == "heading" for i in issues), issues

            check(browser, '<h1>Undersök hur sambandet mellan linjens lutning och skärningen med axeln fungerar</h1><p>En fråga.</p>', (370, 610), title_warns)
        finally:
            browser.close()
    print("Readability checks passed: narrow reading order, 16px warning, dense page and long title.")


if __name__ == "__main__":
    main()
