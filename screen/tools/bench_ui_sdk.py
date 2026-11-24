"""Run paired fictional exercises through Smart Screen without a tutor or a room.

Run from the repository root. Export only the screen provider key, then run:
  uv run --project server python -m screen.tools.bench_ui_sdk OUTPUT --reference CATALOGUE

The output directory contains fictional inputs, raw output, screenshots, and
measurements. Re-running skips recorded arms, including failures.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from playwright.async_api import Error as BrowserError

from open_tutor.screen import Screen
from screen.tools import screenkit


PANE = (370, 610)
CASES = (
    ("clock", "Klockan", 3, "primary", "choice",
     "Jag blandar ihop kvart i och kvart över.",
     "Visa en analog klocka som står på 7.45. Låt eleven välja mellan tre sätt att säga tiden. "
     "Visa inte vilken som är rätt."),
    ("water", "Vattnets kretslopp", 5, "primary", "order",
     "Jag vet att det går runt, men vad händer på vägen?",
     "Låt eleven ordna fyra steg från vattenytan och tillbaka dit: avdunstning, kondensation, "
     "nederbörd och avrinning. Börja i blandad ordning. Låt eleven lämna sin ordning på sidan. "
     "Visa inte lösningen."),
    ("english", "Engelska fraser", 6, "primary", "match",
     "Jag övar på vad man säger på ett kafé.",
     "Låt eleven para ihop tre fraser på engelska med tre svenska betydelser: "
     "Can I have the menu?, I'd like some water., och How much is it? "
     "Visa betydelserna i blandad ordning. Låt eleven lämna sina par på sidan. Visa inte facit."),
    ("history", "Svensk demokrati", 8, "middle", "order",
     "Vi ska förstå hur fler fick vara med och bestämma.",
     "Låt eleven ordna fyra svenska händelser från äldst till nyast: enkammarriksdagen införs, "
     "första riksdagsvalet där kvinnor får rösta, rösträttsåldern blir 18 år och ståndsriksdagen ersätts "
     "med en tvåkammarriksdag. Börja i blandad ordning och visa inga årtal eller facit. "
     "Låt eleven lämna sin ordning på sidan."),
    ("algebra", "Ekvationen", 9, "middle", "answer",
     "Jag förstår varför man gör samma sak på båda sidor, men fastnar när jag ska börja.",
     "Visa ekvationen 3x + 5 = 20 som en våg. Fråga vilken operation som tar bort +5 och låt "
     "eleven skriva sitt eget förslag på sidan. Visa inte operationen eller lösningen."),
    ("physics", "Storhet och enhet", 11, "upper", "match",
     "Jag blandar ihop storheterna i elläran med deras enheter.",
     "Låt eleven para ihop elektrisk ström, spänning och resistans med ampere, volt och ohm. "
     "Visa en kort ledtråd om skillnaden mellan en storhet och en enhet. Blanda alternativen, "
     "låt eleven lämna sina par på sidan och visa inte facit."),
)
SDK_TAGS = re.compile(r"<(ot-order|ot-match|ot-sdk-choice|ot-sdk-answer)\b", re.I)


def exercise_host(document: str) -> str:
    # Mirror the parent frame's ready gate and source-window check. Use frame
    # boundaries as paint proxies because PerformancePaintTiming is top-level.
    listener = """<style>
iframe {opacity:0;transition:opacity .25s ease}
iframe.ready {opacity:1}
</style><script>
window.answerMessages = [];
window.addEventListener('message', event => {
  const frame = document.querySelector('iframe');
  if (event.source !== frame?.contentWindow) return;
  if (event.data?.ot === 'answer') window.answerMessages.push(event.data);
  if (event.data?.ot !== 'ready' || frame.classList.contains('ready')) return;
  frame.classList.add('ready');
  requestAnimationFrame(function checkOpacity() {
    const opacity = Number(getComputedStyle(frame).opacity);
    if (opacity > 0) window.visibleAt ??= performance.now();
    if (opacity === 1) window.completeAt = performance.now();
    else requestAnimationFrame(checkOpacity);
  });
});
</script>"""
    return screenkit.host_page(document).replace("</head>", listener + "</head>", 1)


async def observe(browser, document: str, destination: Path, started: float) -> dict:
    viewer = await browser.new_page(viewport={"width": PANE[0], "height": PANE[1]})
    viewer.set_default_timeout(1800)
    try:
        # Use the same browser clock before and after set_content.
        browser_start = await viewer.evaluate("performance.now()")
        arrival = time.monotonic() - started
        await viewer.set_content(exercise_host(document), wait_until="domcontentloaded", timeout=15000)
        await viewer.wait_for_function("window.completeAt", timeout=15000)
        frame = viewer.frames[1]
        marks = await viewer.evaluate("() => [window.visibleAt, window.completeAt]")
        await viewer.screenshot(path=destination / "screen.png")
        main = frame.locator("#page")
        snapshot = await main.aria_snapshot()
        (destination / "accessibility.txt").write_text(snapshot, encoding="utf-8")
        layout = await frame.evaluate("""() => ({
          font_px: ot.fontPx,
          page_overflow: document.querySelector('#page').scrollHeight >
            document.querySelector('#page').clientHeight + 2 ||
            document.documentElement.scrollWidth > innerWidth + 2,
          text_chars: document.querySelector('#page').innerText.trim().length,
          issues: ot.issues
        })""")
        row = dict(zip(("first_visible_s", "complete_s"),
                       (round(arrival + (x - browser_start) / 1000, 3) for x in marks)))
        row.update(layout)
        row["keyboard"] = await check_keyboard(viewer, frame)
        (destination / "accessibility-after.txt").write_text(await main.aria_snapshot(), encoding="utf-8")
        return row
    finally:
        await viewer.close()


async def check_keyboard(viewer, frame) -> dict:
    """Follow the actual Tab order and exercise ordinary control key bindings."""
    focused = set()
    trace = []
    radio_arrows = False
    move_used = False
    for _ in range(32):
        await viewer.keyboard.press("Tab")
        active = frame.locator(":focus")
        if await active.count() == 0:
            if trace:
                break
            continue
        key = await active.evaluate("""el => {
          const control = el.shadowRoot?.activeElement || el;
          const index = [...document.querySelectorAll('*')].indexOf(el);
          return {index, role: control.getAttribute('role') || control.localName,
            name: control.getAttribute('aria-label') || control.labels?.[0]?.textContent?.trim()
              || control.textContent.trim().slice(0, 65), type: control.type || ''};
        }""")
        index = key.pop("index")
        if index in focused:
            break
        focused.add(index)
        trace.append(key)
        role, name = key["role"], key["name"]
        if role == "radio":
            await viewer.keyboard.press("ArrowRight")
            radio_arrows = (await frame.get_by_role("radio", checked=True).count()) > 0
            if not radio_arrows:
                await viewer.keyboard.press("Space")
        elif role == "combobox":
            await viewer.keyboard.press("ArrowDown")
            await viewer.keyboard.press("Enter")
        elif role in ("input", "textarea", "textbox") and key["type"] != "radio":
            await viewer.keyboard.insert_text("Test")
        elif role == "button":
            if re.search(r"skicka|lämna|svara", name, re.I):
                await viewer.keyboard.press("Enter")
                break
            if re.search(r"flytta", name, re.I):
                if not move_used:
                    await viewer.keyboard.press("Enter")
                    move_used = True
            elif len(trace) == 1:
                await viewer.keyboard.press("Space")
    answers = await viewer.evaluate("() => new Promise(resolve => requestAnimationFrame(() => resolve(window.answerMessages)))")
    announcements = await frame.locator('[role="status"], [aria-live="polite"]').all_text_contents()
    return {"focus": trace, "answers": answers, "radio_arrow_selects": radio_arrows,
            "move_control_activated": move_used, "status": [item.strip() for item in announcements if item.strip()]}


def body_metrics(body: str) -> dict:
    return {"body_bytes": len(body.encode()), "body_lines": len(body.splitlines()),
            "sdk_tags": sorted(set(SDK_TAGS.findall(body))),
            "script_tags": len(re.findall(r"<script\b", body, re.I))}


async def measure(case, arm: str, folder: Path, reference: str, session: str,
                  baseline_shell: Path | None) -> dict:
    slug, title, grade, band, kind, turn, ask = case
    row = {"case": slug, "title": title, "grade": grade, "band": band, "type": kind, "arm": arm}
    output = folder / slug / arm
    output.mkdir(parents=True, exist_ok=True)
    screen = Screen({"grade": grade, "band": band}, output / "job", session_id=session,
                    get_pane_size=lambda: PANE)
    screen.add_turn("child", turn)
    if arm == "sdk":
        screen._system = screen.system_prompt() + "\n\n" + reference
    real_call = screen._default_model_call
    calls = 0

    def compose(body):
        if arm == "sdk":
            return screenkit.compose(body, band=band, ui_sdk=True)
        return screenkit.compose(body, shell=baseline_shell, band=band)

    async def model(system, user, images, look_png, on_first_text, on_text):
        nonlocal calls
        calls += 1
        if calls > 1 or images or look_png:
            raise RuntimeError("Experiment permits one text-only provider request per arm.")
        try:
            body = await real_call(system, user, images, look_png, on_first_text, on_text)
        except Exception as error:
            # Provider exception payloads can include request data. Record the
            # class and HTTP status, if supplied.
            name, status = type(error).__name__, getattr(error, "status_code", None)
            row["provider_failure"] = {"type": name, "status": status}
            raise RuntimeError(f"Screen provider request failed: {name} ({status}).") from None
        row.update(body_metrics(body))
        (output / "model.html").write_text(body, encoding="utf-8")
        return body

    async def render(body, patch, history, width, height):
        viewer = await screen._browser.new_page(viewport={"width": width, "height": height})
        try:
            await viewer.set_content(screenkit.host_page(compose(body)), wait_until="domcontentloaded")
            frame = viewer.frames[1]
            await frame.wait_for_function("document.documentElement.dataset.otReady === '1'")
            return await viewer.screenshot(), await frame.evaluate("ot.issues")
        finally:
            await viewer.close()

    delivered = []
    screen._model_call = model
    screen._render_page = render
    screen.on_page = delivered.append
    screen.on_failure = lambda reason: row.update(failure=reason)
    try:
        await screen.warmup()
        if screen._browser is None:
            raise RuntimeError("Chromium could not start. No provider request was made.")
        started = time.monotonic()
        screen.ask(ask)
        await screen.wait_idle()
        if delivered:
            result = delivered[0]
            meta = json.loads((result.directory / "meta.json").read_text(encoding="utf-8"))
            row.update(delivered=True, first_text_s=meta.get("ttft_s"), model_s=round(result.model_s, 3),
                       render_s=round(result.render_s, 3), server_done_s=round(result.total_s, 3))
            try:
                row.update(await observe(screen._browser, compose(result.body), output, started))
            except BrowserError as error:
                row["viewer_failure"] = type(error).__name__
        return row
    finally:
        await screen.aclose()


async def run(args):
    settings = {
        "SCREEN_MODEL": "muse-spark-1.3-contributor", "SCREEN_API": "responses", "SCREEN_REASONING": "minimal",
        "SCREEN_LOOK": "0", "SCREEN_LINT_RETRY": "0", "SCREEN_FALLBACK": "", "SCREEN_THINKING": "",
        "SCREEN_IMAGES": "commons",
    }
    os.environ.update(settings)
    if not os.environ.get("OPENCODE_GO_API_KEY"):
        raise SystemExit("OPENCODE_GO_API_KEY is missing. No provider request was made.")
    reference = args.reference.read_text(encoding="utf-8") if args.reference else ""
    args.output.mkdir(parents=True, exist_ok=True)
    results = args.output / "results.json"
    evidence = (json.loads(results.read_text(encoding="utf-8")) if results.exists() else
                {"session": f"ui-sdk-{uuid4().hex}", "settings": settings, "rows": []})
    rows = evidence["rows"]
    recorded = {(row["case"], row["arm"]) for row in rows}
    for index, case in enumerate(CASES):
        if args.case and case[0] != args.case:
            continue
        for arm in ("control", "sdk") if index % 2 == 0 else ("sdk", "control"):
            if (case[0], arm) in recorded or args.arm not in ("both", arm):
                continue
            row = await measure(case, arm, args.output, reference, evidence["session"], args.baseline_shell)
            rows.append(row)
            results.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({k: v for k, v in row.items() if k != "keyboard"}, ensure_ascii=False), flush=True)
            if row.get("provider_failure", {}).get("status") in (401, 403, 429):
                raise SystemExit("Provider denied the request. Stopping the remaining arms.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--baseline-shell", type=Path)
    parser.add_argument("--arm", choices=("both", "control", "sdk"), default="both")
    parser.add_argument("--case", choices=[case[0] for case in CASES])
    args = parser.parse_args()
    if args.arm != "control" and not args.reference:
        parser.error("--reference is required when running the SDK arm")
    asyncio.run(run(args))
