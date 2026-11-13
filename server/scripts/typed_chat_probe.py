"""Typed-chat probe: send the child's first message while the tutor is still busy.

Reproduces the 2026-11-12/13 loss of a typed message: the tutor never answered it and
the session log had no ``chat_item`` for it at all. It plays a typed message at chosen
moments after the chat input appears (right away, a few seconds in, while the greeting
is being spoken) and reports, per message, whether the browser confirmed the send and
what the tutor said afterwards.

Two knobs make it deterministic without waiting for a slow provider:

* ``--stub-provider`` starts a local OpenAI-compatible endpoint whose first reply is
  delayed (``--first-delay``, e.g. 12 s, which makes the worker's 10 s provider timeout
  fire and retry, as in the failing session). Point the worker at it with
  ``TUTOR_LLM_BASE_URL``; see below.
* ``--log-dir`` reads the worker's session debug log (``TUTOR_DEBUG_LOG=1``) and prints
  when each typed message reached the worker (``chat_typed``) and whether it became a
  ``chat_item`` — the part that used to be missing entirely.

Run, with a worker of your own (never the shared dev services):

    # terminal 1 — the stub provider
    uv run --project server python server/scripts/typed_chat_probe.py --stub-provider --first-delay 12

    # terminal 2 — a worker of your own, pointed at the stub, and the web app
    TUTOR_AGENT_NAME=open-tutor-typed-test TUTOR_LLM=gemini \\
      TUTOR_LLM_BASE_URL=http://127.0.0.1:8799/v1 TUTOR_LLM_MODEL=stub \\
      TUTOR_DEBUG_LOG=1 TUTOR_DEBUG_LOG_DIR=/tmp/typed-chat/sessions \\
      bin/with-env uv run --project server python -m open_tutor.agent start

    # terminal 3 — drive the real page
    uv run --project server python server/scripts/typed_chat_probe.py \\
      --url http://127.0.0.1:8791/ --send-ats 0.5,3,25 \\
      --log-dir /tmp/typed-chat/sessions --shots-dir /tmp/typed-chat/shots

Fictional content only; it never touches production.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LEARNER_NAME = "Testbarn"
LEARNER_GRADE = 5
CHAT_INPUT = ".ot-chat-input"
END_BTN = 'button[aria-label="Avsluta sessionen"]'
DEFAULT_TEXT = "Hej! Jag ska räkna 3/4 + 1/8 men jag fattar inte. Kan du visa på skärmen?"

PROVIDER_STATE = {"count": 0, "log": None, "first_delay": 12.0, "delay": 0.3}
PROVIDER_STARTED = time.monotonic()


def _provider_log(entry: dict) -> None:
    entry["t_rel_s"] = round(time.monotonic() - PROVIDER_STARTED, 3)
    print("[stub] " + json.dumps(entry, ensure_ascii=False), flush=True)
    if PROVIDER_STATE["log"]:
        with open(PROVIDER_STATE["log"], "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


class StubHandler(BaseHTTPRequestHandler):
    """The smallest OpenAI-compatible Chat Completions stream that the worker accepts."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep the output about the messages, not the socket
        pass

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        PROVIDER_STATE["count"] += 1
        index = PROVIDER_STATE["count"]
        messages = body.get("messages", [])
        last_user = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                content = message.get("content")
                last_user = content if isinstance(content, str) else json.dumps(content)
                break
        delay = PROVIDER_STATE["first_delay"] if index == 1 else PROVIDER_STATE["delay"]
        _provider_log({"event": "request", "index": index, "messages": len(messages),
                       "last_user": last_user[:160], "delay_s": delay})
        if delay:
            time.sleep(delay)

        text = ("Hej Testbarn! Jag heter Räven och hjälper dig med läxorna. "
                "Vad vill du jobba med idag?")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()

        def chunk(payload: dict) -> None:
            data = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
            self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
            self.wfile.flush()

        base = {"id": f"chatcmpl-stub-{index}", "object": "chat.completion.chunk",
                "created": int(time.time()), "model": "stub"}
        chunk({**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})
        for start in range(0, len(text), 12):
            chunk({**base, "choices": [{"index": 0, "delta": {"content": text[start:start + 12]},
                                        "finish_reason": None}]})
            time.sleep(0.02)
        chunk({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}})
        done = b"data: [DONE]\n\n"
        self.wfile.write(f"{len(done):x}\r\n".encode() + done + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        _provider_log({"event": "answered", "index": index})


def serve_stub(port: int, first_delay: float, delay: float, log: str | None) -> None:
    PROVIDER_STATE.update(first_delay=first_delay, delay=delay, log=log)
    server = ThreadingHTTPServer(("127.0.0.1", port), StubHandler)
    print(f"[stub] http://127.0.0.1:{port}/v1, first reply delayed {first_delay}s", flush=True)
    server.serve_forever()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


async def start_session(page, timeline: list) -> None:
    await page.locator(".ot-profiles").wait_for(state="visible", timeout=30000)
    card = page.locator(".ot-profile-card", has_text=LEARNER_NAME)
    if await card.count() > 0:
        await card.first.click()
    else:
        new_here = page.locator(".ot-profile-card", has_text="Ny här?")
        if await new_here.count() > 0:
            await new_here.first.click()
        await page.locator('input[aria-label="Förnamn"]').fill(LEARNER_NAME)
        await page.locator('select[aria-label="Årskurs"]').select_option(str(LEARNER_GRADE))
    await page.locator(".ot-start-btn", has_text="Starta").click()
    timeline.append({"t": now_iso(), "event": "start_clicked"})


async def caption_text(page) -> str:
    try:
        el = await page.query_selector(".ot-caption")
        return (((await el.inner_text()) if el else "") or "").strip()[:300]
    except Exception:
        return ""


def scan_session_log(log_dir: Path | None, since: float) -> dict:
    """What the worker recorded for the newest session: typed arrivals and chat items."""
    if log_dir is None or not log_dir.is_dir():
        return {}
    candidates = [p for p in log_dir.glob("*/*.jsonl") if p.stat().st_mtime >= since - 5]
    if not candidates:
        return {}
    path = max(candidates, key=lambda p: p.stat().st_mtime)
    arrived, chat_items, replies = [], [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("event") == "chat_typed":
            arrived.append({"t_rel_s": entry.get("t_rel_s"), "queued": entry.get("queued"),
                            "text": (entry.get("text") or "")[:60]})
        elif entry.get("event") == "chat_item" and entry.get("item") == "message":
            role = entry.get("role")
            text = (entry.get("text") or "")[:60]
            if role == "user" and not text.startswith("[Session event"):
                chat_items.append({"t_rel_s": entry.get("t_rel_s"), "role": role, "text": text})
            elif role == "assistant":
                replies.append({"t_rel_s": entry.get("t_rel_s"), "text": text})
        elif entry.get("event") == "chat_typed_failed":
            arrived.append({"t_rel_s": entry.get("t_rel_s"), "failed": entry})
    return {"session_file": str(path), "chat_typed": arrived, "chat_items": chat_items,
            "assistant": replies}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8791/")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--send-ats", default="0.5,3,25",
                        help="seconds after the chat input appears, comma separated")
    parser.add_argument("--hold", type=float, default=45.0,
                        help="seconds to keep the session open after the last message")
    parser.add_argument("--shots-dir", default="/tmp/typed-chat")
    parser.add_argument("--log-dir", default="",
                        help="the worker's TUTOR_DEBUG_LOG_DIR, to report what it recorded")
    parser.add_argument("--stub-provider", action="store_true",
                        help="only start the slow OpenAI-compatible stub provider")
    parser.add_argument("--provider-port", type=int, default=8799)
    parser.add_argument("--first-delay", type=float, default=12.0)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--provider-log", default="")
    args = parser.parse_args()

    if args.stub_provider:
        serve_stub(args.provider_port, args.first_delay, args.delay,
                   args.provider_log or str(Path(args.shots_dir) / "provider.jsonl"))
        return 0

    from playwright.async_api import async_playwright

    shots = Path(args.shots_dir)
    shots.mkdir(parents=True, exist_ok=True)
    timeline: list[dict] = []
    console: list[dict] = []
    started = time.time()
    results: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                  "--autoplay-policy=no-user-gesture-required"],
        )
        ctx = await browser.new_context(viewport={"width": 1366, "height": 768},
                                        ignore_https_errors=True,
                                        permissions=["microphone", "camera"])
        page = await ctx.new_page()
        page.on("console", lambda m: console.append({"t": now_iso(), "type": m.type,
                                                      "text": m.text[:300]}))
        page.on("pageerror", lambda e: console.append({"t": now_iso(), "type": "pageerror",
                                                       "text": str(e)[:300]}))
        print(f"[open] {args.url}", flush=True)
        await page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        await start_session(page, timeline)
        await page.locator(CHAT_INPUT).wait_for(state="visible", timeout=90000)
        visible_at = time.monotonic()
        timeline.append({"t": now_iso(), "event": "chat_input_visible"})

        send_times = [float(part) for part in args.send_ats.split(",") if part.strip()]
        for number, send_at in enumerate(send_times, start=1):
            wait = send_at - (time.monotonic() - visible_at)
            if wait > 0:
                await asyncio.sleep(wait)
            text = args.text if number == 1 else f"{args.text} ({number})"
            box = page.locator(CHAT_INPUT)
            await box.fill(text)
            await box.press("Enter")
            at = round(time.monotonic() - visible_at, 2)
            confirmed = False
            try:
                await page.locator(".ot-sent-chip").wait_for(state="visible", timeout=8000)
                confirmed = True
            except Exception:
                pass
            before = await caption_text(page)
            results.append({"n": number, "sent_at_s": at, "browser_confirmed": confirmed,
                            "caption_before": before, "text": text})
            timeline.append({"t": now_iso(), "event": "chat_sent", **results[-1]})
            print(f"[send {number}] at +{at}s browser_confirmed={confirmed}", flush=True)

        print(f"[hold] {args.hold}s", flush=True)
        deadline = time.monotonic() + args.hold
        while time.monotonic() < deadline:
            await asyncio.sleep(3)
            results[-1]["caption_after"] = await caption_text(page)
        await page.screenshot(path=str(shots / "after.png"))

        try:
            await page.locator(END_BTN).wait_for(state="visible", timeout=10000)
            await page.locator(END_BTN).click()
            timeline.append({"t": now_iso(), "event": "end_clicked"})
        except Exception as error:
            timeline.append({"t": now_iso(), "event": "end_failed",
                             "error": type(error).__name__})
        await asyncio.sleep(3)
        await ctx.close()
        await browser.close()

    log = scan_session_log(Path(args.log_dir) if args.log_dir else None, started)
    summary = {"url": args.url, "results": results, "session_log": log,
               "sent_at_s": [r["sent_at_s"] for r in results]}
    (shots / "typed-chat.json").write_text(json.dumps(
        {"summary": summary, "timeline": timeline, "console": console},
        ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n=== result", flush=True)
    print(f"browser confirmed: {[r['browser_confirmed'] for r in results]}", flush=True)
    if log:
        print(f"session log: {log['session_file']}", flush=True)
        print(f"chat_typed (worker saw): {log['chat_typed']}", flush=True)
        print(f"child chat_items:        {log['chat_items']}", flush=True)
    for r in results:
        print(f"  #{r['n']} +{r['sent_at_s']}s -> before: {r['caption_before'][:90]!r}", flush=True)
    last = results[-1].get("caption_after", "")
    print(f"  last caption: {last[:200]!r}", flush=True)
    print(f"[written] {shots / 'typed-chat.json'}", flush=True)
    answered = log.get("chat_items") and len(log["chat_items"]) >= len(results)
    print(f"VERDICT: {'every typed message reached the tutor' if answered else 'MISSING typed message'}", flush=True)
    return 0 if answered else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
