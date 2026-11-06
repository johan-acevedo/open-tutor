"""Eleven v4 over the single-context text-to-dialogue WebSocket, against a local server.

The server replays a stream recorded from ElevenLabs (fixtures/elevenlabs_v4_dialogue.json,
fictional text) and records what the client sends, so the tests check the documented
protocol, caption timing on the real per-message alignment, errors and interruption.
"""

import asyncio
import base64
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest
from aiohttp import web
from livekit.agents import APIConnectOptions, APIStatusError
from livekit.agents.types import USERDATA_TIMED_TRANSCRIPT
from livekit.plugins import elevenlabs

from open_tutor import dialogue_tts
from open_tutor.agent import build_tts
from open_tutor.dialogue_tts import SAMPLE_RATE, DialogueTTS

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "elevenlabs_v4_dialogue.json").read_text())
BELLA = "hpp4J3VqNfWAUOO0d1Us"
NO_RETRY = APIConnectOptions(max_retry=0, timeout=5)


def replay(event: dict) -> str:
    """A recorded event as the server sent it (silence of the recorded length as audio)."""
    event = dict(event)
    if "audio_bytes" in event:
        event["audio"] = base64.b64encode(bytes(event.pop("audio_bytes"))).decode()
    return json.dumps(event)


class FakeElevenLabs:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.requests: list[web.Request] = []
        self.sent: list[dict] = []
        self.closed = asyncio.Event()

    async def handler(self, request):
        self.requests.append(request)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        try:
            await self.behaviour(self, ws)
        finally:
            self.closed.set()
        return ws

    async def next_message(self, ws) -> dict:
        message = await ws.receive()
        if message.type != aiohttp.WSMsgType.TEXT:
            raise ConnectionError("client closed")
        data = json.loads(message.data)
        self.sent.append(data)
        return data


@pytest.fixture
async def fake():
    servers = []

    async def start(behaviour):
        server = FakeElevenLabs(behaviour)
        app = web.Application()
        app.router.add_get("/v1/text-to-dialogue/stream-input", server.handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        servers.append(runner)
        session = aiohttp.ClientSession()
        servers.append(session)
        voice = DialogueTTS(api_key="test-key", voice_id=BELLA, base_url=f"ws://127.0.0.1:{port}/v1", http_session=session)
        return server, voice

    yield start
    for item in reversed(servers):
        await (item.cleanup() if isinstance(item, web.AppRunner) else item.close())


async def recorded_dialogue(server, ws):
    """Answer like ElevenLabs did: audio after each flush, is_final after close_socket."""
    events = iter(RECORDED["two_flushes"]["received"])
    while True:
        data = await server.next_message(ws)
        if data.get("flush"):
            for event in events:
                await ws.send_str(replay(event))
                if event.get("is_final_audio_for_turn"):
                    break
        if data.get("close_socket"):
            for event in events:
                await ws.send_str(replay(event))
            await ws.close()
            return


async def speak(voice, *pieces, conn_options=NO_RETRY):
    frames, words = [], []
    stream = voice.stream(conn_options=conn_options)
    for piece in pieces:
        stream.push_text(piece)
    stream.end_input()
    async for audio in stream:
        frames.append(audio.frame)
        words += audio.frame.userdata.get(USERDATA_TIMED_TRANSCRIPT) or []
    await stream.aclose()
    return frames, words


async def test_documented_protocol_and_captions_follow_the_audio(fake):
    server, voice = await fake(recorded_dialogue)
    frames, words = await speak(voice, "Bra jobbat! ", "Nu tar vi bort fem på båda sidor.")

    request = server.requests[0]
    query = parse_qs(urlparse(str(request.url)).query)
    assert request.path == "/v1/text-to-dialogue/stream-input"
    assert query["model_id"] == ["eleven_v4_turbo"]
    assert query["output_format"] == ["pcm_24000"] and query["sync_alignment"] == ["true"]
    assert query["language_code"] == ["sv"]
    assert request.headers["xi-api-key"] == "test-key"
    assert "test-key" not in str(request.url)

    # Exactly one registered voice first; every input names it; each sentence is flushed.
    assert server.sent[0] == {"voices": [BELLA]}
    inputs = [m for m in server.sent if "inputs" in m]
    assert all(m["inputs"][0]["voice_id"] == BELLA for m in inputs)
    assert "".join(m["inputs"][0]["text"] for m in inputs).split() == "Bra jobbat! Nu tar vi bort fem på båda sidor.".split()
    for i, message in enumerate(server.sent):
        if "inputs" in message:
            assert server.sent[i + 1] == {"flush": True}
    assert server.sent[-1] == {"close_socket": True}

    recorded_bytes = sum(e.get("audio_bytes", 0) for e in RECORDED["two_flushes"]["received"])
    played = sum(f.samples_per_channel for f in frames) / SAMPLE_RATE
    assert played == pytest.approx(recorded_bytes / (2 * SAMPLE_RATE), abs=0.02)

    # The caption is the spoken text, word by word, on the audio clock.
    assert "".join(str(w) for w in words).split() == "Bra jobbat! Nu tar vi bort fem på båda sidor.".split()
    starts = [w.start_time for w in words]
    assert starts == sorted(starts)
    assert all(w.end_time >= w.start_time for w in words)
    # Alignment restarts at 0 in every message: the second sentence must not jump back
    # to the start of the reply.
    first_turn = next(i for i, e in enumerate(RECORDED["two_flushes"]["received"]) if e.get("is_final_audio_for_turn"))
    first_turn_s = sum(e.get("audio_bytes", 0) for e in RECORDED["two_flushes"]["received"][:first_turn]) / (2 * SAMPLE_RATE)
    nu = next(w for w in words if str(w).strip() == "Nu")
    assert nu.start_time >= first_turn_s - 0.01
    # The recorded spans of the second turn run 80 ms past its audio.
    assert words[-1].end_time == pytest.approx(played, abs=0.1)


async def test_a_one_word_answer_is_flushed_at_once(fake):
    async def answer_only_after_flush(server, ws):
        while True:
            data = await server.next_message(ws)
            if data.get("flush"):
                break
        await ws.send_str(json.dumps({"audio": base64.b64encode(bytes(4800)).decode(),
                                      "alignment": {"chars": ["J", "a", "."], "char_start_times_ms": [0, 40, 80],
                                                    "char_durations_ms": [40, 40, 20]}}))
        await server.next_message(ws)  # close_socket
        await ws.send_str(json.dumps({"is_final": True}))
        await ws.close()

    server, voice = await fake(answer_only_after_flush)
    frames, words = await speak(voice, "Ja.")
    assert [m for m in server.sent if "inputs" in m][0]["inputs"][0]["text"].strip() == "Ja."
    assert frames and "".join(str(w) for w in words).strip() == "Ja."


async def test_provider_error_is_reported_not_retried(fake):
    async def reject_voice(server, ws):
        await server.next_message(ws)
        await ws.send_str(json.dumps(RECORDED["bad_voice"]["received"][0]))
        await ws.close()

    server, voice = await fake(reject_voice)
    with pytest.raises(APIStatusError) as error:
        await speak(voice, "Hej. ", conn_options=APIConnectOptions(max_retry=2, retry_interval=0.01, timeout=5))
    assert "voice_not_found" in str(error.value)
    assert error.value.retryable is False
    assert len(server.requests) == 1


async def test_interruption_closes_the_socket_and_no_audio_follows(fake):
    async def endless_reply(server, ws):
        await server.next_message(ws)
        while not ws.closed:
            await ws.send_str(json.dumps({"audio": base64.b64encode(bytes(960)).decode()}))
            await asyncio.sleep(0.01)

    server, voice = await fake(endless_reply)
    stream = voice.stream(conn_options=NO_RETRY)
    stream.push_text("Nu ska vi titta på en lång förklaring om bråk och decimaltal.")
    received = 0
    async for _ in stream:
        received += 1
        if received == 3:
            break
    await stream.aclose()  # what LiveKit does on a barge-in
    await asyncio.wait_for(server.closed.wait(), 2)
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(stream.__anext__(), 0.3)


async def test_keep_alive_while_the_reply_waits_for_text(fake, monkeypatch):
    monkeypatch.setattr(dialogue_tts, "KEEP_ALIVE_INTERVAL", 0.05)
    got_keep_alive = asyncio.Event()

    async def wait_for_keep_alive(server, ws):
        while not (await server.next_message(ws)).get("keep_alive"):
            pass
        got_keep_alive.set()
        await ws.close()

    server, voice = await fake(wait_for_keep_alive)
    stream = voice.stream(conn_options=NO_RETRY)
    consumer = asyncio.create_task(anext(aiter(stream), None))
    await asyncio.wait_for(got_keep_alive.wait(), 2)
    consumer.cancel()
    await stream.aclose()
    assert server.sent[0] == {"voices": [BELLA]}


def test_default_voice_is_v4_turbo_bella_and_flash_stays_on_the_plugin(monkeypatch):
    for name in ("TUTOR_TTS", "TUTOR_TTS_MODEL", "TUTOR_TTS_VOICE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    voice = build_tts()
    assert isinstance(voice, DialogueTTS)
    assert "/text-to-dialogue/stream-input model eleven_v4_turbo voice " + BELLA in voice.route()

    monkeypatch.setenv("TUTOR_TTS_MODEL", "eleven_flash_v2_5")
    assert isinstance(build_tts(), elevenlabs.TTS)
