"""Deepgram Flux TTS (/v2/speak) with the beta ``expressivity`` voice control.

Upstream ``livekit.plugins.deepgram.TTSv2`` (1.8.10) exposes ``model`` and
``base_url`` but no ``expressivity`` option, so this narrow subclass adds it and
sends it as a query parameter on both transports, exactly like ``model``:
per-connection on the streaming WebSocket and per-request on batch synthesize.
Everything else (word transport, error mapping) is inherited untouched, so a
vendor non-success still surfaces as ``APIError``/``APIStatusError`` and is never
swallowed. Drop this adapter when upstream gains the option.

Docs: https://developers.deepgram.com/docs/tts-expressivity
(``expressivity``: integer -2 calm .. 2 animated, default 0; the server rejects
invalid values instead of clamping them).
"""

from __future__ import annotations

import asyncio
import time

import aiohttp
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    tts,
    utils,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from livekit.plugins.deepgram import TTSv2
from livekit.plugins.deepgram._utils import _to_deepgram_url
from livekit.plugins.deepgram.log import logger
from livekit.plugins.deepgram.tts_v2 import (
    NUM_CHANNELS,
    ChunkedStreamv2,
    _encoding_to_mimetype,
)

# Johan's pick: https://api.deepgram.com/v2/speak?model=flux-ludvig-sv&expressivity=1
DEFAULT_MODEL = "flux-ludvig-sv"
DEFAULT_EXPRESSIVITY = 1
# Deepgram closes an idle Flux WebSocket server-side; upstream's pool only
# expires by age since connect (max_session_duration=3600) and never checks
# whether the socket is already closed, so the first write after a long tutor
# silence fails and the retry speaks late. Drop anything idle past this and
# reconnect instead. Chosen with margin under the shortest silence that has
# ever preceded such a failure (56 s, production 2026-11-22).
WS_MAX_IDLE_SECONDS = 40.0
MIN_EXPRESSIVITY = -2
MAX_EXPRESSIVITY = 2


def parse_expressivity(raw: str | None) -> int:
    """Parse TUTOR_TTS_EXPRESSIVITY. Fail fast: never silently speak with another value."""
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError, AttributeError):
        raise ValueError(
            f"TUTOR_TTS_EXPRESSIVITY must be an integer "
            f"{MIN_EXPRESSIVITY}..{MAX_EXPRESSIVITY}, got {raw!r}"
        ) from None
    if not MIN_EXPRESSIVITY <= value <= MAX_EXPRESSIVITY:
        raise ValueError(
            f"TUTOR_TTS_EXPRESSIVITY must be an integer "
            f"{MIN_EXPRESSIVITY}..{MAX_EXPRESSIVITY}, got {raw!r}"
        )
    return value


def _ws_is_closed(ws: object) -> bool:
    """True when the server (or we) already closed this socket. Never raises."""
    return bool(getattr(ws, "closed", False))


class _IdleAwareConnectionPool(utils.ConnectionPool):
    """Upstream pool that also expires by idle time and drops closed sockets.

    Upstream tracks only age since connect, so a socket Deepgram dropped while
    the tutor was silent is still handed out until it is an hour old, and the
    first write fails. This tracks last use (put time, connect time before the
    first put) and discards whatever has been idle past ``idle_timeout`` or is
    already closed, reconnecting on the next checkout. Everything else --
    locking, draining, invalidate/prewarm/aclose, acquire-time reporting -- is
    inherited untouched, so the streaming path needs no other change.
    """

    def __init__(self, *args, idle_timeout: float = WS_MAX_IDLE_SECONDS, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._idle_timeout = idle_timeout
        self._last_used: dict = {}

    async def _connect(self, timeout: float):
        conn = await super()._connect(timeout)
        self._last_used[conn] = time.time()
        return conn

    async def get(self, *, timeout: float):
        # Mirrors upstream get(), plus: skip sockets the server already
        # closed and sockets idle longer than the server tolerates.
        async with self._connect_lock:
            await self._drain_to_close()
            now = time.time()
            while self._available:
                conn = self._available.pop()
                connected_at = self._connections.get(conn)
                if connected_at is None:
                    self._last_used.pop(conn, None)
                    continue
                if _ws_is_closed(conn):
                    self.remove(conn)
                    continue
                if (
                    self._max_session_duration is not None
                    and now - connected_at > self._max_session_duration
                ):
                    self.remove(conn)
                    continue
                if now - self._last_used.get(conn, connected_at) > self._idle_timeout:
                    self.remove(conn)
                    continue
                if self._mark_refreshed_on_get:
                    self._connections[conn] = now
                self.last_acquire_time = 0.0
                self.last_connection_reused = True
                return conn
            t0 = time.perf_counter()
            conn = await self._connect(timeout)
            self.last_acquire_time = time.perf_counter() - t0
            self.last_connection_reused = False
            return conn

    def put(self, conn) -> None:
        super().put(conn)
        if conn in self._connections:
            self._last_used[conn] = time.time()

    def remove(self, conn) -> None:
        self._last_used.pop(conn, None)
        super().remove(conn)

    def invalidate(self) -> None:
        self._last_used.clear()
        super().invalidate()


class DeepgramFluxTTS(TTSv2):
    """TTSv2 that also sends ``expressivity`` on the wire. Otherwise identical."""

    def __init__(self, *, expressivity: int | None = DEFAULT_EXPRESSIVITY, **kwargs) -> None:
        if expressivity is not None and (
            isinstance(expressivity, bool)
            or not isinstance(expressivity, int)
            or not MIN_EXPRESSIVITY <= expressivity <= MAX_EXPRESSIVITY
        ):
            raise ValueError(
                f"expressivity must be an integer {MIN_EXPRESSIVITY}..{MAX_EXPRESSIVITY}, "
                f"got {expressivity!r}"
            )
        super().__init__(**kwargs)
        # Upstream's pool is fresh (no connections yet), so replace it outright
        # with one that also drops idle/closed sockets before handing them out.
        self._pool = _IdleAwareConnectionPool(
            connect_cb=self._connect_ws,
            close_cb=self._close_ws,
            max_session_duration=3600,
            mark_refreshed_on_get=False,
        )
        self._expressivity = expressivity

    @property
    def expressivity(self) -> int | None:
        return self._expressivity

    async def _connect_ws(self, timeout: float) -> aiohttp.ClientWebSocketResponse:
        # Mirrors TTSv2._connect_ws, adding expressivity to the connection query.
        # Streaming only supports linear16 end-to-end; bit_rate stays batch-only.
        session = self._ensure_session()
        config: dict = {
            "encoding": self._opts.encoding,
            "model": self._opts.model,
            "sample_rate": self._opts.sample_rate,
            "mip_opt_out": self._opts.mip_opt_out,
        }
        if self._opts.speed is not None:
            config["speed"] = self._opts.speed
        if self._expressivity is not None:
            config["expressivity"] = self._expressivity
        ws = await asyncio.wait_for(
            session.ws_connect(
                _to_deepgram_url(config, self._opts.base_url, websocket=True),
                headers={"Authorization": f"Token {self._opts.api_key}"},
            ),
            timeout,
        )
        ws_headers = {
            k: v for k, v in ws._response.headers.items() if k.startswith("dg-") or k == "Date"
        }
        logger.debug(
            "Established new Deepgram Flux TTS WebSocket connection:",
            extra={"headers": ws_headers},
        )
        return ws

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> ChunkedStreamv2:
        return _ChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class _ChunkedStream(ChunkedStreamv2):
    """Batch synthesize that also sends ``expressivity`` per request."""

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        # Mirrors ChunkedStreamv2._run, adding expressivity to the request query.
        # Error mapping is unchanged: non-2xx raises APIStatusError, transport
        # failures raise APIConnectionError.
        try:
            http_params: dict = {
                "encoding": self._opts.encoding,
                "container": "none",
                "model": self._opts.model,
                "sample_rate": self._opts.sample_rate,
                "mip_opt_out": self._opts.mip_opt_out,
            }
            if self._opts.bit_rate is not None:
                http_params["bit_rate"] = self._opts.bit_rate
            if self._opts.speed is not None:
                http_params["speed"] = self._opts.speed
            expressivity = getattr(self._tts, "_expressivity", None)
            if expressivity is not None:
                http_params["expressivity"] = expressivity
            async with self._tts._ensure_session().post(
                _to_deepgram_url(http_params, self._opts.base_url, websocket=False),
                headers={
                    "Authorization": f"Token {self._tts._opts.api_key}",
                    "Content-Type": "application/json",
                },
                json={"text": self._input_text},
                timeout=aiohttp.ClientTimeout(total=30, sock_connect=self._conn_options.timeout),
            ) as resp:
                resp.raise_for_status()

                output_emitter.initialize(
                    request_id=utils.shortuuid(),
                    sample_rate=self._opts.sample_rate,
                    num_channels=NUM_CHANNELS,
                    mime_type=_encoding_to_mimetype(self._opts.encoding),
                )

                async for data, _ in resp.content.iter_chunks():
                    output_emitter.push(data)

                output_emitter.flush()

        except asyncio.TimeoutError:
            raise APITimeoutError() from None
        except aiohttp.ClientResponseError as e:
            raise APIStatusError(
                message=e.message, status_code=e.status, request_id=None, body=None
            ) from None
        except Exception as e:
            raise APIConnectionError() from e
