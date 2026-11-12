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
