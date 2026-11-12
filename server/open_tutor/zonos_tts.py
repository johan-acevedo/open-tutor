"""ZONOS3-Mini streaming TTS over plain HTTP (self-hosted, unmetered Swedish).

Talks to the ggml ``zonos3-server`` we run on the farm (pc2014 today,
johan-4070 as backup — same voice IDs on both)::

    POST {base_url}/v2/generate
    {"text", "stream": true, "format": "pcm", "speaker_embedding_id", "speaker_mode": "embedding"}

and converts the streamed float32 44.1 kHz mono PCM to int16 for LiveKit.
``synthesize()`` is implemented through ``stream()`` (one segment), so both
the sentence path and the live path share one code path.

Select it with ``TUTOR_TTS=zonos`` (see ``agent.build_tts``). Defaults speak
Swedish with the raeven voice; point at another box with
``TUTOR_TTS_ZONOS_URL`` and pick a voice from ``GET /v2/speakers`` with
``TUTOR_TTS_VOICE``. ``speaker_mode`` is always ``embedding``: the server's
reference mode needs encoder weights we deliberately do not ship, and
requests without a voice return silence.
"""

from __future__ import annotations

import asyncio
import json
import struct
import urllib.parse

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

# Farm defaults: pc2014's ZONOS3 endpoint + the Swedish raeven voice.
# johan-4070 serves the same voice IDs on :8447, so only the URL changes.
DEFAULT_BASE_URL = "https://pc2014.tail2e1c4e.ts.net:8448"
DEFAULT_VOICE = "default_6c74e01948232c55"  # raeven sv (Swedish+English)
SAMPLE_RATE = 44100
MODEL_NAME = "zonos3-mini"


def _clean_base_url(raw: str | None) -> str:
    if not raw or not raw.strip():
        raise ValueError("TUTOR_TTS_ZONOS_URL must be a non-empty URL")
    parsed = urllib.parse.urlparse(raw.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"TUTOR_TTS_ZONOS_URL must be an http(s) URL, got {raw!r}")
    return raw.strip().rstrip("/")


def _float32_to_int16_le(data: bytes, carry: bytearray) -> bytes:
    """Append raw bytes, drain whole float32 samples as int16 LE. Keeps tail in carry."""
    carry.extend(data)
    usable = (len(carry) // 4) * 4
    chunk = bytes(carry[:usable])
    del carry[:usable]
    if not chunk:
        return b""
    count = len(chunk) // 4
    samples = struct.unpack(f"<{count}f", chunk)
    return struct.pack(
        f"<{count}h",
        *(max(-32768, min(32767, round(s * 32767))) for s in samples),
    )


class ZonosTTS(tts.TTS):
    """LiveKit TTS backed by a self-hosted ZONOS3-Mini ggml server."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        voice: str = DEFAULT_VOICE,
        conn_timeout: float = 10.0,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
        )
        self._base_url = _clean_base_url(base_url)
        if not voice or not voice.strip():
            raise ValueError("ZonosTTS needs a speaker id (GET /v2/speakers)")
        self._voice = voice.strip()
        self._conn_timeout = conn_timeout
        self._session: aiohttp.ClientSession | None = None

    @property
    def provider(self) -> str:
        return "zonos"

    @property
    def model(self) -> str:
        return MODEL_NAME

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def voice(self) -> str:
        return self._voice

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def aclose(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        return self._synthesize_with_stream(text, conn_options=conn_options)

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.SynthesizeStream:
        return _ZonosStream(tts=self, conn_options=conn_options)


class _ZonosStream(tts.SynthesizeStream):
    """One /v2/generate request per flushed segment, streamed as int16 PCM."""

    def __init__(self, *, tts: ZonosTTS, conn_options: APIConnectOptions):
        super().__init__(tts=tts, conn_options=conn_options)
        self._tts: ZonosTTS = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            mime_type="audio/pcm",
            stream=True,
        )
        async for text, is_last in self._segments():
            if text.strip():
                await self._speak_segment(output_emitter, text)
            if is_last:
                break

    async def _segments(self):
        """Yield (text, is_last) per flushed segment from the framework input."""
        buf: list[str] = []
        async for ev in self._input_ch:
            if isinstance(ev, tts.SynthesizeStream._FlushSentinel):
                yield "".join(buf), False
                buf = []
            else:
                buf.append(ev)
        yield "".join(buf), True

    async def _speak_segment(self, output_emitter: tts.AudioEmitter, text: str) -> None:
        segment_id = utils.shortuuid("seg_")
        output_emitter.start_segment(segment_id=segment_id)
        payload = {
            "text": text,
            "stream": True,
            "format": "pcm",
            "seed": None,
            "speaker_embedding_id": self._tts.voice,
            "speaker_mode": "embedding",
        }
        carry = bytearray()
        resp: aiohttp.ClientResponse | None = None
        try:
            async with self._tts._ensure_session().post(
                f"{self._tts.base_url}/v2/generate",
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(
                    total=120, sock_connect=self._tts._conn_timeout
                ),
            ) as resp:
                resp.raise_for_status()
                async for data, _ in resp.content.iter_chunks():
                    pcm = _float32_to_int16_le(data, carry)
                    if pcm:
                        output_emitter.push(pcm)
            if carry:
                # Server closed mid-sample; pad rather than drop the tail.
                carry.extend(b"\x00" * (-len(carry) % 4))
                tail = _float32_to_int16_le(bytes(carry), bytearray())
                if tail:
                    output_emitter.push(tail)
            output_emitter.end_segment()
        except asyncio.CancelledError:
            # Barge-in: framework cancels us; close the HTTP stream and let it propagate.
            if resp is not None and not resp.closed:
                resp.release()
            raise
        except TimeoutError:
            raise APITimeoutError() from None
        except aiohttp.ClientResponseError as e:
            raise APIStatusError(
                message=e.message, status_code=e.status, request_id=None, body=None
            ) from None
        except Exception as e:
            raise APIConnectionError() from e
