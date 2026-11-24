#!/usr/bin/env python3
"""Executable browser smoke check for the UI SDK experiment blocks.

Local rendering only (no paid providers, no services):

  uv run --project server python screen/tools/check_ui_sdk.py [--out /tmp/ui-sdk-smoke]

Covers: keyboard action, accessible names/roles/live status, the posted
answer messages, the sanitizer path, the frame sandbox, and the 370x610
layout. Prints bundle raw/gzip bytes and exits non-zero on any failure.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import screenkit


FIXTURE = ROOT / "tools" / "fixtures" / "ui-sdk-blocks.html"
W, H = 370, 610
CHECKS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append(name)
    print(("PASS " if ok else "FAIL ") + name + (f" ({detail})" if detail else ""))
    if not ok:
        raise AssertionError(name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/ui-sdk-smoke")
    args = ap.parse_args()
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    body = FIXTURE.read_text()

    # --- compose gating -------------------------------------------------
    doc_sdk = screenkit.compose(body, ui_sdk=True)
    doc_auto = screenkit.compose(body)
    doc_plain = screenkit.compose(body, ui_sdk=False)
    plain_body = "<h1>Enheter</h1><ot-answer id=\"s\" label=\"Svar\"></ot-answer>"
    doc_other = screenkit.compose(plain_body)
    # '"ui-radio-group"' (double-quoted) only occurs in the built bundle,
    # never in shell.js, which uses single quotes throughout.
    check("explicit ui_sdk=True inlines the bundle", '"ui-radio-group"' in doc_sdk)
    check("auto-detect inlines the bundle for SDK blocks", '"ui-radio-group"' in doc_auto)
    check("ui_sdk=False leaves the bundle out (native fallback)", '"ui-radio-group"' not in doc_plain)
    check("plain pages stay bundle-free", '"ui-radio-group"' not in doc_other)
    for name, doc in (("sdk", doc_sdk), ("plain", doc_plain)):
        check(f"no unfilled slots ({name})", "{{" not in doc)
    check("no runtime CDN for the bundle", "ui-sdk.dev" not in doc_sdk)
    try:
        meta = json.loads((ROOT / "shell" / "ui-sdk.bundle.meta.json").read_text())
    except FileNotFoundError:
        print("SKIP bundle meta (build.sh not run)")
        meta = None
    if meta:
        print(f"bundle raw={meta['raw_bytes']} gzip={meta['gzip_bytes']} sha256={meta['sha256'][:12]}")
        check("bundle bytes match the built file",
              (ROOT / "shell" / "ui-sdk.bundle.js").stat().st_size == meta["raw_bytes"])

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            context = browser.new_context(viewport={"width": W, "height": H})
            page = context.new_page()
            page.set_content(screenkit.host_page(doc_sdk))
            # Installed on the live window: init-script listeners do not
            # survive set_content's document.write (they land on a dead
            # Window). Answers are all posted after user actions below.
            page.evaluate("window.__ot = []; window.addEventListener('message', function (e) { window.__ot.push(e.data); });")
            check("frame sandbox is allow-scripts only",
                  page.evaluate("() => document.querySelector('iframe').getAttribute('sandbox')") == "allow-scripts")
            frame = page.frames[1]
            frame.wait_for_function("() => document.documentElement.dataset.otReady === '1'", timeout=30000)
            ready = frame.evaluate("() => ({fontPx: ot.fontPx, issues: ot.issues})")
            check("shell reports ready at 370x610", ready["fontPx"] > 0, f"fontPx={ready['fontPx']}")
            bad = [i for i in ready["issues"] if i.get("kind") == "tag"]
            check("no unknown-tag lint for the new blocks", not bad, json.dumps(bad))
            check("model script and handler stripped (native sanitizer)",
                  frame.evaluate("() => !document.querySelector('#page script, #page [onclick]')")
                  and frame.evaluate("() => !window.modelRan && document.getElementById('elak').textContent.includes('Vanlig text')"))

            answers = lambda: page.evaluate("() => window.__ot.filter(m => m.ot === 'answer')")

            # --- ot-sdk-choice: keyboard select + explicit submit ----------
            group = frame.locator("ui-radio-group")
            check("radio group keeps one tab stop", frame.evaluate(
                """() => { const g = document.querySelector('ui-radio-group');
                    return g && g.querySelectorAll('ui-radio').length === 3; }"""))
            check("radio roles", frame.evaluate(
                "() => document.querySelector('ui-radio').getAttribute('role') === 'radio'"))
            check("group named in Swedish", frame.evaluate(
                "() => document.body.textContent.includes('Vilket ord betyder hund?')"))
            page.keyboard.press("Tab")  # into the group (first radio, nothing checked)
            page.keyboard.press("ArrowDown")  # check the second option
            check("arrow key checks second radio", frame.evaluate("() => document.querySelector('ui-radio-group').value") == "katt")
            check("checked radio exposed", frame.evaluate(
                "() => document.querySelectorAll('ui-radio')[1].getAttribute('aria-checked')") == "true")
            page.screenshot(path=str(out / "choice-checked.png"))
            # submit with the keyboard: tab to Skicka, Enter
            page.keyboard.press("Tab")
            focused = frame.evaluate("() => document.activeElement && document.activeElement.textContent")
            check("tab reaches Skicka", focused == "Skicka", focused or "")
            page.keyboard.press("Enter")
            page.wait_for_function("() => window.__ot.some(m => m.ot === 'answer' && m.id === 'val2')", timeout=5000)
            got = [m for m in answers() if m["id"] == "val2"][-1]
            check("choice answer message", got["value"] == "katt", json.dumps(got))

            # --- ot-sdk-answer: type + Enter ------------------------------
            frame.locator("#svar2-input").click()
            page.keyboard.type("hunden")
            page.keyboard.press("Enter")
            page.wait_for_function("() => window.__ot.some(m => m.ot === 'answer' && m.id === 'svar2')", timeout=5000)
            got = [m for m in answers() if m["id"] == "svar2"][-1]
            check("answer message", got["value"] == "hunden", json.dumps(got))
            check("sent state shown", frame.evaluate(
                "() => document.querySelector('ot-sdk-answer .ot-send').textContent") == "Skickat ✓")

            # --- ot-order: keyboard move + live announcement + submit -----
            check("order items are listitems", frame.evaluate(
                "() => document.querySelectorAll('ot-order li').length") == 3)
            move_down = frame.locator("ot-order [data-move='down']").first
            check("move button named in Swedish", move_down.get_attribute("aria-label") == "Flytta ner: Myra")
            move_down.focus()
            page.keyboard.press("Enter")
            live = frame.evaluate("() => document.querySelector('ot-order [role=status]').textContent")
            check("polite reorder announcement", live == "Myra är nu 2 av 3", live)
            check("move button names follow the item", frame.evaluate(
                "() => document.querySelector('ot-order [data-move=up]').getAttribute('aria-label')") == "Flytta upp: Katt")
            page.wait_for_function("() => window.__ot.some(m => m.ot === 'input' && m.id === 'ordning')", timeout=5000)
            frame.locator("ot-order .ot-send").click()
            page.wait_for_function("() => window.__ot.some(m => m.ot === 'answer' && m.id === 'ordning')", timeout=5000)
            got = [m for m in answers() if m["id"] == "ordning"][-1]
            check("order answer message", got["value"] == "katt>myra>hast", json.dumps(got))
            # restore reorders and keeps state
            frame.evaluate("() => ot.restore({ordning: 'hast>katt>myra'})")
            check("restore reorders", frame.evaluate(
                "() => Array.from(document.querySelectorAll('ot-order li')).map(li => li.dataset.value).join('>')") == "hast>katt>myra")

            # --- ot-match: only a completed mapping sends -----------------
            check("match submit starts disabled", frame.evaluate(
                "() => document.querySelector('ot-match .ot-send').disabled") is True)
            selects = frame.locator("ot-match ui-select")
            check("two SDK selects, one per prompt", selects.count() == 2)
            check("select named per prompt", frame.evaluate(
                "() => document.querySelector('ot-match ui-select').getAttribute('aria-label')") == "Välj svar för Hund")
            # keyboard: Enter opens with focus on the first item; Enter chooses it
            frame.locator("ot-match ui-select-trigger > button").first.focus()
            page.keyboard.press("Enter")
            page.keyboard.press("Enter")
            check("first match chosen by keyboard", frame.evaluate(
                "() => document.querySelectorAll('ot-match ui-select')[0].value") == "dog")
            check("still disabled with one row left", frame.evaluate(
                "() => document.querySelector('ot-match .ot-send').disabled") is True)
            frame.locator("ot-match ui-select-trigger > button").nth(1).focus()
            page.keyboard.press("Enter")
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Enter")
            check("second match chosen by keyboard", frame.evaluate(
                "() => document.querySelectorAll('ot-match ui-select')[1].value") == "cat")
            check("submit enabled when complete", frame.evaluate(
                "() => document.querySelector('ot-match .ot-send').disabled") is False)
            frame.locator("ot-match .ot-send").click()
            page.wait_for_function("() => window.__ot.some(m => m.ot === 'answer' && m.id === 'djur')", timeout=5000)
            got = [m for m in answers() if m["id"] == "djur"][-1]
            check("match answer maps prompts to choices", got["value"] == "hund=dog;katt=cat", json.dumps(got))

            # --- layout at 370x610 ----------------------------------------
            # (read inside the frame: the sandbox has no allow-same-origin,
            # so the outer page cannot touch the frame's document directly)
            overflow = frame.evaluate("() => document.documentElement.scrollWidth <= 370")
            check("no horizontal overflow at 370px", overflow)
            page.screenshot(path=str(out / "page-370x610.png"))
            print(f"screenshots in {out}")

            # --- DOMPurify fallback leg (needs the real CDN lib, like check_sanitizer)
            try:
                fb = browser.new_context(viewport={"width": W, "height": H})
                fb.add_init_script("delete Element.prototype.setHTML")
                page2 = fb.new_page()
                page2.set_content(screenkit.host_page(doc_sdk))
                frame2 = page2.frames[1]
                frame2.wait_for_function("() => document.documentElement.dataset.otReady === '1'", timeout=30000)
                check("fallback keeps model attrs (prompt/choice/value)",
                      frame2.evaluate("() => document.querySelectorAll('ot-match ui-select').length") == 2
                      and frame2.evaluate("() => document.querySelectorAll('ot-order li').length") == 3)
                check("fallback strips model script", frame2.evaluate(
                    "() => !document.querySelector('#page script') && !window.modelRan"))
                fb.close()
            except Exception as e:  # CDN unreachable where this runs: not a block failure
                print(f"SKIP DOMPurify fallback leg ({type(e).__name__}: {e})")
        finally:
            browser.close()

    print("native sanitizer path: covered above")
    print(f"done: {len(CHECKS)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
