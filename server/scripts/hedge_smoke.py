"""Live smoke for hedged tutor turns and screen pages.

Fictional prompts only. Keys come from the environment (never printed or
committed): OPENCODE_GO_API_KEY via server/bin/with-env and COMMAND_CODE_API_KEY
in the caller\u2019s environment.

(a) 3 real tutor turns, go primary + cc fallback, hedge on: most turns unhedged.
(b) Primary on a delay proxy (10 s stall): the turn is served by cc in about
    hedge deadline + normal ttft, with no mixed reply.
(c) One real screen page, go primary + cc fallback.
(d) Same page with go routed at the delay proxy: cc serves it.

Usage:
  set -a; source ~/.config/homelab/secrets/agent-auth.env; set +a
  server/bin/with-env uv run --project server python server/scripts/hedge_smoke.py [--parts abcd] [--race]

--race sets TUTOR_LLM_RACE=1 and SCREEN_RACE=1, so every part runs in race mode
(both providers from the start) instead of the delayed hedge.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livekit.agents import llm
from livekit.agents.types import APIConnectOptions

from open_tutor import agent
from open_tutor import http_clients
from open_tutor.config import LLMRoute
from open_tutor.screen import Screen
from open_tutor.session_llm import SessionLLM
from open_tutor.tutor_llm import build_route_llm

GO = "https://opencode.ai/inference/go/openai/v1"
CC = "https://api.commandcode.ai/provider/v1"
PORT = 18791


def sse_body(text: str) -> bytes:
    delta = {"type": "response.output_text.delta", "sequence_number": 3,
             "output_index": 0, "content_index": 0, "item_id": "msg_1", "delta": text}
    done = {"type": "response.completed", "sequence_number": 4,
            "response": {"id": "resp_smoke", "object": "response", "created_at": 0,
                         "model": "m", "status": "completed", "output": [],
                         "tools": [], "tool_choice": "auto", "parallel_tool_calls": True,
                         "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                                    "input_tokens_details": {"cached_tokens": 0},
                                    "output_tokens_details": {"reasoning_tokens": 0}}}}
    NL = chr(10)
    NLNL = chr(10) + chr(10)
    lines = ["data: " + json.dumps(e) for e in (delta, done)]
    lines.append("data: [DONE]")
    return (NLNL.join(lines) + NLNL).encode()


class DelayHandler(BaseHTTPRequestHandler):
    delay = 10.0

    def do_POST(self):  # noqa: N802 - http.server naming
        try:
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
        except Exception:
            pass
        time.sleep(self.delay)
        try:
            data = sse_body("Hej från den fördröjda proxyn.")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


def start_proxy(delay: float) -> ThreadingHTTPServer:
    DelayHandler.delay = delay
    server = ThreadingHTTPServer(("127.0.0.1", PORT), DelayHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class _Screen:
    def set_pane_source(self, fn):
        pass


def tutor_harness():
    tutor = agent.SmartTutor({"name": "Testbarn", "grade": 6}, MagicMock(),
                             board={}, screen=_Screen())
    return tutor.instructions, list(tutor.tools)


async def run_turn(model, text):
    ctx = llm.ChatContext()
    ctx.add_message(role="system", content="Du är Räven, en läxhjälpande räv. Svara kort på svenska.")
    ctx.add_message(role="user", content=text)
    t0 = time.perf_counter()
    out = ""
    stream = model.chat(chat_ctx=ctx, tools=[],
                        conn_options=APIConnectOptions(timeout=20, max_retry=0))
    try:
        async for chunk in stream:
            if chunk.delta and chunk.delta.content:
                out += chunk.delta.content
    finally:
        await stream.aclose()
    return out, time.perf_counter() - t0


async def part_a(instructions, tools, go_route, cc_route):
    print("--- (a) three real turns, go primary + cc fallback, hedge 2.5 s ---", flush=True)
    go = build_route_llm(go_route, "smoke-a")
    cc = build_route_llm(cc_route, "smoke-a")
    model = SessionLLM(go, go_route, cc, cc_route, prefer_within=1.5)
    await model.warm_up(instructions=instructions, tools=tools)
    print(f"warm-up winner: {model.route_name}", flush=True)
    for text in ("Hej! Kan du hjälpa mig med bråk?", "Vad är tre fjärdedelar plus ett halvt?",
                 "Kan du ge ett till exempel?"):
        out, wall = await run_turn(model, text)
        print(f"turn: wall={wall:.1f}s text={out[:80]!r}", flush=True)
    for turn in model.turn_stats:
        print("llm_turn:", turn, flush=True)
    await model.aclose()


async def part_b(cc_route):
    print("--- (b) primary stalled 10 s on a delay proxy: cc must serve ---", flush=True)
    proxy = start_proxy(10.0)
    slow = LLMRoute("go-slow", "responses", f"http://127.0.0.1:{PORT}/v1",
                    "muse-spark-1.3-contributor", "dummy", "minimal")
    slow_llm = build_route_llm(slow, "smoke-b")
    cc = build_route_llm(cc_route, "smoke-b")
    model = SessionLLM(slow_llm, slow, cc, cc_route, prefer_within=1.5)
    t0 = time.perf_counter()
    out, wall = await run_turn(model, "Hej! Vad är klockan halv sju på en urtavla?")
    print(f"turn: wall={wall:.1f}s text={out[:100]!r}", flush=True)
    print("llm_turn:", model.turn_stats[-1] if model.turn_stats else None, flush=True)
    await model.aclose()
    proxy.shutdown()


async def part_c(tmpdir):
    print("--- (c) one real screen page, go primary + cc fallback ---", flush=True)
    screen = Screen({"name": "Testbarn", "grade": 4}, Path(tmpdir) / "pages",
                    render_page=AsyncMock(return_value=(b"PNG", [])))
    delivered = {}
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.on_failure = lambda m: delivered.setdefault("failure", m)
    t0 = time.perf_counter()
    screen.ask("En sida om klockan halv sju")
    await screen.wait_idle()
    print(f"page: wall={time.perf_counter() - t0:.1f}s delivered={'page' in delivered}",
          flush=True)
    if "page" in delivered:
        print("body head:", delivered["page"].body[:120].replace(chr(10), " "), flush=True)
    print("screen stats:", screen.screen_stats_summary(), flush=True)
    await screen.aclose()


async def part_d(tmpdir):
    print("--- (d) screen page with go stalled: cc must serve ---", flush=True)
    import os

    proxy = start_proxy(10.0)
    previous_fallback = os.environ.get("SCREEN_FALLBACK")
    os.environ["SCREEN_FALLBACK"] = "cc"
    real_factory = http_clients.shared_async_openai

    def routed(base_url, key, user_agent):
        if "opencode.ai" in base_url:
            return real_factory(f"http://127.0.0.1:{PORT}/v1", key, user_agent)
        return real_factory(base_url, key, user_agent)

    http_clients.shared_async_openai = routed
    os.environ["SCREEN_HEDGE_AFTER_S"] = "2"
    try:
        screen = Screen({"name": "Testbarn", "grade": 4}, Path(tmpdir) / "pages-d",
                        render_page=AsyncMock(return_value=(b"PNG", [])))
        delivered = {}
        screen.on_page = lambda p: delivered.setdefault("page", p)
        screen.on_failure = lambda m: delivered.setdefault("failure", m)
        t0 = time.perf_counter()
        screen.ask("En sida om bråk: en halv plus en fjärdedel")
        await screen.wait_idle()
        print(f"page: wall={time.perf_counter() - t0:.1f}s delivered={'page' in delivered}",
              flush=True)
        if "page" in delivered:
            print("body head:", delivered["page"].body[:120].replace(chr(10), " "), flush=True)
        print("screen stats:", screen.screen_stats_summary(), flush=True)
        await screen.aclose()
    finally:
        http_clients.shared_async_openai = real_factory
        if previous_fallback is None:
            os.environ.pop("SCREEN_FALLBACK", None)
        else:
            os.environ["SCREEN_FALLBACK"] = previous_fallback
        proxy.shutdown()


async def main():
    import os

    for key in ("OPENCODE_GO_API_KEY", "COMMAND_CODE_API_KEY"):
        if not os.environ.get(key):
            raise SystemExit(f"missing {key} in the environment")
    go_route = LLMRoute("go", "responses", GO, "muse-spark-1.3-contributor",
                        os.environ["OPENCODE_GO_API_KEY"], "minimal")
    cc_route = LLMRoute("cc", "responses", CC, "meta/muse-spark-1.3-contributor",
                        os.environ["COMMAND_CODE_API_KEY"], "minimal")
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parts", default="abcd",
                        help="which smoke parts to run (default abcd)")
    parser.add_argument("--race", action="store_true",
                        help="race mode: both providers from the start "
                             "(TUTOR_LLM_RACE=1, SCREEN_RACE=1)")
    args = parser.parse_args()
    parts = args.parts
    if args.race:
        os.environ["TUTOR_LLM_RACE"] = "1"
        os.environ["SCREEN_RACE"] = "1"
        print("race mode on (TUTOR_LLM_RACE=1, SCREEN_RACE=1)", flush=True)
    if "a" in parts:
        instructions, tools = tutor_harness()
        await part_a(instructions, tools, go_route, cc_route)
    if "b" in parts:
        await part_b(cc_route)
    if "c" in parts or "d" in parts:
        with tempfile.TemporaryDirectory() as tmpdir:
            if "c" in parts:
                await part_c(tmpdir)
            if "d" in parts:
                await part_d(tmpdir)
    print("smoke done", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
