"""Shared HTTP transports with long-lived keep-alive connections.

httpx's default ``keepalive_expiry`` is 5 s, so a tutor turn or screen call that
arrives more than a few seconds after the previous one pays a fresh TLS handshake.
Both the tutor routes (``tutor_llm.build_route_llm``) and the screen's streaming
calls (``screen._stream_spec``) build their OpenAI SDK clients on these shared
transports, with ``keepalive_expiry`` ~120 s, so warm connections are reused
across turns, jobs and sessions in the same worker process.

One client per process per base URL: creating them is cheap, sharing them is the
point. They are never closed; the process owns them. ``warm_provider_connections``
opens each configured provider once at worker prewarm (see ``agent.prewarm``):
even a failed request warms DNS/TCP/TLS, and the whole warm-up is bounded and
never fails the worker.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

import httpx2 as httpx

log = logging.getLogger("open-tutor")

# Long enough to span the pauses in a lesson; short enough to notice a dead peer.
KEEPALIVE_EXPIRY_S = 120.0

_lock = threading.RLock()  # re-entrant: shared_async_openai builds on shared_async_client
_async_clients: dict[str, httpx.AsyncClient] = {}
_async_openai: dict[tuple[str, str], object] = {}


def shared_async_client(base_url: str) -> httpx.AsyncClient:
    """One ``httpx.AsyncClient`` per host, with long keep-alive. Never closed."""
    key = (base_url or "").rstrip("/")
    with _lock:
        client = _async_clients.get(key)
        if client is None:
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=120.0, write=15.0, pool=15.0),
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=50,
                    max_keepalive_connections=20,
                    keepalive_expiry=KEEPALIVE_EXPIRY_S,
                ),
            )
            _async_clients[key] = client
        return client


def shared_async_openai(base_url: str, api_key: str, user_agent: str):
    """One ``AsyncOpenAI`` per (host, key), on the shared transport.

    Authentication and the User-Agent ride here; the per-session header
    (``x-opencode-session``) goes on each request as ``extra_headers`` so one
    cached client serves every session. Never closed: it only wraps the shared
    transport, which the process owns.
    """
    from openai import AsyncOpenAI

    cache_key = ((base_url or "").rstrip("/"), api_key or "")
    with _lock:
        client = _async_openai.get(cache_key)
        if client is None:
            client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                max_retries=0,
                default_headers={"User-Agent": user_agent},
                http_client=shared_async_client(base_url),
            )
            _async_openai[cache_key] = client
        return client


async def _warm_one(label: str, base_url: str, api_key: str, user_agent: str) -> bool:
    """One cheap request (the provider's model list) to open the connection.

    Even a 404 warms DNS/TCP/TLS, which is the point after a cold restart. Any
    failure only costs the log line: warmth is best-effort.
    """
    try:
        client = shared_async_openai(base_url, api_key, user_agent)
        await asyncio.wait_for(client.models.list(), timeout=4.0)
        log.info("warmed provider connection to %s", label)
        return True
    except Exception as error:  # noqa: BLE001 - warmth is best-effort
        log.debug("provider warm-up to %s did not answer: %s", label, error)
        return False


def warm_provider_connections(
    routes: list[tuple[str, str, str]], user_agent: str, budget_s: float = 5.0
) -> dict[str, bool]:
    """Open one connection per ``(label, base_url, api_key)`` route.

    Synchronous, bounded by ``budget_s`` in total, never raises: worker prewarm
    calls this and a dead provider must not stop the worker from starting.
    Returns which routes answered, for the log only.
    """
    started = time.monotonic()
    outcome: dict[str, bool] = {}
    if not routes:
        return outcome
    try:
        deduped = list(dict.fromkeys((label, base_url, key) for label, base_url, key in routes if base_url and key))
        if not deduped:
            return outcome

        async def _all() -> list[bool]:
            return list(
                await asyncio.gather(
                    *(_warm_one(label, base_url, key, user_agent) for label, base_url, key in deduped),
                    return_exceptions=True,
                )
            )

        try:
            results = asyncio.run(asyncio.wait_for(_all(), timeout=max(0.5, budget_s)))
        except Exception as error:  # noqa: BLE001 - timeout or no loop: still bounded
            log.debug("provider warm-up bounded at %.1f s: %s", time.monotonic() - started, error)
            return outcome
        for (label, _base_url, _key), result in zip(deduped, results):
            outcome[label] = result is True
    except Exception as error:  # noqa: BLE001 - prewarm must never fail the worker
        log.debug("provider warm-up skipped: %s", error)
    return outcome
