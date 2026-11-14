"""Shared HTTP transports: per-loop ownership, bounded warm-up, clean shutdown."""

import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.fixture
def models_server():
    """A tiny HTTP/1.1 keep-alive server answering the model list.

    Keep-alive matters: it lets a pooled connection bind to the warming loop,
    which is exactly what must never leak into another loop's client.
    """

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802 - http.server naming
            body = b'{"object":"list","data":[]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


def test_shared_async_openai_builds_without_self_deadlock():
    """Regression: shared_async_openai builds on shared_async_client under one
    lock. With a plain Lock that self-deadlocked and every real screen model
    call hung forever (the tutor path never nested, so only the screen hung).

    Bounded on purpose: with the bug this fails in seconds instead of hanging
    the suite.
    """
    from open_tutor import http_clients

    async def build():
        return http_clients.shared_async_openai("https://example.invalid/v1", "k", "ua")

    async def check():
        await build()
        # Nested under the same lock, on the same loop: the old plain Lock
        # self-deadlocked here.
        return http_clients.shared_async_client("https://example.invalid/v1") is not None

    assert asyncio.run(asyncio.wait_for(check(), timeout=10))


def test_shared_clients_need_the_job_loop():
    """Creating a shared client off-loop is a loud error, not a transport bound
    to a stranger loop that dies later with ``Event loop is closed``."""
    from open_tutor import http_clients

    with pytest.raises(RuntimeError, match="running event loop"):
        http_clients.shared_async_client("https://example.invalid/v1")
    with pytest.raises(RuntimeError, match="running event loop"):
        http_clients.shared_async_openai("https://example.invalid/v1", "k", "ua")


def test_warm_provider_connections_is_bounded_and_never_raises():
    from open_tutor import http_clients

    started = time.monotonic()
    outcome = http_clients.warm_provider_connections(
        [("dead", "http://127.0.0.1:9/v1", "k")], "ua", budget_s=3.0)
    assert time.monotonic() - started < 10
    assert outcome == {"dead": False}
    assert http_clients.warm_provider_connections([], "ua") == {}


def test_prewarm_does_not_poison_shared_transports(models_server):
    """P1: prewarm must never bind the shared async transports to its own loop.

    The old code warmed the shared clients inside ``asyncio.run``, whose loop
    then closed; reusing the pooled keep-alive connection on the job loop
    raised ``RuntimeError: Event loop is closed`` (affecting Gemini too).
    Prewarm is loop-independent now, so a fresh loop's client just works.
    """
    from open_tutor import http_clients

    outcome = http_clients.warm_provider_connections(
        [("stub", models_server, "k")], "ua", budget_s=5.0)
    assert outcome == {"stub": True}

    async def use_on_a_fresh_loop():
        client = http_clients.shared_async_client(models_server)
        try:
            async with client.stream("GET", f"{models_server}/models") as response:
                assert response.status_code == 200
                await response.aread()
        finally:
            await http_clients.aclose_shared_clients()
        return True

    # A new loop, as the job loop is after prewarm ran elsewhere.
    assert asyncio.run(use_on_a_fresh_loop())


def test_loop_clients_are_owned_per_loop_and_closed(models_server):
    """Each loop owns its clients; closing drops them without touching others."""
    from open_tutor import http_clients

    async def on_first_loop():
        first = http_clients.shared_async_client(models_server)
        assert http_clients.shared_async_client(models_server) is first
        return first

    async def on_second_loop(first):
        second = http_clients.shared_async_client(models_server)
        assert second is not first  # never shared across loops
        await http_clients.aclose_shared_clients()
        assert second.is_closed
        assert not first.is_closed  # the other loop's client is left alone
        # A closed client is forgotten: the next access recreates it.
        recreated = http_clients.shared_async_client(models_server)
        assert recreated is not second
        await http_clients.aclose_shared_clients()

    first = asyncio.run(on_first_loop())
    asyncio.run(on_second_loop(first))
    assert first.is_closed is False  # its loop died; the entry was pruned, not closed


# ---- third fix round: absolute prewarm deadline --------------------------------


def test_prewarm_trickling_server_returns_within_budget():
    """P2: a server trickling bytes forever must not stall worker init.

    Fails on 7bfa963, where prewarm relied on httpx inactivity timeouts: a
    trickle within those timeouts outlived ``budget_s``.
    """
    import time as _time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class TrickleHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802 - http.server naming
            body_len = 100
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(body_len))
            self.end_headers()
            try:
                for _ in range(body_len):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    _time.sleep(0.2)  # trickle: within httpx read timeouts, past budget
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), TrickleHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        from open_tutor import http_clients

        url = f"http://127.0.0.1:{server.server_port}/v1"
        started = _time.monotonic()
        outcome = http_clients.warm_provider_connections(
            [("trickle", url, "k")], "ua", budget_s=2.0)
        elapsed = _time.monotonic() - started
        assert elapsed < 4.0  # absolute deadline, not the ~20 s trickle
        assert outcome == {"trickle": True}
    finally:
        server.shutdown()
