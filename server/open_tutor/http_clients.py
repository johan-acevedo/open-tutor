"""Shared HTTP transports with long-lived keep-alive connections.

httpx's default ``keepalive_expiry`` is 5 s, so a tutor turn or screen call that
arrives more than a few seconds after the previous one pays a fresh TLS handshake.
Both the tutor routes (``tutor_llm.build_route_llm``) and the screen's streaming
calls (``screen._stream_spec``) build their OpenAI SDK clients on these shared
transports, with ``keepalive_expiry`` ~120 s, so warm connections are reused
across turns, jobs and sessions on the same event loop.

One client per (process, loop, host): creating them is cheap, sharing them is the
point, and an async transport must never cross event loops (reusing a transport
whose loop closed raises ``RuntimeError: Event loop is closed``). Each loop owns
its clients; ``aclose_shared_clients`` closes them at job/process shutdown.
``warm_provider_connections`` no longer touches the async transports at all: it
does a loop-independent warm-up (a cheap sync request per provider, then
discarded) so prewarm can never poison the loop-owned clients, and it is bounded
and never fails the worker.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time

import httpx2 as httpx

log = logging.getLogger("open-tutor")

# Long enough to span the pauses in a lesson; short enough to notice a dead peer.
KEEPALIVE_EXPIRY_S = 120.0

_lock = threading.RLock()  # re-entrant: shared_async_openai builds on shared_async_client
# (pid, loop, base_url) -> client. The loop is the key: an async transport is
# bound to the loop that first uses it, so each loop owns its clients and a
# closed loop's entries are pruned on the next access.
_async_clients: dict[tuple[int, object, str], httpx.AsyncClient] = {}
_async_openai: dict[tuple[int, object, str, str], object] = {}


def _prune_closed_locked() -> None:
    """Forget clients whose loop is gone. Only call with ``_lock`` held."""
    pid = os.getpid()
    dead_loops = {key[1] for key in _async_clients if key[0] != pid or key[1].is_closed()}
    if not dead_loops:
        return
    for key in [key for key in _async_clients if key[1] in dead_loops]:
        del _async_clients[key]
    for key in [key for key in _async_openai if key[1] in dead_loops]:
        del _async_openai[key]


def shared_async_client(base_url: str) -> httpx.AsyncClient:
    """One ``httpx.AsyncClient`` per (process, loop, host), with long keep-alive.

    Owned by the calling loop; close it with ``aclose_shared_clients`` at
    job/process shutdown. Never share the result across loops or threads."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        raise RuntimeError(
            "shared_async_client needs a running event loop: "
            "call from the job's loop, not from a worker thread or prewarm"
        ) from None
    key = (os.getpid(), loop, (base_url or "").rstrip("/"))
    with _lock:
        _prune_closed_locked()
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
    """One ``AsyncOpenAI`` per (process, loop, host, key), on the shared transport.

    Authentication and the User-Agent ride here; the per-session header
    (``x-opencode-session``) goes on each request as ``extra_headers`` so one
    cached client serves every session. Owned by the calling loop, like the
    transport it wraps: never share it across loops or threads.
    """
    from openai import AsyncOpenAI

    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        raise RuntimeError(
            "shared_async_openai needs a running event loop: "
            "call from the job's loop, not from a worker thread or prewarm"
        ) from None
    cache_key = (os.getpid(), loop, (base_url or "").rstrip("/"), api_key or "")
    with _lock:
        _prune_closed_locked()
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


async def aclose_shared_clients() -> None:
    """Close and forget the shared clients owned by the running loop.

    Call at job/process shutdown, after the last turn and screen job: closing
    earlier would break in-flight requests sharing the transport. Bounded and
    never raises; other loops' clients are left alone.
    """
    import asyncio

    loop = asyncio.get_running_loop()
    pid = os.getpid()
    with _lock:
        owned = [key for key in _async_clients
                 if key[0] == pid and key[1] is loop]
        wrappers = [key for key in _async_openai
                    if key[0] == pid and key[1] is loop]
    for key in owned:
        with _lock:
            client = _async_clients.pop(key, None)
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001 - shutdown hygiene, never fatal
                log.debug("closing a shared HTTP client failed", exc_info=True)
    with _lock:
        for key in wrappers:
            _async_openai.pop(key, None)


class _WarmRequest:
    """A sync warm-up whose deadline owner can interrupt an active socket."""

    def __init__(self, timeout_s: float, user_agent: str) -> None:
        self.client = httpx.Client(timeout=timeout_s, follow_redirects=True,
                                   headers={"User-Agent": user_agent})
        self.response: httpx.Response | None = None
        self._streams: list = []
        self._lock = threading.Lock()
        self._stopped = False

    def trace(self, event: str, info: dict) -> None:
        if event.endswith(("connect_tcp.complete", "start_tls.complete")):
            stream = info["return_value"]
            with self._lock:
                self._streams.append(stream)
                stopped = self._stopped
            if stopped:
                stream.close()
                raise TimeoutError("warm-up deadline")

    def close(self) -> None:
        with self._lock:
            self._stopped = True
            streams = list(self._streams)
        # Closing a socket alone need not wake recv() in another thread.
        for stream in streams:
            sock = stream.get_extra_info("socket")
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        try:
            if self.response is not None:
                self.response.close()
        finally:
            self.client.close()

    def run(self, label: str, base_url: str, api_key: str) -> bool:
        try:
            with self.client.stream(
                "GET", f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                extensions={"trace": self.trace},
            ) as response:
                self.response = response
                log.info("warmed provider connection to %s (status %s)", label, response.status_code)
                return True  # DNS/TCP/TLS is warm; never download the body.
        except Exception:  # noqa: BLE001 - warmth is best-effort, no credentials in logs
            log.debug("provider warm-up to %s did not answer", label)
            return False
        finally:
            self.client.close()


def warm_provider_connections(
    routes: list[tuple[str, str, str]], user_agent: str, budget_s: float = 5.0
) -> dict[str, bool]:
    """Warm response headers only, closing active I/O at the total deadline."""
    deadline = time.monotonic() + max(0.0, budget_s)
    outcome: dict[str, bool] = {}
    try:
        deduped = list(dict.fromkeys(route for route in routes if route[1] and route[2]))
        for index, (label, base_url, key) in enumerate(deduped):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            route_deadline = time.monotonic() + remaining / (len(deduped) - index)
            request = _WarmRequest(max(0.001, route_deadline - time.monotonic()), user_agent)
            holder: dict[str, bool] = {}

            def target(request=request, label=label, base_url=base_url, key=key, holder=holder):
                holder["ok"] = request.run(label, base_url, key)

            thread = threading.Thread(target=target, name=f"prewarm-{label}", daemon=True)
            thread.start()
            # Reserve time to interrupt socket I/O and join the stopped worker.
            thread.join(timeout=max(0.0, route_deadline - time.monotonic() - 0.1))
            timed_out = thread.is_alive()
            if timed_out:
                request.close()
                thread.join(timeout=max(0.0, route_deadline - time.monotonic()))
                log.debug("provider warm-up to %s reached its deadline", label)
            outcome[label] = not timed_out and holder.get("ok", False)
    except Exception:  # noqa: BLE001 - prewarm must never fail the worker
        log.debug("provider warm-up skipped")
    return outcome
