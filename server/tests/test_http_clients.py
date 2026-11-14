"""Shared HTTP transports: they must build without deadlocking and warm boundedly."""

import asyncio
import time


def test_shared_async_openai_builds_without_self_deadlock():
    """Regression: shared_async_openai builds on shared_async_client under one
    lock. With a plain Lock that self-deadlocked and every real screen model
    call hung forever (the tutor path never nested, so only the screen hung).

    Bounded on purpose: with the bug this fails in seconds instead of hanging
    the suite.
    """
    from open_tutor import http_clients

    async def build():
        return await asyncio.to_thread(
            http_clients.shared_async_openai, "https://example.invalid/v1", "k", "ua")

    client = asyncio.run(asyncio.wait_for(build(), timeout=10))
    assert client is not None
    assert http_clients.shared_async_client("https://example.invalid/v1") is not None


def test_warm_provider_connections_is_bounded_and_never_raises():
    from open_tutor import http_clients

    started = time.monotonic()
    outcome = http_clients.warm_provider_connections(
        [("dead", "http://127.0.0.1:9/v1", "k")], "ua", budget_s=3.0)
    assert time.monotonic() - started < 10
    assert outcome == {"dead": False}
    assert http_clients.warm_provider_connections([], "ua") == {}
