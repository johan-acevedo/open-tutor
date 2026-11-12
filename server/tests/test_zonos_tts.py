"""Zonos streaming TTS: conversion, wire format, errors, selection.

No live calls: a local aiohttp server replays canned float32 PCM (split
mid-sample on purpose) and records request bodies.
"""

import struct

import pytest
from aiohttp import web
from livekit.agents import APIConnectOptions, APIStatusError

from open_tutor.agent import build_tts, tts_route
from open_tutor.zonos_tts import (
    DEFAULT_BASE_URL,
    DEFAULT_VOICE,
    MODEL_NAME,
    ZonosTTS,
    _float32_to_int16_le,
)

NO_RETRY = APIConnectOptions(max_retry=0, timeout=5)


def zonos_env(monkeypatch, **overrides):
    monkeypatch.setenv("TUTOR_TTS", "zonos")
    for name in ("TUTOR_TTS_MODEL", "TUTOR_TTS_VOICE", "TUTOR_TTS_ZONOS_URL",
                 "TUTOR_TTS_EXPRESSIVITY", "DEEPGRAM_API_KEY",
                 "ELEVENLABS_API_KEY", "ELEVEN_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)


def test_defaults_point_at_pc2014_raeven(monkeypatch):
    zonos_env(monkeypatch)
    engine = build_tts()
    assert isinstance(engine, ZonosTTS)
    assert engine.base_url == DEFAULT_BASE_URL
    assert engine.voice == DEFAULT_VOICE
    assert engine.model == MODEL_NAME
    assert engine.provider == "zonos"
    assert engine.sample_rate == 44100
    assert engine.capabilities.streaming is True
    assert tts_route(engine) == "zonos zonos3-mini"


def test_url_and_voice_override(monkeypatch):
    zonos_env(monkeypatch, TUTOR_TTS_ZONOS_URL="http://x:1919/",
              TUTOR_TTS_VOICE="default_abc")
    engine = build_tts()
    assert engine.base_url == "http://x:1919"
    assert engine.voice == "default_abc"


@pytest.mark.parametrize("raw", ["", "notaurl", "ftp://x/y"])
def test_bad_url_fails_fast(monkeypatch, raw):
    zonos_env(monkeypatch, TUTOR_TTS_ZONOS_URL=raw)
    with pytest.raises(ValueError):
        build_tts()


def test_float32_to_int16_with_mid_sample_split():
    samples = [0.0, 0.5, -0.5, 1.0, -1.0, 2.0, -2.0]
    raw = struct.pack(f"<{len(samples)}f", *samples)
    carry = bytearray()
    # Feed 3 bytes at a time: every boundary splits a sample.
    out = b"".join(
        _float32_to_int16_le(raw[i:i + 3], carry) for i in range(0, len(raw), 3)
    )
    assert carry == b""
    assert out == struct.pack("<7h", 0, 16384, -16384, 32767, -32767, 32767, -32768)


class FakeEmitter:
    def __init__(self):
        self.calls: list[tuple] = []

    def start_segment(self, *, segment_id: str) -> None:
        self.calls.append(("start", segment_id))

    def push(self, data: bytes) -> None:
        self.calls.append(("push", bytes(data)))

    def end_segment(self) -> None:
        self.calls.append(("end",))


async def _serve(handler):
    app = web.Application()
    app.router.add_post("/v2/generate", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    addr = runner.addresses[0]
    port = addr.rpartition(":")[2] if isinstance(addr, str) else addr[1]
    return runner, f"http://127.0.0.1:{port}"


async def test_speak_segment_converts_and_segments():
    bodies = []

    async def handler(request):
        bodies.append(await request.json())
        resp = web.StreamResponse()
        await resp.prepare(request)
        pcm = struct.pack("<4f", 0.0, 0.5, -0.5, 0.25)
        await resp.write(pcm[:5])
        await resp.write(pcm[5:])
        await resp.write_eof()
        return resp

    runner, url = await _serve(handler)
    try:
        engine = ZonosTTS(base_url=url, voice="default_test")
        stream = engine.stream(conn_options=NO_RETRY)
        emitter = FakeEmitter()
        try:
            await stream._speak_segment(emitter, "hej")
        finally:
            await stream.aclose()
            await engine.aclose()
    finally:
        await runner.cleanup()
    assert len(bodies) == 1
    assert bodies[0]["text"] == "hej"
    kinds = [c[0] for c in emitter.calls]
    assert kinds[0] == "start" and kinds[-1] == "end"
    audio = b"".join(c[1] for c in emitter.calls if c[0] == "push")
    assert audio == struct.pack("<4h", 0, 16384, -16384, 8192)


async def test_server_error_becomes_api_status_error():
    async def handler(request):
        return web.Response(status=500, text="boom")

    runner, url = await _serve(handler)
    try:
        engine = ZonosTTS(base_url=url, voice="default_test")
        stream = engine.stream(conn_options=NO_RETRY)
        emitter = FakeEmitter()
        try:
            with pytest.raises(APIStatusError):
                await stream._speak_segment(emitter, "hej")
        finally:
            await stream.aclose()
            await engine.aclose()
    finally:
        await runner.cleanup()
