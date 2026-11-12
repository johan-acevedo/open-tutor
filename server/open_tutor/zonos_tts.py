"""ZONOS3 Swedish speech from the pc2014 tailnet box (batch-only).

Smallest possible batch adapter over LiveKit 1.8.10's ``tts.TTS``: the framework
automatically wraps batch providers in a sentence ``StreamAdapter``, so this only
implements ``synthesize()`` and lets interruptions/cancellation flow through the
standard ``ChunkedStream`` machinery.

Wire protocol (pc2014 Zonos server, no auth, tailnet-only)::

    POST {base_url}/v2/generate
    {"text": ..., "speaker_embedding_id": <voice>, "speaker_mode": "embedding",
     "stream": false, "format": "wav"}

The voice and the embedding mode are always sent explicitly: with no voice the
server answers with silence, and anything but ``speaker_mode="embedding"``
is a 400. The reply is a PCM16 mono WAV at 44100 Hz, decoded here with stdlib
``wave`` (header validated, never played as audio) and pushed as raw PCM.

Error mapping follows the other adapters: non-2xx (including the vendor 409
busy signal) surfaces as ``APIStatusError`` and is left for the SDK retry
policy -- no custom retry loop here. Transport failures map to
``APIConnectionError``/``APITimeoutError``. ``CancelledError`` (an
interruption) is never wrapped.
"""

from __future__ import annotations

import asyncio
import io
import wave

import aiohttp
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIError,
    APIStatusError,
    APITimeoutError,
    tts,
    utils,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

# pc2014 on the tailnet; plain HTTP(S), no key. Tailnet-only, never exposed.
DEFAULT_BASE_URL = "https://pc2014.tail2e1c4e.ts.net:8448"
GENERATE_PATH = "/v2/generate"
# Canonical Swedish voice embedding. Never omit it: the server answers silence.
DEFAULT_VOICE = "default_6c74e01948232c55"
SPEAKER_MODE = "embedding"

SAMPLE_RATE = 44100
NUM_CHANNELS = 1
# CPU sentences normally take ~2.5 s but long ones may need up to 60 s of read.
READ_TIMEOUT = 60.0
# Upper bound on the buffered response body; a runaway server must not OOM us.
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_CHUNK_SIZE = 64 * 1024


class ZonosTTS(tts.TTS):
    """Batch-only Swedish TTS served by ZONOS3 on pc2014."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        voice: str = DEFAULT_VOICE,
        http_session: aiohttp.ClientSession | None = None,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError(f"ZonosTTS needs a non-empty base_url, got {base_url!r}")
        if not isinstance(voice, str) or not voice.strip():
            raise ValueError(
                "ZonosTTS needs a non-empty voice (speaker_embedding_id); "
                f"got {voice!r}"
            )
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )
        self._base_url = base_url.rstrip("/")
        self._voice = voice
        self._session = http_session

    @property
    def model(self) -> str:
        return "zonos3"

    @property
    def provider(self) -> str:
        return "ZONOS3"

    @property
    def voice(self) -> str:
        return self._voice

    @property
    def base_url(self) -> str:
        return self._base_url

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is not None:
            return self._session
        return utils.http_context.http_session()

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"ZonosTTS needs non-empty text, got {text!r}")
        return _ChunkedStream(tts=self, input_text=text, conn_options=conn_options)


def _decode_wav(body: bytes) -> bytes:
    """Return the raw PCM16 mono 44100 Hz frames of a Zonos WAV reply.

    The header is parsed and validated with stdlib ``wave`` -- never passed
    through as audio. Anything but exactly PCM16/mono/44100 Hz is a bad
    response, not something to resample silently.
    """
    try:
        with wave.open(io.BytesIO(body), "rb") as wav:
            channels = wav.getnchannels()
            sampwidth = wav.getsampwidth()
            framerate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError, ValueError) as e:
        raise APIError(f"ZonosTTS did not return a valid WAV file: {e}", retryable=False) from e
    if channels != NUM_CHANNELS or sampwidth != 2 or framerate != SAMPLE_RATE:
        raise APIError(
            "ZonosTTS returned unexpected WAV format: "
            f"{channels}ch/{sampwidth * 8}bit/{framerate}Hz, "
            f"expected 1ch/16bit/{SAMPLE_RATE}Hz",
            retryable=False,
        )
    if not frames:
        raise APIError("ZonosTTS returned a WAV file with no audio", retryable=False)
    return frames


class _ChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        zonos: ZonosTTS = self._tts  # type: ignore[assignment]
        url = f"{zonos.base_url}{GENERATE_PATH}"
        payload = {
            "text": self._input_text,
            "speaker_embedding_id": zonos.voice,
            "speaker_mode": SPEAKER_MODE,
            "stream": False,
            "format": "wav",
        }
        try:
            async with zonos._ensure_session().post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(
                    total=READ_TIMEOUT, sock_connect=self._conn_options.timeout
                ),
            ) as resp:
                if resp.status < 200 or resp.status >= 300:
                    detail = (await resp.content.read(4096)).decode("utf-8", "replace")
                    raise APIStatusError(
                        f"ZonosTTS {url} answered {resp.status}: {detail[:500]}",
                        status_code=resp.status,
                    )
                body = bytearray()
                async for chunk in resp.content.iter_chunked(_CHUNK_SIZE):
                    body += chunk
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise APIError(
                            f"ZonosTTS response exceeded {MAX_RESPONSE_BYTES} bytes",
                            retryable=False,
                        )
        except asyncio.CancelledError:
            raise
        except APIError:
            raise
        except asyncio.TimeoutError as e:
            raise APITimeoutError(f"ZonosTTS {url} timed out") from e
        except aiohttp.ClientResponseError as e:
            raise APIStatusError(
                message=str(e), status_code=e.status or -1, request_id=None, body=None
            ) from e
        except aiohttp.ClientError as e:
            raise APIConnectionError(f"ZonosTTS {url} connection failed: {e}") from e

        pcm = _decode_wav(bytes(body))
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
            mime_type="audio/pcm",
        )
        output_emitter.push(pcm)
        output_emitter.flush()
