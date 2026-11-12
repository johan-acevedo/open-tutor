"""ZonosTTS: pc2014 ZONOS3 batch speech over the documented /v2/generate route.

No live calls: a fake HTTP session records the POST and replays canned WAV or
error replies, so the tests check the payload (explicit Swedish voice +
embedding mode), the WAV decode (true 44100 Hz PCM, header never played as
audio), error surfacing (malformed, wrong format, non-2xx incl. 409), the
response-size bound, timeouts, and that cancellation is never wrapped.
"""

import asyncio
import io
import wave

import aiohttp
import pytest
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIError,
    APIStatusError,
)

from open_tutor.zonos_tts import (
    DEFAULT_BASE_URL,
    DEFAULT_VOICE,
    MAX_RESPONSE_BYTES,
    NUM_CHANNELS,
    READ_TIMEOUT,
    SAMPLE_RATE,
    ZonosTTS,
)

NO_RETRY = APIConnectOptions(max_retry=0, timeout=5)


def test_selected_zonos_route_uses_configured_host_and_voice(monkeypatch):
    from open_tutor.agent import build_tts
    monkeypatch.setenv("TUTOR_TTS", "zonos")
    monkeypatch.setenv("TUTOR_TTS_BASE_URL", DEFAULT_BASE_URL)
    monkeypatch.setenv("TUTOR_TTS_VOICE", DEFAULT_VOICE)
    engine = build_tts()
    assert isinstance(engine, ZonosTTS)
    assert engine.base_url == DEFAULT_BASE_URL
    assert engine.voice == DEFAULT_VOICE


def make_wav(
    *,
    rate=SAMPLE_RATE,
    channels=NUM_CHANNELS,
    sampwidth=2,
    seconds=0.1,
    payload: bytes | None = None,
) -> bytes:
    frames = payload if payload is not None else bytes(int(rate * seconds) * channels * sampwidth)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sampwidth)
        wav.setframerate(rate)
        wav.writeframes(frames)
    return buf.getvalue()


def pcm_of(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        return wav.readframes(wav.getnframes())


class FakePostResponse:
    def __init__(self, *, status=200, body=b"", chunks=None):
        self.status = status
        self._body = body
        self._chunks = chunks
        self.content = self
        self._consumed_error = False

    async def read(self, n=-1):
        return self._body[:n] if n >= 0 else self._body

    async def iter_chunked(self, n):
        if self._chunks is not None:
            for chunk in self._chunks:
                yield chunk
            return
        for i in range(0, len(self._body), n):
            yield self._body[i : i + n]


class FakePostCM:
    def __init__(self, session, status=200, body=b"", chunks=None, hang=False):
        self._session = session
        self._status = status
        self._body = body
        self._chunks = chunks
        self._hang = hang

    async def __aenter__(self):
        if self._hang:
            await asyncio.sleep(3600)
        return FakePostResponse(status=self._status, body=self._body, chunks=self._chunks)

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """Records POSTs; replays one canned reply (or hangs for cancellation tests)."""

    def __init__(self, *, status=200, body=b"", chunks=None, hang=False):
        self.posts: list[dict] = []
        self._status = status
        self._body = body
        self._chunks = chunks
        self._hang = hang

    def post(self, url, **kwargs):
        self.posts.append({"url": url, **kwargs})
        return FakePostCM(
            self, status=self._status, body=self._body, chunks=self._chunks, hang=self._hang
        )


class FakeEmitter:
    def __init__(self):
        self.initialized_kwargs: dict | None = None
        self.frames: list[bytes] = []
        self.flushed = False

    def initialize(self, **kwargs):
        self.initialized_kwargs = kwargs

    def push(self, data: bytes):
        self.frames.append(bytes(data))

    def flush(self):
        self.flushed = True


def engine_for(body=b"", **kwargs) -> tuple[ZonosTTS, FakeSession]:
    session = FakeSession(body=body, **kwargs.pop("session_kwargs", {}))
    return ZonosTTS(http_session=session, **kwargs), session


async def run_engine(
    engine: ZonosTTS, text="Hej du", conn_options: APIConnectOptions = NO_RETRY
) -> FakeEmitter:
    emitter = FakeEmitter()
    stream = engine.synthesize(text, conn_options=conn_options)
    try:
        await stream._run(emitter)
    finally:
        # Drop the ChunkedStream's own background attempt so a direct _run
        # never double-POSTs or leaves an unretrieved task exception behind.
        await stream.aclose()
    return emitter


def test_defaults_are_canonical_swedish_voice_on_pc2014():
    engine = ZonosTTS(http_session=FakeSession())
    assert engine.base_url == DEFAULT_BASE_URL == "https://pc2014.tail2e1c4e.ts.net:8448"
    assert engine.voice == DEFAULT_VOICE == "default_6c74e01948232c55"
    assert engine.provider == "ZONOS3"
    assert engine.model == "zonos3"
    assert engine.sample_rate == 44100
    assert engine.num_channels == 1
    assert engine.capabilities.streaming is False, "batch-only; LiveKit wraps a StreamAdapter"


@pytest.mark.parametrize("voice", ["", "   ", None, 123])
def test_empty_voice_fails_fast(voice):
    with pytest.raises(ValueError):
        ZonosTTS(voice=voice, http_session=FakeSession())


@pytest.mark.parametrize("text", ["", "   ", None, 123])
def test_empty_text_fails_fast(text):
    engine = ZonosTTS(http_session=FakeSession())
    with pytest.raises(ValueError):
        engine.synthesize(text, conn_options=NO_RETRY)


def test_bad_base_url_fails_fast():
    with pytest.raises(ValueError):
        ZonosTTS(base_url="  ", http_session=FakeSession())


async def test_payload_carries_explicit_voice_and_embedding_mode():
    wav = make_wav()
    engine, session = engine_for(wav)
    await run_engine(engine)
    (post,) = session.posts
    assert post["url"] == f"{DEFAULT_BASE_URL}/v2/generate"
    assert post["json"] == {
        "text": "Hej du",
        "speaker_embedding_id": DEFAULT_VOICE,
        "speaker_mode": "embedding",
        "stream": False,
        "format": "wav",
    }
    assert "Authorization" not in (post.get("headers") or {}), "tailnet-only, no auth"


async def test_custom_voice_and_base_url_reach_the_wire():
    wav = make_wav()
    engine, session = engine_for(
        wav, voice="custom_sv_123", base_url="https://other:8448/"
    )
    await run_engine(engine, text="God morgon")
    (post,) = session.posts
    assert post["url"] == "https://other:8448/v2/generate"
    assert post["json"]["speaker_embedding_id"] == "custom_sv_123"
    assert post["json"]["text"] == "God morgon"


async def test_wav_decodes_to_true_44100_pcm_without_header():
    pcm = bytes(range(256)) * 344  # 0.1 s of 16-bit mono 44100 Hz-ish bytes
    pcm = pcm[: int(44100 * 0.1) * 2]
    wav = make_wav(payload=pcm)
    engine, _ = engine_for(wav)
    emitter = await run_engine(engine)
    assert emitter.initialized_kwargs["sample_rate"] == 44100
    assert emitter.initialized_kwargs["num_channels"] == 1
    assert emitter.initialized_kwargs["mime_type"] == "audio/pcm"
    assert b"".join(emitter.frames) == pcm
    assert not any(wav[:44] in frame or frame.startswith(b"RIFF") for frame in emitter.frames), (
        "WAV header must be parsed, never played as audio"
    )
    assert emitter.flushed


@pytest.mark.parametrize(
    "wav_kwargs",
    [
        {"rate": 22050},
        {"rate": 48000},
        {"channels": 2},
        {"sampwidth": 1},
    ],
)
async def test_wrong_wav_format_is_a_clear_error(wav_kwargs):
    engine, _ = engine_for(make_wav(**wav_kwargs))
    with pytest.raises(APIError, match="unexpected WAV format"):
        await run_engine(engine)


async def test_malformed_body_is_a_clear_error():
    engine, _ = engine_for(b"this is not a wav file")
    with pytest.raises(APIError, match="valid WAV"):
        await run_engine(engine)


async def test_empty_wav_audio_is_a_clear_error():
    engine, _ = engine_for(make_wav(seconds=0))
    with pytest.raises(APIError, match="no audio"):
        await run_engine(engine)


@pytest.mark.parametrize("status", [400, 409, 429, 500])
async def test_non_2xx_surfaces_status_including_409(status):
    engine, _ = engine_for(b"busy", session_kwargs={"status": status})
    with pytest.raises(APIStatusError) as exc_info:
        await run_engine(engine)
    assert exc_info.value.status_code == status


async def test_connection_failure_surfaces_not_silenced():
    class RefusingSession:
        def post(self, url, **kwargs):
            raise aiohttp.ClientConnectionError("refused")

    engine = ZonosTTS(http_session=RefusingSession())
    with pytest.raises(APIConnectionError):
        await run_engine(engine)


async def test_oversize_response_is_bounded():
    big = b"\0" * (1024 * 1024)
    chunks = [big] * (MAX_RESPONSE_BYTES // len(big) + 1)
    engine, _ = engine_for(b"", session_kwargs={"chunks": chunks})
    with pytest.raises(APIError, match="exceeded"):
        await run_engine(engine)


async def test_timeouts_are_bounded_for_slow_cpu():
    seen: dict = {}

    class TimeoutSession:
        def post(self, url, **kwargs):
            seen.update(kwargs)
            raise asyncio.TimeoutError()

    from livekit.agents import APITimeoutError

    engine = ZonosTTS(http_session=TimeoutSession())
    with pytest.raises(APITimeoutError):
        await run_engine(engine)
    assert seen["timeout"].total == READ_TIMEOUT == 60.0
    assert seen["timeout"].sock_connect == 5


async def test_cancellation_is_never_wrapped():
    engine = ZonosTTS(http_session=FakeSession(hang=True))
    stream = engine.synthesize("hej", conn_options=NO_RETRY)
    try:
        task = asyncio.create_task(stream._run(FakeEmitter()))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await stream.aclose()
