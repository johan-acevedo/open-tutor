"""Check the screen's loading overlay in the real shell, without provider calls.

The fox dims the finished page and shows "Laddar <ämne>…" at once while the
next page is prepared (board.loading -> {ot:'loading', topic}). Verifies the
veil appears with the Swedish label, that the topic travels as text (never
HTML), that clearing removes it, and that a successful patch clears it too.
Screenshots go to --out for the review notes.

Run from the repo root:
  uv run --project server python screen/tools/check_loading.py --out /tmp/loading
"""

from __future__ import annotations

import argparse
import pathlib

from playwright.sync_api import sync_playwright

import screenkit


def check(browser, body: str, size: tuple[int, int], out: pathlib.Path, tag: str) -> None:
    page = browser.new_page(viewport={"width": size[0], "height": size[1]})
    try:
        page.set_content(screenkit.host_page(screenkit.compose(body)))
        page.wait_for_function("() => frames.length === 1")
        frame = page.frames[1]
        frame.wait_for_function("() => document.documentElement.dataset.otReady === '1'")
        assert frame.evaluate("() => !!document.getElementById('ot-loading')") is False

        frame.evaluate("(t) => ot.loading(t)", "historia")
        label = frame.evaluate(
            "() => document.querySelector('#ot-loading .ot-loading-label').textContent")
        assert label == "Laddar historia …", label
        assert frame.evaluate(
            "() => document.querySelectorAll('#ot-loading *').length") == 3
        page.screenshot(path=str(out / f"{tag}-loading-{size[0]}x{size[1]}.png"))

        # The topic is text: markup in it must not become elements.
        frame.evaluate("(t) => ot.loading(t)", '<img src=x onerror=window.evil=1>')
        assert frame.evaluate(
            "() => document.querySelectorAll('#ot-loading img').length") == 0
        text = frame.evaluate(
            "() => document.querySelector('#ot-loading .ot-loading-label').textContent")
        assert text.startswith("Laddar <img"), text
        assert frame.evaluate("() => window.evil") is None

        frame.evaluate("() => ot.loading(null)")
        assert frame.evaluate("() => !!document.getElementById('ot-loading')") is False

        # A successful patch clears a stale veil by itself.
        frame.evaluate("(t) => ot.loading(t)", "historia")
        frame.evaluate("""() => ot.patch(
            '<ot-patch target=\"rubrik\" do=\"text\">Klockan halv sju</ot-patch>')""")
        page.wait_for_timeout(500)
        assert frame.evaluate("() => !!document.getElementById('ot-loading')") is False
        page.screenshot(path=str(out / f"{tag}-cleared-{size[0]}x{size[1]}.png"))
    finally:
        page.close()


def pending_shot(browser, body: str, out: pathlib.Path) -> None:
    """An unresolved image slot renders a loading picture placeholder."""
    page = browser.new_page(viewport={"width": 1000, "height": 700})
    try:
        page.set_content(screenkit.host_page(screenkit.compose(body)))
        page.wait_for_function("() => frames.length === 1")
        frame = page.frames[1]
        frame.wait_for_function("() => document.documentElement.dataset.otReady === '1'")
        label = frame.evaluate(
            "() => document.querySelector('ot-image .ot-img-pending').textContent")
        assert "Laddar bild" in label, label
        assert frame.evaluate("() => document.querySelectorAll('ot-image img').length") == 0
        page.screenshot(path=str(out / "pending-placeholder-1000x700.png"))
    finally:
        page.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/screen-loading")
    args = parser.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    root = pathlib.Path(__file__).resolve().parents[1]
    body = (root / "examples" / "klockan.html").read_text()
    body = body.replace("<h1>", '<h1 id="rubrik">', 1)
    pending = ('<h1>Romarriket</h1><p>Forum Romanum, hjärtat i antikens Rom.</p>'
               '<ot-image id="forum" query="Forum Romanum" alt="Forum">'
               '<ot-label at="20,30">templen</ot-label>'
               '<ot-label at="70,60">triumfbågarna</ot-label></ot-image>')
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            check(browser, body, (370, 610), out, "klockan")
            check(browser, body, (1000, 700), out, "klockan")
            pending_shot(browser, pending, out)
        finally:
            browser.close()
    print(f"screenshots in {out}")


if __name__ == "__main__":
    main()
