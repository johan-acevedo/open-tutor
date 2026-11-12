"""Smart Screen end-to-end probe (test sub-agent).

Opens the dev web app in headless Chromium, starts a session as a fictional
learner, plays a short fictional fractions lesson through the typed chat
input, and records when the screen becomes visible / patches / answers.

Run from the repo root (dev services must already run):
    uv run --project server python server/scripts/smart_screen_e2e.py
    uv run --project server python server/scripts/smart_screen_e2e.py --url http://127.0.0.1:8711/

Screenshots + timeline.json go to --shots-dir (default /tmp/smart-screen-e2e).
Never touches production; fictional content only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

LEARNER_NAME = "Testbarn"
LEARNER_GRADE = 5  # årskurs 5

LINES = {
    "a": "Hej! Jag ska räkna 3/4 + 1/8 men jag fattar inte. Kan du visa på skärmen?",
    "b": "Okej, så 3/4 är samma som 6/8?",
    "c": "Kan du lägga till svaret på skärmen?",
    "box": "Kan du lägga till en svarsruta så jag kan skriva svaret själv?",
    "point": "Kan du peka på svaret?",
}

CHAT_INPUT = ".ot-chat-input"
BOARD_EMPTY = ".ot-board-empty"
PAGE_ARTICLE = "article.ot-bcard-page[data-board-id]"
BOOK_POS = ".ot-book-pos"
CAPTION = ".ot-caption"
END_BTN = 'button[aria-label="Avsluta sessionen"]'
ENDCARD = ".ot-endcard"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


async def shot(page, path: Path, label: str, timeline: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(path))
    timeline.append({"t": now_iso(), "event": "screenshot", "label": label, "path": str(path)})
    print(f"[shot] {label} -> {path}", flush=True)


async def visible_page_id(page) -> str | None:
    try:
        return await page.evaluate(
            """() => {
            const arts = [...document.querySelectorAll('article.ot-bcard-page[data-board-id]')];
            for (const a of arts) {
              const slot = a.closest('[hidden]');
              if (!slot) return a.getAttribute('data-board-id');
            }
            return null;
          }"""
        )
    except Exception:
        return None


async def page_ids(page) -> list[str]:
    try:
        return await page.evaluate(
            """() => [...document.querySelectorAll('article.ot-bcard-page[data-board-id]')]
               .map(a => a.getAttribute('data-board-id'))"""
        )
    except Exception:
        return []


async def page_ready(page, page_id: str) -> bool:
    try:
        return await page.evaluate(
            """(id) => {
            const a = document.querySelector(`article.ot-bcard-page[data-board-id="${id}"]`);
            return !!(a && a.classList.contains('is-ready'));
          }""",
            page_id,
        )
    except Exception:
        return False


async def caption_text(page) -> str:
    try:
        el = await page.query_selector(CAPTION)
        if not el:
            return ""
        return (await el.inner_text() or "").strip()
    except Exception:
        return ""


async def frame_inner_text(page, page_id: str) -> dict:
    """Read the page body from inside its frame via CDP (parent JS is opaque
    because the frame is sandboxed, so contentDocument is not accessible)."""
    try:
        for frame in page.frames:
            try:
                url = frame.url or ""
            except Exception:
                url = ""
            # srcdoc frames have an about:srcdoc URL; try each child frame.
            if frame == page.main_frame:
                continue
            try:
                info = await frame.evaluate(
                    """() => ({
                    len: document.body ? document.body.innerHTML.length : 0,
                    hasH1: !!document.querySelector('h1'),
                    hasAnswer: !!(document.querySelector('ot-answer')
                      || document.querySelector('ot-choice')
                      || document.querySelector('ot-gap')),
                    rawTags: ((document.body.innerHTML||'').match(/&lt;|<ot-patch/)||[]).length,
                    text: (document.body.innerText||'').slice(0,300)
                  })"""
                )
                if info and info.get("len", 0) > 200:
                    return {"ok": True, "frame_url": url[:80], **info}
            except Exception:
                continue
        return {"ok": False, "why": "no frame with body found"}
    except Exception as e:
        return {"ok": False, "why": f"{type(e).__name__}: {e}"}


async def has_answer_box(page, page_id: str) -> bool:
    try:
        frame_loc = page.frame_locator(
            f'article.ot-bcard-page[data-board-id="{page_id}"] >> iframe.ot-page-frame')
        for sel in ("ot-answer input", "ot-choice button", "ot-gap input"):
            try:
                if await frame_loc.locator(sel).count() > 0:
                    return True
            except Exception:
                pass
        return False
    except Exception:
        return False


async def wait_for(fn, timeout_s: float, poll_s: float = 0.5):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        try:
            v = await fn()
            if v:
                return v
        except Exception:
            pass
        await asyncio.sleep(poll_s)
    return None


async def send_chat(page, text: str, timeline: list) -> None:
    box = page.locator(CHAT_INPUT)
    await box.wait_for(state="visible", timeout=30000)
    await box.fill(text)
    t_send = now_iso()
    await box.press("Enter")
    timeline.append({"t": t_send, "event": "chat_sent", "text": text})
    print(f"[chat] sent: {text[:80]}", flush=True)
    # The app shows a "Du: ..." chip for ~4 s after a successful send.
    try:
        await page.locator(".ot-sent-chip").wait_for(state="visible", timeout=8000)
    except Exception:
        print("[warn] no sent-chip confirmation", flush=True)


async def ensure_started(page, timeline: list) -> None:
    """On the profiles screen: pick Testbarn or create it, then press Starta."""
    await page.locator(".ot-profiles").wait_for(state="visible", timeout=30000)
    # Existing profile card with the name?
    card = page.locator(".ot-profile-card", has_text=LEARNER_NAME)
    if await card.count() > 0:
        print("[profiles] picking existing Testbarn", flush=True)
        await card.first.click()
    else:
        print("[profiles] creating Testbarn", flush=True)
        # "Ny här?" card toggles the new-profile fields.
        new_here = page.locator(".ot-profile-card", has_text="Ny här?")
        if await new_here.count() > 0:
            await new_here.first.click()
        name_field = page.locator('input[aria-label="Förnamn"]')
        await name_field.wait_for(state="visible", timeout=10000)
        await name_field.fill(LEARNER_NAME)
        grade_sel = page.locator('select[aria-label="Årskurs"]')
        await grade_sel.select_option(str(LEARNER_GRADE))
    start_btn = page.locator(".ot-start-btn", has_text="Starta")
    await start_btn.wait_for(state="visible", timeout=10000)
    await start_btn.click()
    timeline.append({"t": now_iso(), "event": "start_clicked"})


async def answer_in_page(page, page_id: str, timeline: list) -> bool:
    """If the visible page holds an answer box, answer inside its frame.

    Returns True when an answer was submitted.
    """
    frame_loc = page.frame_locator(f'article.ot-bcard-page[data-board-id="{page_id}"] >> iframe.ot-page-frame')
    # ot-answer: text input + Skicka button. Fractions answer: 7/8.
    try:
        answer_input = frame_loc.locator("ot-answer input")
        if await answer_input.count() > 0:
            inp = answer_input.first
            await inp.wait_for(state="visible", timeout=8000)
            await inp.fill("7/8")
            timeline.append({"t": now_iso(), "event": "page_answer_typed",
                             "page": page_id, "part": "ot-answer", "value": "7/8"})
            btn = frame_loc.locator("ot-answer button")
            if await btn.count() > 0:
                await btn.first.click()
            else:
                await inp.press("Enter")
            timeline.append({"t": now_iso(), "event": "page_answer_sent",
                             "page": page_id, "value": "7/8"})
            print("[answer] submitted 7/8 in ot-answer", flush=True)
            return True
    except Exception as e:
        print(f"[answer] ot-answer attempt failed: {type(e).__name__}: {e}", flush=True)
    # ot-choice: click the first button.
    try:
        choice_btns = frame_loc.locator("ot-choice button")
        if await choice_btns.count() > 0:
            await choice_btns.first.wait_for(state="visible", timeout=5000)
            label = (await choice_btns.first.inner_text() or "").strip()[:60]
            await choice_btns.first.click()
            timeline.append({"t": now_iso(), "event": "page_answer_sent",
                             "page": page_id, "kind": "choice", "value": label})
            print(f"[answer] clicked choice: {label}", flush=True)
            return True
    except Exception as e:
        print(f"[answer] ot-choice attempt failed: {type(e).__name__}: {e}", flush=True)
    # ot-gap: fill the gap input (change event sends it).
    try:
        gap_input = frame_loc.locator("ot-gap input")
        if await gap_input.count() > 0:
            await gap_input.first.wait_for(state="visible", timeout=5000)
            await gap_input.first.fill("7/8")
            await gap_input.first.press("Enter")
            # change fires on blur; click elsewhere to be sure.
            await frame_loc.locator("ot-gap").first.click()
            timeline.append({"t": now_iso(), "event": "page_answer_sent",
                             "page": page_id, "kind": "gap", "value": "7/8"})
            print("[answer] filled ot-gap with 7/8", flush=True)
            return True
    except Exception as e:
        print(f"[answer] ot-gap attempt failed: {type(e).__name__}: {e}", flush=True)
    print("[answer] no answer box found on page", flush=True)
    timeline.append({"t": now_iso(), "event": "page_answer_none", "page": page_id})
    return False


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://dell5500.tail2e1c4e.ts.net:9444/",
                    help="dev web URL")
    ap.add_argument("--shots-dir", default="/tmp/smart-screen-e2e")
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--no-headless", dest="headless", action="store_false")
    args = ap.parse_args()

    from playwright.async_api import async_playwright

    shots = Path(args.shots_dir)
    shots.mkdir(parents=True, exist_ok=True)
    timeline: list[dict] = []
    console_errors: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=args.headless,
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            ignore_https_errors=True,
            permissions=["microphone", "camera"],
        )
        page = await ctx.new_page()
        page.on("console", lambda m: console_errors.append(
            {"t": now_iso(), "type": m.type, "text": m.text[:500]})
            if m.type in ("error",) else None)
        page.on("pageerror", lambda e: console_errors.append(
            {"t": now_iso(), "type": "pageerror", "text": str(e)[:500]}))

        print(f"[open] {args.url} @1366x768", flush=True)
        timeline.append({"t": now_iso(), "event": "goto", "url": args.url})
        await page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        await shot(page, shots / "00-profiles.png", "profiles", timeline)

        await ensure_started(page, timeline)

        # Live: chat input mounted, board greets Testbarn.
        await page.locator(CHAT_INPUT).wait_for(state="visible", timeout=90000)
        timeline.append({"t": now_iso(), "event": "live_chat_visible"})
        try:
            await page.locator(BOARD_EMPTY).wait_for(state="visible", timeout=15000)
            timeline.append({"t": now_iso(), "event": "board_empty_visible"})
        except Exception:
            pass
        await shot(page, shots / "01-live-empty.png", "live-empty", timeline)

        # (a) fractions ask -> tutor should call ask_screen, keep talking, show page.
        await send_chat(page, LINES["a"], timeline)
        # Give the tutor a moment to react in words before the screen finishes.
        await asyncio.sleep(6)
        cap = await caption_text(page)
        timeline.append({"t": now_iso(), "event": "caption_after_a", "caption": cap[:200]})
        print(f"[caption after a] {cap[:200]!r}", flush=True)
        await shot(page, shots / "02-after-a-sent.png", "after-a-sent", timeline)

        found = await wait_for(lambda: visible_page_id(page), timeout_s=150, poll_s=1.0)
        timeline.append({"t": now_iso(), "event": "page_visible", "page": found})
        print(f"[page] visible: {found}", flush=True)
        if not found:
            await shot(page, shots / "FAIL-no-page.png", "fail-no-page", timeline)
            raise SystemExit("no page became visible within 150 s")

        # Wait for the shell to report ready (is-ready) = rendered, not blank.
        ready = await wait_for(lambda: page_ready(page, found) or None, timeout_s=30)
        timeline.append({"t": now_iso(), "event": "page_ready_class", "page": found, "ready": bool(ready)})
        await asyncio.sleep(2)  # let KaTeX/JSXGraph settle
        info = await frame_inner_text(page, found)
        timeline.append({"t": now_iso(), "event": "page_dom", "page": found, "info": info})
        print(f"[page dom] {json.dumps(info, ensure_ascii=False)[:600]}", flush=True)
        await shot(page, shots / "03-page-visible.png", "page-visible", timeline)

        # (b) follow-up -> expect a patch applied in place (no new page needed,
        # though a new page also counts as progress).
        ids_before = await page_ids(page)
        await send_chat(page, LINES["b"], timeline)
        await asyncio.sleep(8)
        cap = await caption_text(page)
        timeline.append({"t": now_iso(), "event": "caption_after_b", "caption": cap[:200]})
        # Poll up to 90 s for either a new page or (same page, DOM changed).
        t0 = time.monotonic()
        patched = False
        new_page = None
        while time.monotonic() - t0 < 90:
            ids = await page_ids(page)
            fresh = [i for i in ids if i not in ids_before]
            if fresh:
                new_page = fresh[0]
                break
            await asyncio.sleep(2)
        if new_page:
            timeline.append({"t": now_iso(), "event": "second_page_visible", "page": new_page})
            print(f"[page] second page: {new_page}", flush=True)
            found = new_page
            await wait_for(lambda: page_ready(page, found) or None, timeout_s=30)
            await asyncio.sleep(2)
        else:
            # No new page: assume a patch may have landed; record DOM again.
            patched = True
            timeline.append({"t": now_iso(), "event": "no_second_page_assume_patch", "page": found})
        await shot(page, shots / "04-after-b.png", "after-b", timeline)

        # (c) ask for the answer on screen -> expect reveal/patch or words.
        await send_chat(page, LINES["c"], timeline)
        await asyncio.sleep(10)
        cap = await caption_text(page)
        timeline.append({"t": now_iso(), "event": "caption_after_c", "caption": cap[:200]})
        await shot(page, shots / "05-after-c.png", "after-c", timeline)

        # (d) answer in the page frame if there is a box; otherwise ask for one
        # (this also proves the patch path: a small change applied in place).
        current = await visible_page_id(page) or found
        if not await has_answer_box(page, current):
            patch_ids_before = await page_ids(page)
            await send_chat(page, LINES["box"], timeline)
            # Wait up to 120 s for a patch (same page, box appears) or a new page.
            t0 = time.monotonic()
            box_page = None
            while time.monotonic() - t0 < 120:
                ids = await page_ids(page)
                fresh = [i for i in ids if i not in patch_ids_before]
                if fresh:
                    box_page = fresh[0]
                    timeline.append({"t": now_iso(), "event": "box_new_page",
                                     "page": box_page})
                    current = box_page
                    await wait_for(lambda: page_ready(page, current) or None,
                                   timeout_s=30)
                    await asyncio.sleep(2)
                    break
                cur = await visible_page_id(page) or current
                if await has_answer_box(page, cur):
                    timeline.append({"t": now_iso(), "event": "box_patched_in_place",
                                     "page": cur})
                    print(f"[patch] answer box patched into {cur}", flush=True)
                    current = cur
                    break
                await asyncio.sleep(2)
            if not await has_answer_box(page, current):
                timeline.append({"t": now_iso(), "event": "box_missing_after_ask",
                                 "page": current})
            info = await frame_inner_text(page, current)
            timeline.append({"t": now_iso(), "event": "page_dom_after_box",
                             "page": current, "info": info})
            await shot(page, shots / "055-after-box-ask.png", "after-box-ask", timeline)
        answered = await answer_in_page(page, current, timeline)
        if answered:
            await asyncio.sleep(10)
            cap = await caption_text(page)
            timeline.append({"t": now_iso(), "event": "caption_after_answer", "caption": cap[:200]})
            print(f"[caption after answer] {cap[:200]!r}", flush=True)
        await shot(page, shots / "06-after-answer.png", "after-answer", timeline)
        # Point: ask the tutor to highlight the answer (proves board.point if used).
        try:
            await send_chat(page, LINES["point"], timeline)
            await asyncio.sleep(10)
            cap = await caption_text(page)
            timeline.append({"t": now_iso(), "event": "caption_after_point",
                             "caption": cap[:200]})
            await shot(page, shots / "065-after-point.png", "after-point", timeline)
        except Exception as e:
            timeline.append({"t": now_iso(), "event": "point_step_failed",
                             "error": f"{type(e).__name__}"})

        # End the session from the browser.
        try:
            btn = page.locator(END_BTN)
            await btn.wait_for(state="visible", timeout=15000)
            await btn.click()
            timeline.append({"t": now_iso(), "event": "end_clicked"})
        except Exception as e:
            timeline.append({"t": now_iso(), "event": "end_click_failed",
                             "error": f"{type(e).__name__}"})
            print(f"[end] click failed: {e}", flush=True)
        try:
            await page.locator(ENDCARD).wait_for(state="visible", timeout=90000)
            timeline.append({"t": now_iso(), "event": "endcard_visible"})
        except Exception:
            timeline.append({"t": now_iso(), "event": "endcard_timeout"})
            print("[end] no endcard within 90 s", flush=True)
        await shot(page, shots / "07-ended.png", "ended", timeline)

        (shots / "timeline.json").write_text(
            json.dumps({"timeline": timeline, "console_errors": console_errors,
                        "url": args.url}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"[done] {len(timeline)} events, {len(console_errors)} console errors", flush=True)
        for ce in console_errors[:20]:
            print(f"[console.{ce['type']}] {ce['text'][:200]}", flush=True)

        await ctx.close()
        await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
