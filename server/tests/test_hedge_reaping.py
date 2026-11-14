"""PR #65 review probes, retained as teardown and prewarm regressions."""

import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from livekit.agents import llm

from test_hedged_tutor import HedgeFakeLLM, HangingFakeLLM, route
from test_screen_hedge import hedging_screen
from open_tutor.session_llm import SessionLLM
from open_tutor import http_clients


def model_for(primary, secondary):
    model = SessionLLM(primary, route('preferred'), secondary, route('fallback'))
    model._decide(primary, 'preferred', 'review fixture: skip provider warm-up')
    return model


async def base_close_all(*models):
    for model in models:
        for stream in model.streams:
            await llm.LLMStream.aclose(stream)


class TrickleServer:
    def __init__(self, *, slow_headers=False):
        self.slow_headers = slow_headers

    def __enter__(self):
        self.stop = threading.Event()
        stop = self.stop
        self.seen = 0
        owner = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def do_GET(self):
                owner.seen += 1
                if owner.slow_headers:
                    try:
                        self.wfile.write(b"HTTP/1.1 200 OK\r\nX-Trickle: ")
                        while not stop.wait(0.03):
                            self.wfile.write(b"x")
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                self.send_response(200)
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                try:
                    while not stop.is_set():
                        self.wfile.write(b'1\r\nx\r\n')
                        self.wfile.flush()
                        stop.wait(0.05)
                    self.wfile.write(b'0\r\n\r\n')
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/v1'
        return self
    def __exit__(self, *args):
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        for t in threading.enumerate():
            if t.name.startswith('prewarm-review'):
                t.join(1)


async def test_new_tutor_timeout_leaves_provider_running(monkeypatch):
    monkeypatch.setenv('TUTOR_LLM_HEDGE_AFTER_S', '0.05')
    p = HangingFakeLLM('preferred', script=[(60, 'slow')])
    s = HedgeFakeLLM('fallback', script=[(0.01, 'fast')])
    stream = model_for(p, s).chat(chat_ctx=llm.ChatContext())
    try:
        async for chunk in stream:
            pass
        await stream.aclose()
        await asyncio.sleep(0)
        provider = p.streams[-1]
        assert provider._task.done(), 'wrapper shutdown dropped the live loser provider task'
    finally:
        await base_close_all(p, s)


def test_new_prewarm_threads_accumulate():
    with TrickleServer() as server:
        for i in range(3):
            http_clients.warm_provider_connections([('review-leak', server.url, 'fake')], 'review', budget_s=0.5)
        pending = [t for t in threading.enumerate() if t.name == 'prewarm-review-leak']
        assert not pending, 'every warm call abandons another live thread/socket'


async def test_new_winner_close_skipped_after_loser_spends_budget(monkeypatch):
    monkeypatch.setenv('TUTOR_LLM_HEDGE_AFTER_S', '0.05')
    p = HangingFakeLLM('preferred', script=[(60, 'slow')])
    s = HedgeFakeLLM('fallback', script=[(0.01, 'first'), (60, 'remaining')])
    stream = model_for(p, s).chat(chat_ctx=llm.ChatContext())
    try:
        assert (await anext(stream)).delta.content == 'first'
        await stream.aclose()
        winner = s.streams[-1]
        assert winner.closed
        assert winner._task.done(), 'exhausted loser budget discards the active winner without aclose'
    finally:
        await base_close_all(p, s)


async def test_new_screen_full_call_exceeds_two_second_bound(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv('SCREEN_HEDGE_AFTER_S', '0.05')
    async def primary(*args):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            try:
                await asyncio.sleep(60)
            finally:
                await asyncio.sleep(3)
            raise
    async def secondary(*args):
        return '<h1>Fictional page</h1>'
    screen = hedging_screen(tmp_path, monkeypatch, model_call=primary, fallback_call=secondary)
    started = time.monotonic()
    try:
        result = await screen._call_model('system', 'fictional', kind='look')
        elapsed = time.monotonic() - started
        assert result[0] == '<h1>Fictional page</h1>'
        assert elapsed < 0.3, 'slow loser teardown exceeds even the two-second cleanup budget'
    finally:
        close_started = time.monotonic()
        await screen.aclose()
        assert time.monotonic() - close_started < 2.2
        assert screen._reaper.tasks
        assert sum("provider cleanup exceeded deadline" in r.message for r in caplog.records) == 1




def test_prewarm_header_trickle_stops_worker_at_deadline():
    with TrickleServer(slow_headers=True) as server:
        started = time.monotonic()
        result = http_clients.warm_provider_connections(
            [("review-header-trickle", server.url, "fake")], "review", budget_s=0.5)
        assert time.monotonic() - started < 0.7
        assert result == {"review-header-trickle": False}
        assert not [t for t in threading.enumerate() if t.name == "prewarm-review-header-trickle"]


async def test_tutor_shutdown_does_not_wait_past_cancel_deadline(monkeypatch, caplog):
    from test_hedged_tutor import ScriptedStream
    from open_tutor import session_llm

    monkeypatch.setenv("TUTOR_LLM_HEDGE_AFTER_S", "0.05")
    monkeypatch.setattr(session_llm, "LOSER_CLEANUP_BOUND_S", 0.05)
    closing, finished = asyncio.Event(), asyncio.Event()

    class SlowTeardown(ScriptedStream):
        async def aclose(self):
            try:
                closing.set()
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0.4)
                finished.set()
                await super().aclose()

    class SlowLLM(HedgeFakeLLM):
        def chat(self, *, chat_ctx, tools=None, conn_options=None, **kwargs):
            stream = SlowTeardown(self, chat_ctx, tools or [], conn_options, script=self.script)
            self.streams.append(stream)
            return stream

    p = SlowLLM("preferred", script=[(60, "slow")])
    s = HedgeFakeLLM("fallback", script=[(0.01, "first"), (60, "later")])
    stream = model_for(p, s).chat(chat_ctx=llm.ChatContext())
    try:
        assert (await anext(stream)).delta.content == "first"
        await closing.wait()
        started = time.monotonic()
        await stream.aclose()
        assert time.monotonic() - started < 0.15
        assert p.streams[-1]._task.done()
        assert s.streams[-1].closed
        assert not finished.is_set()
        assert stream._reaper.tasks  # survivors retain ownership past the deadline
        await asyncio.wait_for(finished.wait(), 1)
        assert sum("(preferred)" in record.message for record in caplog.records) == 1
    finally:
        await base_close_all(p, s)
