"""Deepgram Flux TTS route: selected voice, expressivity on the wire, errors surface.

No live calls: a fake HTTP session records the streaming WebSocket URL and the
batch POST URL, and replays canned vendor messages for the word transport.
"""

import asyncio
import json
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest
from livekit.agents import APIConnectOptions, APIError, APIStatusError, tokenize

from open_tutor.agent import build_tts, tts_route
from open_tutor.deepgram_tts import (
    DEFAULT_EXPRESSIVITY,
    DEFAULT_MODEL,
    DeepgramFluxTTS,
)

NO_RETRY = APIConnectOptions(max_retry=0, timeout=5)


def deepgram_env(monkeypatch, **overrides):
    monkeypatch.setenv("TUTOR_TTS", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    for name in ("TUTOR_TTS_MODEL", "TUTOR_TTS_VOICE", "TUTOR_TTS_EXPRESSIVITY",
                 "ELEVENLABS_API_KEY", "ELEVEN_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)


def test_defaults_are_ludvig_swedish_with_expressivity_1(monkeypatch):
    deepgram_env(monkeypatch)
    assert DEFAULT_MODEL == "flux-ludvig-sv"
    assert DEFAULT_EXPRESSIVITY == 1
    engine = build_tts()
    assert isinstance(engine, DeepgramFluxTTS)
    assert engine.model == "flux-ludvig-sv"
    assert engine.expressivity == 1
    assert engine.sample_rate == 24000
    assert tts_route(engine) == "Deepgram flux-ludvig-sv"


def test_model_and_expressivity_override(monkeypatch):
    deepgram_env(monkeypatch, TUTOR_TTS_MODEL="flux-other-sv", TUTOR_TTS_EXPRESSIVITY="-2")
    engine = build_tts()
    assert engine.model == "flux-other-sv"
    assert engine.expressivity == -2


@pytest.mark.parametrize("raw", ["banana", "1.5", "3", "-3", ""])
def test_bad_expressivity_fails_fast(monkeypatch, raw):
    deepgram_env(monkeypatch, TUTOR_TTS_EXPRESSIVITY=raw)
    with pytest.raises(ValueError):
        build_tts()


class FakeSession:
    """Records request URLs; hands out fake sockets with canned vendor messages."""

    def __init__(self):
        self.ws_urls: list[str] = []
        self.ws_headers: list[dict] = []
        self.sockets: list["FakeWS"] = []
        self.post_urls: list[str] = []
        self.incoming: list = []

    async def ws_connect(self, url, headers=None):
        self.ws_urls.append(url)
        self.ws_headers.append(dict(headers or {}))
        ws = FakeWS(self.incoming)
        self.sockets.append(ws)
        return ws

    def post(self, url, **kwargs):
        self.post_urls.append(url)
        return FakePostCM()


class FakeWS:
    close_code = None

    def __init__(self, incoming):
        self.sent: list[dict] = []
        self._incoming = incoming
        self._response = FakeResponse()

    async def send_str(self, message: str):
        self.sent.append(json.loads(message))

    async def receive(self, timeout=None):
        if not self._incoming:
            raise asyncio.TimeoutError()
        return self._incoming.pop(0)

    async def close(self):
        pass


class FakeResponse:
    headers = {"Date": "thu, 01 jan 2026"}


class FakeMsg:
    def __init__(self, type, data="", extra=None):
        self.type = type
        self.data = data
        self.extra = extra


class FakePostCM:
    async def __aenter__(self):
        return FakePostResponse()

    async def __aexit__(self, *args):
        return False


class FakePostResponse:
    def raise_for_status(self):
        pass

    @property
    def content(self):
        return self

    async def iter_chunks(self):
        yield b"\x00\x01", False


class FakeEmitter:
    def __init__(self):
        self.frames: list[bytes] = []
        self.segments = 0
        self.ended = 0
        self.initialized = False

    def initialize(self, **kwargs):
        self.initialized = True

    def start_segment(self, segment_id=None):
        self.segments += 1

    def push(self, data: bytes):
        self.frames.append(bytes(data))

    def end_segment(self):
        self.ended += 1

    def flush(self):
        pass


def word_stream(text: str):
    words = tokenize.basic.WordTokenizer(ignore_punctuation=False).stream()
    words.push_text(text)
    words.end_input()
    return words


async def test_streaming_websocket_url_carries_model_and_expressivity():
    session = FakeSession()
    engine = DeepgramFluxTTS(model="flux-ludvig-sv", expressivity=1,
                             api_key="test-key", http_session=session)
    try:
        await engine._connect_ws(timeout=5)
    finally:
        await engine.aclose()
    (url,) = session.ws_urls
    parsed = urlparse(url)
    assert parsed.scheme == "wss"
    assert parsed.netloc == "api.deepgram.com"
    assert parsed.path == "/v2/speak"
    query = parse_qs(parsed.query)
    assert query["model"] == ["flux-ludvig-sv"]
    assert query["expressivity"] == ["1"], "requested expressivity must reach the socket"
    assert query["encoding"] == ["linear16"], "streaming stays linear16 PCM"
    assert session.ws_headers[0]["Authorization"] == "Token test-key"


async def test_streaming_url_defaults_to_plain_base_without_query():
    engine = DeepgramFluxTTS(api_key="test-key", http_session=FakeSession())
    try:
        assert "?" not in engine._opts.base_url
    finally:
        await engine.aclose()


async def test_streaming_sends_words_then_flush_and_pushes_audio():
    session = FakeSession()
    session.incoming.extend([
        FakeMsg(aiohttp.WSMsgType.BINARY, b"\x00\x01"),
        FakeMsg(aiohttp.WSMsgType.TEXT, json.dumps({"type": "SpeechMetadata"})),
    ])
    engine = DeepgramFluxTTS(model="flux-ludvig-sv", expressivity=1,
                             api_key="test-key", http_session=session)
    stream = engine.stream(conn_options=NO_RETRY)
    emitter = FakeEmitter()
    try:
        await stream._run_ws(word_stream("hej du"), emitter)
        (ws,) = session.sockets
        sent = list(ws.sent)  # snapshot: pool teardown appends Flush/Close after this
    finally:
        await stream.aclose()
        await engine.aclose()
    assert [m["type"] for m in sent] == ["Speak", "Speak", "Flush"]
    assert "".join(m.get("text", "") for m in sent if m["type"] == "Speak") == "hej du "
    assert emitter.segments == 1
    assert emitter.frames == [b"\x00\x01"]
    assert emitter.ended == 1, "SpeechMetadata authoritatively ends the turn"


async def test_streaming_vendor_error_surfaces_not_silenced():
    session = FakeSession()
    session.incoming.append(
        FakeMsg(aiohttp.WSMsgType.TEXT,
                json.dumps({"type": "Error", "description": "bad request"})))
    engine = DeepgramFluxTTS(api_key="test-key", http_session=session)
    stream = engine.stream(conn_options=NO_RETRY)
    try:
        with pytest.raises(APIError):
            await stream._run_ws(word_stream("hej"), FakeEmitter())
    finally:
        await stream.aclose()
        await engine.aclose()


async def test_streaming_unexpected_close_surfaces_status():
    session = FakeSession()
    session.incoming.append(FakeMsg(aiohttp.WSMsgType.CLOSED))
    engine = DeepgramFluxTTS(api_key="test-key", http_session=session)
    stream = engine.stream(conn_options=NO_RETRY)
    try:
        with pytest.raises(APIStatusError):
            await stream._run_ws(word_stream("hej"), FakeEmitter())
    finally:
        await stream.aclose()
        await engine.aclose()


async def test_batch_synthesize_url_carries_expressivity():
    session = FakeSession()
    engine = DeepgramFluxTTS(model="flux-ludvig-sv", expressivity=1,
                             api_key="test-key", http_session=session)
    emitter = FakeEmitter()
    try:
        await engine.synthesize("hej", conn_options=NO_RETRY)._run(emitter)
    finally:
        await engine.aclose()
    (url,) = session.post_urls
    query = parse_qs(urlparse(url).query)
    assert query["model"] == ["flux-ludvig-sv"]
    assert query["expressivity"] == ["1"]
    assert emitter.initialized
    assert emitter.frames == [b"\x00\x01"]
