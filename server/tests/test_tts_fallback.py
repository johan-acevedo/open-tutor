"""Tests for Google Cloud Chirp 3: HD builder and session-sticky TTS failover."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import stat
import struct
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import aiohttp

from google.auth.credentials import Credentials as GoogleCredentials
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from livekit import rtc
from livekit.agents import (
    Agent,
    APIConnectionError,
    APIConnectOptions,
    APIError,
    APIStatusError,
    ModelSettings,
    tts,
    utils,
)
from livekit.agents.types import USERDATA_TIMED_TRANSCRIPT
from livekit.agents.voice.io import TimedString
from livekit.plugins import google

from open_tutor.agent import build_tts, tts_route
from open_tutor.dialogue_tts import DialogueTTS
from livekit.plugins import cartesia
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from livekit.agents.telemetry import traces as lk_traces
from open_tutor.fillers import (
    SPECS,
    FillerClips,
    Fillers,
    clip_directory,
    voice_fingerprint,
    write_wav,
)
from open_tutor.tts_fallback import (
    DEFAULT_GOOGLE_VOICE,
    CooldownLedger,
    FallbackTTS,
    build_google_tts,
    is_quota_or_auth_error,
    parse_cooldown_s,
    reset_cooldowns,
)

NO_RETRY = APIConnectOptions(max_retry=0, timeout=5)
RETRY_TWICE = APIConnectOptions(max_retry=2, retry_interval=0.0, timeout=5)


def _make_valid_sa_json() -> str:
    """Generate a structurally valid ephemeral RSA-2048 GCP service account JSON."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "test-proj",
            "private_key_id": "k1",
            "private_key": pem,
            "client_email": "talarum-tts@test-proj.iam.gserviceaccount.com",
            "client_id": "1234567890",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


SAMPLE_SA = _make_valid_sa_json()


@pytest.fixture(autouse=True)
def _clean_cooldowns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TUTOR_TTS_COOLDOWN_FILE", str(tmp_path / "tts-cooldowns.json"))
    reset_cooldowns()
    yield
    reset_cooldowns()


class FakeTTS(tts.TTS):
    """Controllable in-memory TTS double for streaming and batch synthesis."""

    def __init__(
        self,
        *,
        provider: str = "FakePrimary",
        model: str = "m1",
        voice_id: str = "v1",
        aligned: bool = True,
        sample_rate: int = 24000,
        fail_with: BaseException | None = None,
        fail_after_frame: bool = False,
        pcm_byte: int = 1,
        frame_bytes: int = 960,
        emit_audio: bool = True,
        start_delay_s: float = 0.0,
        tone_amplitude: int = 0,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True, aligned_transcript=aligned),
            sample_rate=sample_rate,
            num_channels=1,
        )
        self._provider = provider
        self._model = model
        self.voice_id = voice_id
        self.fail_with = fail_with
        self.fail_after_frame = fail_after_frame
        self.pcm_byte = pcm_byte
        self.frame_bytes = frame_bytes
        self.emit_audio = emit_audio
        self.start_delay_s = start_delay_s
        self.tone_amplitude = tone_amplitude
        self.seen_texts: list[str] = []
        self.calls = 0
        self.closed = False

    def _payload(self) -> bytes:
        if self.tone_amplitude > 0:
            # 300 ms loud square wave that passes filler clip_problem() checks.
            samples = int(0.30 * self.sample_rate)
            vals = [
                self.tone_amplitude if (i // 20) % 2 == 0 else -self.tone_amplitude
                for i in range(samples)
            ]
            return struct.pack(f"<{samples}h", *vals)
        return bytes([self.pcm_byte]) * self.frame_bytes

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    def synthesize(self, text: str, *, conn_options: APIConnectOptions = NO_RETRY) -> tts.ChunkedStream:
        return _FakeChunked(tts=self, input_text=text, conn_options=conn_options)

    def stream(self, *, conn_options: APIConnectOptions = NO_RETRY) -> tts.SynthesizeStream:
        return _FakeStream(tts=self, conn_options=conn_options)

    async def aclose(self) -> None:
        self.closed = True


class _FakeChunked(tts.ChunkedStream):
    def __init__(self, *, tts: FakeTTS, input_text: str, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._fake = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        self._fake.calls += 1
        self._fake.seen_texts.append(self._input_text)
        if self._fake.fail_with and not self._fake.fail_after_frame:
            raise self._fake.fail_with
        output_emitter.initialize(
            request_id=utils.shortuuid(),
            sample_rate=self._fake.sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
        )
        if self._fake.emit_audio:
            output_emitter.push(self._fake._payload())
        if self._fake.fail_with and self._fake.fail_after_frame:
            output_emitter.flush()
            await asyncio.sleep(0.02)
            raise self._fake.fail_with
        output_emitter.flush()


class _FakeStream(tts.SynthesizeStream):
    def __init__(self, *, tts: FakeTTS, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts, conn_options=conn_options)
        self._fake = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        self._fake.calls += 1
        collected = []
        async for item in self._input_ch:
            if not isinstance(item, self._FlushSentinel):
                collected.append(item)
        full_text = "".join(collected)
        self._fake.seen_texts.append(full_text)
        if self._fake.start_delay_s > 0:
            await asyncio.sleep(self._fake.start_delay_s)
        self._mark_started()
        if self._fake.fail_with and not self._fake.fail_after_frame:
            raise self._fake.fail_with
        req_id = utils.shortuuid()
        output_emitter.initialize(
            request_id=req_id,
            sample_rate=self._fake.sample_rate,
            num_channels=1,
            stream=True,
            mime_type="audio/pcm",
        )
        output_emitter.start_segment(segment_id=req_id)
        if self._fake.emit_audio:
            output_emitter.push(self._fake._payload())
        if self._fake.capabilities.aligned_transcript and full_text.strip():
            output_emitter.push_timed_transcript(
                [TimedString(text=full_text.strip(), start_time=0.0, end_time=0.2)]
            )
        if self._fake.fail_with and self._fake.fail_after_frame:
            output_emitter.flush()
            await asyncio.sleep(0.05)
            raise self._fake.fail_with
        output_emitter.end_segment()


async def collect_stream(
    engine: tts.TTS,
    *pieces: str,
    conn_options: APIConnectOptions = NO_RETRY,
) -> tuple[list[rtc.AudioFrame], list[TimedString]]:
    frames, words = [], []
    stream = engine.stream(conn_options=conn_options)
    for piece in pieces:
        stream.push_text(piece)
    stream.flush()
    stream.end_input()
    try:
        async for ev in stream:
            if ev.frame:
                frames.append(ev.frame)
                if ev.frame.userdata:
                    words.extend(ev.frame.userdata.get(USERDATA_TIMED_TRANSCRIPT) or [])
    finally:
        await stream.aclose()
    return frames, words


# ---- primary happy path & aligned captions ----------------------------------


async def test_primary_happy_path_keeps_word_synced_captions():
    primary = FakeTTS(provider="ElevenLabs", model="eleven_v4_turbo", voice_id="bella", aligned=True, pcm_byte=7)
    fallback = FakeTTS(provider="Google Cloud Platform", model="chirp_3", voice_id="aoede", aligned=False, pcm_byte=9)
    engine = FallbackTTS(primary, fallback)

    assert engine.capabilities.aligned_transcript is True
    assert engine.active_engine is primary
    frames, words = await collect_stream(engine, "Hej ", "Alva!")

    assert frames and bytes(frames[0].data)[0] == 7
    assert [str(w) for w in words] == ["Hej Alva!"]
    assert primary.calls == 1 and fallback.calls == 0
    assert engine.stats_for_analytics() == {
        "tts_fallback_armed": True,
        "tts_started_on_fallback": False,
        "tts_failovers": 0,
        "tts_served_by": {"ElevenLabs": 1},
    }
    await engine.aclose()
    assert primary.closed and fallback.closed


# ---- mid-turn failover, session stickiness, and cooldown --------------------


async def test_quota_error_fails_over_mid_turn_sticks_and_trips_cooldown():
    now = [100.0]
    ledger = CooldownLedger(clock=lambda: now[0])
    quota_err = APIStatusError(
        "ElevenLabs text-to-dialogue: quota_exceeded: Out of credits",
        status_code=1008,
        retryable=False,
    )
    primary = FakeTTS(provider="ElevenLabs", model="eleven_v4_turbo", voice_id="bella", aligned=True, fail_with=quota_err, pcm_byte=7)
    fallback = FakeTTS(provider="Google Cloud Platform", model="chirp_3", voice_id="aoede", aligned=False, pcm_byte=9)
    engine = FallbackTTS(primary, fallback, cooldown_s=600.0, cooldowns=ledger)

    # First utterance: primary fails before audio -> seamlessly replayed on fallback.
    frames1, words1 = await collect_stream(engine, "Bra ", "jobbat!")
    assert frames1 and bytes(frames1[0].data)[0] == 9
    assert words1 == []
    assert fallback.seen_texts == ["Bra jobbat!"]
    assert engine.using_fallback is True
    assert engine.active_engine is fallback
    # Capability refreshed immediately so subsequent turns do not wait for aligned transcripts.
    assert engine.capabilities.aligned_transcript is False

    # Second utterance in same session: sticks to fallback without hitting primary again.
    frames2, _ = await collect_stream(engine, "Nästa uppgift.")
    assert frames2 and bytes(frames2[0].data)[0] == 9
    assert primary.calls == 1
    assert fallback.calls == 2
    assert engine.stats_for_analytics()["tts_failovers"] == 1
    assert engine.stats_for_analytics()["tts_served_by"] == {"Google Cloud Platform": 2}

    # New session during cooldown starts directly on fallback with matching capabilities.
    primary2 = FakeTTS(provider="ElevenLabs", model="eleven_v4_turbo", voice_id="bella", aligned=True, pcm_byte=7)
    fallback2 = FakeTTS(provider="Google Cloud Platform", model="chirp_3", voice_id="aoede", aligned=False, pcm_byte=9)
    engine2 = FallbackTTS(primary2, fallback2, cooldown_s=600.0, cooldowns=ledger)
    assert engine2.using_fallback is True
    assert engine2.capabilities.aligned_transcript is False
    assert "cooling down" in engine2.route()
    frames3, _ = await collect_stream(engine2, "Hej igen!")
    assert bytes(frames3[0].data)[0] == 9
    assert primary2.calls == 0 and fallback2.calls == 1

    # Once cooldown expires, a fresh session tries primary again.
    now[0] += 601.0
    primary3 = FakeTTS(provider="ElevenLabs", model="eleven_v4_turbo", voice_id="bella", aligned=True, pcm_byte=7)
    fallback3 = FakeTTS(provider="Google Cloud Platform", model="chirp_3", voice_id="aoede", aligned=False, pcm_byte=9)
    engine3 = FallbackTTS(primary3, fallback3, cooldown_s=600.0, cooldowns=ledger)
    assert engine3.using_fallback is False
    assert engine3.capabilities.aligned_transcript is True


def test_cooldown_persists_across_separate_job_processes(tmp_path: Path):
    """LiveKit AgentServer spawns a fresh OS process per call on Linux."""
    cooldown_file = tmp_path / "shared-cooldown.json"
    env = {**os.environ, "TUTOR_TTS_COOLDOWN_FILE": str(cooldown_file)}
    cwd = str(Path(__file__).resolve().parent.parent)

    proc1_code = (
        "from livekit.agents import APIStatusError\n"
        "from open_tutor.tts_fallback import CooldownLedger, default_cooldown_path\n"
        "ledger = CooldownLedger(path=default_cooldown_path())\n"
        "ledger.trip('ElevenLabs eleven_v4_turbo bella', 600.0)\n"
    )
    res1 = subprocess.run([sys.executable, "-c", proc1_code], env=env, cwd=cwd, capture_output=True, text=True)
    assert res1.returncode == 0, res1.stderr
    assert cooldown_file.is_file()
    assert stat.S_IMODE(cooldown_file.stat().st_mode) == 0o600

    proc2_code = (
        "from open_tutor.tts_fallback import CooldownLedger, default_cooldown_path\n"
        "ledger = CooldownLedger(path=default_cooldown_path())\n"
        "assert ledger.is_cooling_down('ElevenLabs eleven_v4_turbo bella')\n"
        "assert ledger.remaining_s('ElevenLabs eleven_v4_turbo bella') > 500.0\n"
    )
    res2 = subprocess.run([sys.executable, "-c", proc2_code], env=env, cwd=cwd, capture_output=True, text=True)
    assert res2.returncode == 0, res2.stderr


async def test_transient_error_sticks_in_session_without_poisoning_next_session():
    ledger = CooldownLedger(clock=lambda: 100.0)
    primary = FakeTTS(
        provider="ElevenLabs",
        model="eleven_v4_turbo",
        voice_id="bella",
        fail_with=APIConnectionError("temporary network blip"),
    )
    fallback = FakeTTS(provider="Google Cloud Platform", model="chirp_3", voice_id="aoede", aligned=False, pcm_byte=9)
    engine = FallbackTTS(primary, fallback, cooldown_s=600.0, cooldowns=ledger)

    frames, _ = await collect_stream(engine, "Test")
    assert bytes(frames[0].data)[0] == 9
    assert engine.using_fallback is True

    next_engine = FallbackTTS(
        FakeTTS(provider="ElevenLabs", model="eleven_v4_turbo", voice_id="bella"),
        FakeTTS(provider="Google Cloud Platform", model="chirp_3", voice_id="aoede", aligned=False),
        cooldown_s=600.0,
        cooldowns=ledger,
    )
    assert next_engine.using_fallback is False


# ---- P1 #1: error sanitization (no spoken text in logs) ---------------------


async def test_provider_errors_never_leak_spoken_text_into_logs(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG)
    marker_body = "HEMLIG_BARN_FRAS_12345"
    marker_empty = "HEMLIG_TOM_AUDIO_67890"

    bad_status = APIStatusError(
        f"Provider rejected {marker_body}",
        status_code=503,
        body={"detail": f"failed while speaking {marker_body}"},
        retryable=True,
    )
    primary = FakeTTS(provider="ElevenLabs", fail_with=bad_status)
    fallback = FakeTTS(provider="Google Cloud Platform", fail_with=bad_status, aligned=False)
    engine = FallbackTTS(primary, fallback)

    # Streaming path with retries enabled
    with pytest.raises(APIStatusError) as stream_exc:
        await collect_stream(engine, f"Säg {marker_body}", conn_options=RETRY_TWICE)
    assert marker_body not in str(stream_exc.value)
    assert stream_exc.value.body is None
    assert stream_exc.value.__cause__ is None
    assert stream_exc.value.status_code == 503

    # Batch path with retries enabled
    with pytest.raises(APIStatusError) as batch_exc:
        stream = engine.synthesize(f"Säg {marker_body}", conn_options=RETRY_TWICE)
        try:
            async for _ in stream:
                pass
        finally:
            await stream.aclose()
    assert marker_body not in str(batch_exc.value)
    assert batch_exc.value.body is None
    assert batch_exc.value.__cause__ is None

    # Empty audio on non-empty text must also never leak spoken text via LiveKit's fallback error
    empty_primary = FakeTTS(provider="ElevenLabs", emit_audio=False)
    empty_fallback = FakeTTS(provider="Google Cloud Platform", emit_audio=False, aligned=False)
    empty_engine = FallbackTTS(empty_primary, empty_fallback)
    with pytest.raises(APIConnectionError) as empty_exc:
        await collect_stream(empty_engine, marker_empty, conn_options=RETRY_TWICE)
    assert marker_empty not in str(empty_exc.value)

    logged_messages = "\n".join(rec.getMessage() for rec in caplog.records)
    logged_fields = "\n".join(repr(rec.__dict__) for rec in caplog.records)
    assert marker_body not in logged_messages
    assert marker_body not in logged_fields
    assert marker_empty not in logged_messages
    assert marker_empty not in logged_fields


async def test_inner_spans_and_cartesia_structured_logs_never_leak_spoken_text(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    """Sanitizing inside child._run keeps spoken text out of LiveKit's inner
    OpenTelemetry exception spans, and the plugin filter scrubs Cartesia extras."""
    caplog.set_level(logging.DEBUG)
    marker = "HEMLIG_SPAN_OCH_EXTRA_4242"

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(lk_traces, "tracer", provider.get_tracer("test-tts"))
    # Also patch the module-level tracer imported directly in livekit.agents.tts.tts.
    from livekit.agents.tts import tts as lk_tts_mod

    monkeypatch.setattr(lk_tts_mod, "tracer", provider.get_tracer("test-tts"))

    raw_err = APIStatusError(
        f"Google rejected {marker}",
        status_code=503,
        body={"detail": f"echo {marker}"},
        retryable=False,
    )
    primary = FakeTTS(provider="ElevenLabs", fail_with=raw_err)
    fallback = FakeTTS(provider="Google Cloud Platform", aligned=False, fail_with=raw_err)
    engine = FallbackTTS(primary, fallback)

    with pytest.raises(APIStatusError):
        await collect_stream(engine, f"Säg {marker}", conn_options=NO_RETRY)

    for span in exporter.get_finished_spans():
        for event in span.events:
            assert marker not in repr(dict(event.attributes or {})), event
        attrs = dict(span.attributes or {})
        for k, v in attrs.items():
            # LiveKit's own gen_ai input attribute is only set on success; exception
            # spans must never carry provider error text.
            if k != "tts.input_text":
                assert marker not in repr(v), (k, v)

    # Cartesia structured payload fields are scrubbed by the attached plugin filter.
    logging.getLogger("livekit.plugins.cartesia").error(
        "Cartesia returned error.",
        extra={"error": {"message": f"failed on {marker}"}, "lk.pii.data": marker},
    )
    for rec in caplog.records:
        assert marker not in rec.getMessage()
        assert marker not in repr(rec.__dict__)


async def test_dialogue_batch_nested_stream_and_empty_pcm_never_leak_into_spans(
    monkeypatch: pytest.MonkeyPatch,
):
    """Bella's batch synthesize() uses _synthesize_with_stream (a nested stream),
    and empty PCM on non-empty text used to hit LiveKit's request-span error.
    Neither path may leak spoken text into OpenTelemetry spans."""
    marker_err = "HEMLIG_BATCH_NESTED_777"
    marker_empty = "HEMLIG_EMPTY_SPAN_888"

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    from livekit.agents.tts import tts as lk_tts_mod

    monkeypatch.setattr(lk_traces, "tracer", provider.get_tracer("test-tts-batch"))
    monkeypatch.setattr(lk_tts_mod, "tracer", provider.get_tracer("test-tts-batch"))

    class _ErrWS:
        closed = False
        close_code = None

        async def send_str(self, payload: str) -> None:
            pass

        async def receive(self):
            return SimpleNamespace(
                type=aiohttp.WSMsgType.TEXT,
                data=json.dumps(
                    {"error": "bad_request", "message": f"failed on {marker_err}", "code": 400}
                ),
            )

        async def close(self) -> None:
            self.closed = True

    class _ErrSession:
        async def ws_connect(self, *args, **kwargs):
            return _ErrWS()

    bella = DialogueTTS(
        api_key="el-test",
        voice_id="hpp4J3VqNfWAUOO0d1Us",
        model="eleven_v4_turbo",
        http_session=_ErrSession(),
    )
    fb_fail = FakeTTS(
        provider="Google Cloud Platform",
        aligned=False,
        fail_with=APIStatusError(f"rejected {marker_err}", status_code=503, retryable=False),
    )
    eng = FallbackTTS(bella, fb_fail, cooldowns=CooldownLedger())
    with pytest.raises(APIError):
        s = eng.synthesize(f"Säg {marker_err}", conn_options=NO_RETRY)
        try:
            async for _ in s:
                pass
        finally:
            await s.aclose()

    # Empty PCM on non-empty text (both primary and fallback produce 0 PCM).
    empty_eng = FallbackTTS(
        FakeTTS(provider="ElevenLabs", emit_audio=False),
        FakeTTS(provider="Google Cloud Platform", aligned=False, emit_audio=False),
        cooldowns=CooldownLedger(),
    )
    with pytest.raises(APIConnectionError):
        await collect_stream(empty_eng, f"Säg {marker_empty}", conn_options=NO_RETRY)

    for span in exporter.get_finished_spans():
        for event in span.events:
            ev_repr = repr(dict(event.attributes or {}))
            assert marker_err not in ev_repr, event
            assert marker_empty not in ev_repr, event
        for k, v in dict(span.attributes or {}).items():
            if k != "tts.input_text":
                assert marker_err not in repr(v), (k, v)
                assert marker_empty not in repr(v), (k, v)


async def test_dialogue_batch_499_after_audio_is_not_treated_as_success():
    """DialogueTTS.synthesize() uses a nested stream; a 499 close after audio
    must NOT be swallowed as success."""
    pcm_chunk = base64.b64encode(bytes([7]) * 960).decode("ascii")

    class _Close499WS:
        closed = False
        close_code = 499

        def __init__(self) -> None:
            self._step = 0

        async def send_str(self, payload: str) -> None:
            pass

        async def receive(self):
            self._step += 1
            if self._step == 1:
                return SimpleNamespace(
                    type=aiohttp.WSMsgType.TEXT,
                    data=json.dumps({"audio": pcm_chunk}),
                )
            return SimpleNamespace(type=aiohttp.WSMsgType.CLOSE, data=499)

        async def close(self) -> None:
            self.closed = True

    class _Session499:
        async def ws_connect(self, *args, **kwargs):
            return _Close499WS()

    bella = DialogueTTS(
        api_key="el-test",
        voice_id="hpp4J3VqNfWAUOO0d1Us",
        model="eleven_v4_turbo",
        http_session=_Session499(),
    )
    aoede = FakeTTS(provider="Google Cloud Platform", aligned=False, pcm_byte=9)
    engine = FallbackTTS(bella, aoede, cooldowns=CooldownLedger())

    with pytest.raises(APIError) as exc_info:
        stream = engine.synthesize("Första meningen.", conn_options=RETRY_TWICE)
        try:
            async for _ in stream:
                pass
        finally:
            await stream.aclose()
    assert exc_info.value.retryable is False
    assert engine.using_fallback is True
    assert aoede.calls == 0


async def test_stalled_second_sentence_with_open_input_still_times_out():
    """With two flushes outstanding and input still open, finishing the first
    sentence must NOT clear the timeout waiting on the stalled second sentence."""
    pcm_chunk = base64.b64encode(bytes([7]) * 960).decode("ascii")

    class _SecondSentenceStallWS:
        closed = False
        close_code = None

        def __init__(self) -> None:
            self.flushes = 0
            self._two_flushes = asyncio.Event()
            self._sent_first = False

        async def send_str(self, payload: str) -> None:
            msg = json.loads(payload)
            if msg.get("flush"):
                self.flushes += 1
                if self.flushes >= 2:
                    self._two_flushes.set()

        async def receive(self):
            if not self._sent_first:
                # Wait until BOTH sentences have been flushed, then answer only sentence 1.
                await self._two_flushes.wait()
                self._sent_first = True
                return SimpleNamespace(
                    type=aiohttp.WSMsgType.TEXT,
                    data=json.dumps({"audio": pcm_chunk, "is_final_audio_for_turn": True}),
                )
            await asyncio.sleep(60)  # stall on sentence 2 while input remains open

        async def close(self) -> None:
            self.closed = True

    class _Session:
        def __init__(self, ws: _SecondSentenceStallWS) -> None:
            self.ws = ws

        async def ws_connect(self, *args, **kwargs):
            return self.ws

    ws = _SecondSentenceStallWS()
    bella = DialogueTTS(
        api_key="el-test",
        voice_id="hpp4J3VqNfWAUOO0d1Us",
        model="eleven_v4_turbo",
        http_session=_Session(ws),
    )
    aoede = FakeTTS(provider="Google Cloud Platform", aligned=False, pcm_byte=9)
    engine = FallbackTTS(bella, aoede, cooldowns=CooldownLedger())

    stream = engine.stream(conn_options=APIConnectOptions(max_retry=0, timeout=0.15))
    # Two sentences longer than blingfire's default min_sentence_len=20 plus a
    # trailing token force two flushes while input remains open.
    stream.push_text(
        "Det här är den första lite längre meningen. "
        "Det här är den andra lite längre meningen. Tredje"
    )
    # Intentionally keep input open (no end_input yet) to test in-flight second sentence.
    t0 = time.perf_counter()
    with pytest.raises(APIError) as exc_info:
        async for _ in stream:
            pass
    elapsed = time.perf_counter() - t0
    await stream.aclose()
    assert ws.flushes == 2
    assert elapsed < 1.5
    assert exc_info.value.retryable is False
    assert engine.using_fallback is True
    assert ws.closed is True


async def test_flush_counter_handles_fast_reply_and_slow_second_write():
    """Marking pending_flushes before awaiting ws.send_str fixes both orderings:
    1) A reply completing before send({"flush": True}) returns must NOT leave a
       stale pending flush that times out while waiting for more text.
    2) Turn 1 finishing while turn 2's flush write is still in flight must NOT
       clear the timeout for a stalled turn 2."""
    pcm_chunk = base64.b64encode(bytes([7]) * 960).decode("ascii")

    # Ordering 1: reply finishes BEFORE flush write returns; stream then stays idle > timeout.
    class _FastReplyWS:
        closed = False
        close_code = None

        def __init__(self) -> None:
            self._queue: asyncio.Queue[dict] = asyncio.Queue()
            self._sent_turn1 = False
            self._turn1_processed = asyncio.Event()

        async def send_str(self, payload: str) -> None:
            msg = json.loads(payload)
            if msg.get("flush"):
                await self._queue.put({"audio": pcm_chunk, "is_final_audio_for_turn": True})
                # Gate until the NEXT receive() call so receive() has already
                # processed is_final_audio_for_turn BEFORE send_str returns.
                await self._turn1_processed.wait()
            elif msg.get("close_socket"):
                await self._queue.put({"is_final": True})

        async def receive(self):
            if self._sent_turn1:
                self._turn1_processed.set()
            item = await self._queue.get()
            if item.get("is_final_audio_for_turn"):
                self._sent_turn1 = True
            return SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(item))

        async def close(self) -> None:
            self.closed = True

    class _Session1:
        async def ws_connect(self, *args, **kwargs):
            return _FastReplyWS()

    bella1 = DialogueTTS(
        api_key="el-test",
        voice_id="hpp4J3VqNfWAUOO0d1Us",
        model="eleven_v4_turbo",
        http_session=_Session1(),
    )
    stream1 = bella1.stream(conn_options=APIConnectOptions(max_retry=0, timeout=0.12))
    stream1.push_text("Det här är en tillräckligt lång första mening. Mer")

    async def _finish_after_idle() -> None:
        # Stay idle longer than the 0.12s timeout after turn 1 completes.
        await asyncio.sleep(0.28)
        stream1.end_input()

    finisher = asyncio.create_task(_finish_after_idle())
    frames1 = [ev.frame async for ev in stream1 if ev.frame]
    await finisher
    await stream1.aclose()
    assert frames1  # completed cleanly without false idle timeout

    # Ordering 2: turn 1 finishes while turn 2's flush write stays blocked until timeout.
    class _SlowSecondWriteWS:
        closed = False
        close_code = None

        def __init__(self) -> None:
            self._flushes = 0
            self._turn1_answered = False
            self._flush2_started = asyncio.Event()

        async def send_str(self, payload: str) -> None:
            msg = json.loads(payload)
            if msg.get("flush"):
                self._flushes += 1
                if self._flushes == 2:
                    self._flush2_started.set()
                    # Hold the second flush write open until the timeout cancels the stream.
                    await asyncio.sleep(60)

        async def receive(self):
            if not self._turn1_answered:
                await self._flush2_started.wait()
                self._turn1_answered = True
                return SimpleNamespace(
                    type=aiohttp.WSMsgType.TEXT,
                    data=json.dumps({"audio": pcm_chunk, "is_final_audio_for_turn": True}),
                )
            await asyncio.sleep(60)  # turn 2 stalls silently

        async def close(self) -> None:
            self.closed = True

    ws2 = _SlowSecondWriteWS()

    class _Session2:
        async def ws_connect(self, *args, **kwargs):
            return ws2

    bella2 = DialogueTTS(
        api_key="el-test",
        voice_id="hpp4J3VqNfWAUOO0d1Us",
        model="eleven_v4_turbo",
        http_session=_Session2(),
    )
    aoede2 = FakeTTS(provider="Google Cloud Platform", aligned=False, pcm_byte=9)
    engine2 = FallbackTTS(bella2, aoede2, cooldowns=CooldownLedger())
    stream2 = engine2.stream(conn_options=APIConnectOptions(max_retry=0, timeout=0.15))
    stream2.push_text(
        "Det här är den första lite längre meningen. "
        "Det här är den andra lite längre meningen. Tredje"
    )
    t0 = time.perf_counter()
    with pytest.raises(APIError) as exc2:
        async for _ in stream2:
            pass
    elapsed = time.perf_counter() - t0
    await stream2.aclose()
    assert elapsed < 1.5
    assert exc2.value.retryable is False
    assert engine2.using_fallback is True
    assert ws2.closed is True


def test_concurrent_job_processes_preserve_both_cooldowns(tmp_path: Path):
    """Two job processes tripping different routes at the same time must not clobber each other."""
    cooldown_file = tmp_path / "concurrent-cooldown.json"
    env = {**os.environ, "TUTOR_TTS_COOLDOWN_FILE": str(cooldown_file)}
    cwd = str(Path(__file__).resolve().parent.parent)

    def _script(route_key: str) -> str:
        return (
            "from open_tutor.tts_fallback import CooldownLedger, default_cooldown_path\n"
            "ledger = CooldownLedger(path=default_cooldown_path())\n"
            f"for _ in range(15): ledger.trip({route_key!r}, 600.0)\n"
        )

    p1 = subprocess.Popen([sys.executable, "-c", _script("route-alpha")], env=env, cwd=cwd)
    p2 = subprocess.Popen([sys.executable, "-c", _script("route-beta")], env=env, cwd=cwd)
    assert p1.wait(timeout=15) == 0
    assert p2.wait(timeout=15) == 0

    ledger = CooldownLedger(path=cooldown_file)
    assert ledger.is_cooling_down("route-alpha")
    assert ledger.is_cooling_down("route-beta")


async def test_stalled_dialogue_socket_times_out_and_falls_back_to_aoede():
    """If ElevenLabs accepts the WebSocket and text then stalls silently,
    DialogueTTS must time out within conn_options.timeout so FallbackTTS switches."""

    class _StalledWS:
        closed = False
        close_code = None

        def __init__(self) -> None:
            self.sent: list[dict] = []

        async def send_str(self, payload: str) -> None:
            self.sent.append(json.loads(payload))

        async def receive(self):
            await asyncio.sleep(60)  # silent stall

        async def close(self) -> None:
            self.closed = True

    class _FakeSession:
        def __init__(self, ws: _StalledWS) -> None:
            self.ws = ws

        async def ws_connect(self, *args, **kwargs):
            return self.ws

    stalled_ws = _StalledWS()
    primary = DialogueTTS(
        api_key="el-test",
        voice_id="hpp4J3VqNfWAUOO0d1Us",
        model="eleven_v4_turbo",
        http_session=_FakeSession(stalled_ws),
    )
    fallback = FakeTTS(
        provider="Google Cloud Platform",
        model="chirp_3",
        voice_id="sv-SE-Chirp3-HD-Aoede",
        aligned=False,
        pcm_byte=9,
    )
    engine = FallbackTTS(primary, fallback, cooldowns=CooldownLedger())

    t0 = time.perf_counter()
    frames, _ = await collect_stream(
        engine,
        "Hej kompis!",
        conn_options=APIConnectOptions(max_retry=0, timeout=0.15),
    )
    elapsed = time.perf_counter() - t0
    assert frames and bytes(frames[0].data)[0] == 9
    assert elapsed < 2.0
    assert engine.using_fallback is True
    assert fallback.seen_texts == ["Hej kompis!"]
    assert stalled_ws.closed is True


async def test_provider_499_after_audio_is_not_treated_as_success():
    """LiveKit's base TTS stream swallows 499; FallbackTTS must still propagate
    partial failure and trip fallback on both streaming and batch paths."""
    err_499 = APIStatusError("provider aborted", status_code=499, retryable=False)

    # Streaming post-audio 499 -> raises non-retryable error & switches next turn.
    p_s = FakeTTS(provider="ElevenLabs", fail_with=err_499, fail_after_frame=True, pcm_byte=7)
    f_s = FakeTTS(provider="Google Cloud Platform", aligned=False, pcm_byte=9)
    eng_s = FallbackTTS(p_s, f_s, cooldowns=CooldownLedger())
    with pytest.raises(APIError) as exc_s:
        await collect_stream(eng_s, "Halv mening.", conn_options=RETRY_TWICE)
    assert exc_s.value.retryable is False
    assert eng_s.using_fallback is True
    assert f_s.calls == 0

    # Streaming pre-audio 499 -> seamlessly fails over to fallback.
    p_pre = FakeTTS(provider="ElevenLabs", fail_with=err_499, fail_after_frame=False, pcm_byte=7)
    f_pre = FakeTTS(provider="Google Cloud Platform", aligned=False, pcm_byte=9)
    eng_pre = FallbackTTS(p_pre, f_pre, cooldowns=CooldownLedger())
    frames, _ = await collect_stream(eng_pre, "Hela meningen.", conn_options=NO_RETRY)
    assert frames and bytes(frames[0].data)[0] == 9
    assert eng_pre.using_fallback is True

    # Batch post-audio 499 -> raises non-retryable error & switches next turn.
    p_b = FakeTTS(provider="ElevenLabs", fail_with=err_499, fail_after_frame=True, pcm_byte=7)
    f_b = FakeTTS(provider="Google Cloud Platform", aligned=False, pcm_byte=9)
    eng_b = FallbackTTS(p_b, f_b, cooldowns=CooldownLedger())
    with pytest.raises(APIError) as exc_b:
        stream = eng_b.synthesize("Halv mening.", conn_options=RETRY_TWICE)
        try:
            async for _ in stream:
                pass
        finally:
            await stream.aclose()
    assert exc_b.value.retryable is False
    assert eng_b.using_fallback is True
    assert f_b.calls == 0


# ---- P1 #4: single retry owner & no replay after audio ----------------------


async def test_fallback_retries_do_not_multiply_in_streaming_or_batch():
    # Streaming: max_retry=2 -> exactly 3 fallback attempts (NOT 9).
    p_stream = FakeTTS(provider="ElevenLabs", fail_with=APIStatusError("quota", status_code=429, retryable=False))
    f_stream = FakeTTS(
        provider="Google Cloud Platform",
        aligned=False,
        fail_with=APIConnectionError("transient fallback blip", retryable=True),
    )
    eng_stream = FallbackTTS(p_stream, f_stream, cooldowns=CooldownLedger())
    with pytest.raises(APIConnectionError):
        await collect_stream(eng_stream, "Hej!", conn_options=RETRY_TWICE)
    assert p_stream.calls == 1
    assert f_stream.calls == 3

    # Batch: max_retry=2 -> exactly 3 fallback attempts (NOT 9).
    p_batch = FakeTTS(provider="ElevenLabs", fail_with=APIStatusError("quota", status_code=429, retryable=False))
    f_batch = FakeTTS(
        provider="Google Cloud Platform",
        aligned=False,
        fail_with=APIConnectionError("transient fallback blip", retryable=True),
    )
    eng_batch = FallbackTTS(p_batch, f_batch, cooldowns=CooldownLedger())
    with pytest.raises(APIConnectionError):
        stream = eng_batch.synthesize("Hej!", conn_options=RETRY_TWICE)
        try:
            async for _ in stream:
                pass
        finally:
            await stream.aclose()
    assert p_batch.calls == 1
    assert f_batch.calls == 3


async def test_fallback_failure_after_audio_never_replays_utterance():
    # Streaming mid-audio failure on fallback -> 1 call, never retried.
    p1 = FakeTTS(provider="ElevenLabs", fail_with=APIStatusError("quota", status_code=429, retryable=False))
    f1 = FakeTTS(
        provider="Google Cloud Platform",
        aligned=False,
        fail_with=APIConnectionError("dropped mid-audio", retryable=True),
        fail_after_frame=True,
        pcm_byte=9,
    )
    eng1 = FallbackTTS(p1, f1)
    with pytest.raises(APIConnectionError) as exc1:
        await collect_stream(eng1, "Halva meningen", conn_options=RETRY_TWICE)
    assert exc1.value.retryable is False
    assert f1.calls == 1

    # Batch mid-audio failure on fallback -> 1 call, never retried.
    p2 = FakeTTS(provider="ElevenLabs", fail_with=APIStatusError("quota", status_code=429, retryable=False))
    f2 = FakeTTS(
        provider="Google Cloud Platform",
        aligned=False,
        fail_with=APIConnectionError("dropped mid-audio", retryable=True),
        fail_after_frame=True,
        pcm_byte=9,
    )
    eng2 = FallbackTTS(p2, f2)
    with pytest.raises(APIConnectionError) as exc2:
        stream = eng2.synthesize("Halva meningen", conn_options=RETRY_TWICE)
        try:
            async for _ in stream:
                pass
        finally:
            await stream.aclose()
    assert exc2.value.retryable is False
    assert f2.calls == 1


# ---- P2 #5: resampler buffered frame, empty stream, partial failure ---------


async def test_resampler_buffered_first_frame_still_fails_over():
    """A 1-sample 16 kHz frame is buffered inside AudioResampler (0 output bytes);
    failing before any resampled PCM is pushed must still fail over cleanly."""
    primary = FakeTTS(
        provider="ElevenLabs",
        sample_rate=16000,
        frame_bytes=2,  # 1 sample at 16 kHz -> buffered by 16k->24k resampler
        fail_with=APIConnectionError("dropped right after tiny frame"),
        fail_after_frame=True,
        pcm_byte=7,
    )
    fallback = FakeTTS(
        provider="Google Cloud Platform",
        sample_rate=24000,
        aligned=False,
        pcm_byte=9,
    )
    engine = FallbackTTS(primary, fallback)

    frames, _ = await collect_stream(engine, "Hej!")
    assert frames and bytes(frames[0].data)[0] == 9
    assert fallback.calls == 1
    assert engine.using_fallback is True


async def test_empty_stream_with_real_google_plugin_completes_cleanly():
    """Empty/whitespace streams must not crash with AudioEmitter isn't started
    or touch the network client."""
    g = build_google_tts(environ={"GOOGLE_TTS_CREDENTIALS_JSON": SAMPLE_SA})
    primary = FakeTTS(provider="ElevenLabs", aligned=True)
    engine = FallbackTTS(primary, g)
    engine._trip_fallback(APIStatusError("quota", status_code=429, retryable=False))

    frames_stream, _ = await collect_stream(engine, "   ")
    assert frames_stream == []
    assert g._client is None

    batch = engine.synthesize("   ", conn_options=NO_RETRY)
    batch_frames = [ev.frame async for ev in batch if ev.frame]
    await batch.aclose()
    assert batch_frames == []
    assert g._client is None


async def test_mid_audio_primary_failure_propagates_partial_error_and_switches_next_turn():
    primary = FakeTTS(
        provider="ElevenLabs",
        model="eleven_v4_turbo",
        voice_id="bella",
        fail_with=APIConnectionError("socket dropped mid-sentence"),
        fail_after_frame=True,
        pcm_byte=7,
    )
    fallback = FakeTTS(provider="Google Cloud Platform", model="chirp_3", voice_id="aoede", aligned=False, pcm_byte=9)
    engine = FallbackTTS(primary, fallback)

    received: list[rtc.AudioFrame] = []
    stream = engine.stream(conn_options=RETRY_TWICE)
    stream.push_text("Första meningen.")
    stream.end_input()
    with pytest.raises(APIConnectionError) as exc_info:
        async for ev in stream:
            if ev.frame:
                received.append(ev.frame)
    await stream.aclose()

    assert exc_info.value.retryable is False
    assert received and bytes(received[0].data)[0] == 7
    assert fallback.calls == 0
    assert primary.calls == 1
    assert engine.using_fallback is True

    frames2, _ = await collect_stream(engine, "Andra meningen.")
    assert bytes(frames2[0].data)[0] == 9
    assert fallback.calls == 1


async def test_batch_synthesize_fails_over():
    primary = FakeTTS(
        provider="ElevenLabs",
        fail_with=APIStatusError("payment required", status_code=402, retryable=False),
    )
    fallback = FakeTTS(provider="Google Cloud Platform", model="chirp_3", voice_id="aoede", aligned=False, pcm_byte=9)
    engine = FallbackTTS(primary, fallback)

    out = bytearray()
    stream = engine.synthesize("Mm.", conn_options=NO_RETRY)
    async for ev in stream:
        out.extend(bytes(ev.frame.data))
    await stream.aclose()
    assert out and out[0] == 9 and all(b in (0, 9) for b in out)
    assert engine.using_fallback is True


# ---- P2 #6: fillers never mix voices or poison primary cache ----------------


async def test_fillers_never_cache_fallback_under_primary_and_follow_active_voice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("TUTOR_FILLER_CLIPS_DIR", str(tmp_path / "fillers"))
    primary = FakeTTS(
        provider="ElevenLabs",
        model="eleven_v4_turbo",
        voice_id="bella",
        fail_with=APIStatusError("quota", status_code=429, retryable=False),
    )
    fallback = FakeTTS(
        provider="Google Cloud Platform",
        model="chirp_3",
        voice_id="aoede",
        aligned=False,
        tone_amplitude=8000,
    )
    engine = FallbackTTS(primary, fallback)

    # 1) FillerClips pins to concrete primary -> primary fails cleanly; Aoede is NOT
    #    called and NOT written into Bella's cache directory.
    bella_clips = FillerClips(engine)
    assert bella_clips.engine is primary
    assert bella_clips.directory == clip_directory(primary)
    generated = await bella_clips.prepare()
    assert generated == []
    assert fallback.calls == 0
    assert not list(bella_clips.directory.glob("*.wav")) if bella_clips.directory.exists() else True

    # 2) Pre-seed Bella's cache on disk, start Fillers, then fail over mid-session.
    bella_dir = clip_directory(primary)
    pcm = fallback._payload()
    write_wav(bella_dir / f"{SPECS[0].name}.wav", pcm, 24000, 1)

    played_paths: list[Path] = []

    class _RecorderPlayer:
        def play(self, config):
            played_paths.append(Path(config.source))
            return SimpleNamespace(done=lambda: True, stop=lambda: None)

    fillers = Fillers(engine=engine, player=_RecorderPlayer(), delay=0.05)
    await fillers.start()
    assert fillers.clips is not None and fillers.clips.ready
    assert fillers._arm_blocker() is None
    fillers._play_now(1)
    assert played_paths[-1].parent == bella_dir

    # Failover to Aoede: Bella's cached clip must NOT play while Aoede is speaking.
    engine._trip_fallback(APIStatusError("quota", status_code=429, retryable=False))
    assert fillers._arm_blocker() == "no_clips"

    # Let background preparation for Aoede finish -> now plays from Aoede's own directory.
    assert fillers._prep_task is not None
    await fillers._prep_task
    aoede_dir = clip_directory(fallback)
    assert fillers._arm_blocker() is None
    fillers._play_now(2)
    assert played_paths[-1].parent == aoede_dir
    assert aoede_dir != bella_dir
    await fillers.aclose()


# ---- P2 #7: Agent.tts_node captions, _started_time metrics, 1-segment -------


async def test_tts_node_captions_started_time_metrics_and_one_segment():
    primary = FakeTTS(
        provider="ElevenLabs",
        model="eleven_v4_turbo",
        voice_id="bella",
        aligned=True,
        pcm_byte=7,
        start_delay_s=0.06,
    )
    fallback = FakeTTS(
        provider="Google Cloud Platform",
        model="chirp_3",
        voice_id="aoede",
        aligned=False,
        pcm_byte=9,
    )
    engine = FallbackTTS(primary, fallback)

    collected_metrics = []
    engine.on("metrics_collected", collected_metrics.append)

    class _FakeActivity:
        def __init__(self, tts_engine: tts.TTS) -> None:
            self.tts = tts_engine
            self.session = SimpleNamespace(
                conn_options=SimpleNamespace(tts_conn_options=NO_RETRY)
            )

        def _resolve_expressive_options(self):
            return None

    class _DummyAgent(Agent):
        def __init__(self, tts_engine: tts.TTS) -> None:
            super().__init__(instructions="test")
            self._fake_activity = _FakeActivity(tts_engine)

        def _get_activity_or_raise(self):
            return self._fake_activity

    agent = _DummyAgent(engine)

    async def text_gen(*parts: str):
        for p in parts:
            yield p

    # 1) Through Agent.default.tts_node on primary: timed captions & child _started_time TTFB.
    t0 = time.perf_counter()
    frames_p = [f async for f in Agent.default.tts_node(agent, text_gen("Hej ", "kompis!"), ModelSettings())]
    elapsed = time.perf_counter() - t0
    assert frames_p and bytes(frames_p[0].data)[0] == 7
    words_p = [
        str(w)
        for f in frames_p
        if f.userdata
        for w in (f.userdata.get(USERDATA_TIMED_TRANSCRIPT) or [])
    ]
    assert words_p == ["Hej kompis!"]
    await asyncio.sleep(0.05)
    assert collected_metrics, "outer FallbackTTS must emit TTSMetrics"
    # Child waited 0.06s before calling _mark_started(); preserved timestamp means
    # TTFB is measured from child's _mark_started(), strictly smaller than total elapsed.
    assert 0.0 <= collected_metrics[0].ttfb < elapsed - 0.02

    # 2) Failover via Agent.default.tts_node: primary fails -> Aoede audio + capability flip.
    primary.fail_with = APIStatusError("quota", status_code=429, retryable=False)
    frames_f = [f async for f in Agent.default.tts_node(agent, text_gen("Nu kör vi."), ModelSettings())]
    assert frames_f and bytes(frames_f[0].data)[0] == 9
    assert engine.capabilities.aligned_transcript is False

    # 3) One-segment contract: second non-empty flush is ignored by LiveKit 1.8.10's
    #    base SynthesizeStream and completes without segment-count mismatch.
    stream = engine.stream(conn_options=NO_RETRY)
    stream.push_text("Första segmentet.")
    stream.flush()
    stream.push_text("Andra ignoreras av SDK.")
    stream.end_input()
    seg_frames = [ev.frame async for ev in stream if ev.frame]
    await stream.aclose()
    assert seg_frames
    assert fallback.seen_texts[-1] == "Första segmentet."


# ---- P1 #3: eager Google credential validation & build_tts ------------------


def test_voice_fingerprint_unwraps_fallback_and_reads_google_voice():
    g = build_google_tts(environ={"GOOGLE_TTS_CREDENTIALS_JSON": SAMPLE_SA})
    assert isinstance(g, google.TTS)
    assert isinstance(g._credentials, GoogleCredentials)
    fp_google = voice_fingerprint(g)
    assert DEFAULT_GOOGLE_VOICE in fp_google

    primary = FakeTTS(provider="ElevenLabs", model="eleven_v4_turbo", voice_id="bella")
    engine = FallbackTTS(primary, g)
    assert voice_fingerprint(engine) == voice_fingerprint(primary)

    engine._trip_fallback(APIStatusError("quota", status_code=429, retryable=False))
    assert voice_fingerprint(engine) == fp_google


def test_invalid_and_corrupt_google_credentials_rejected_eagerly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.WARNING)
    secret_marker = "SUPER_SECRET_KEY_MATERIAL_999"

    # Incomplete dict {"type": "service_account"} must fail at build time, not at client init.
    with pytest.raises(ValueError, match="not valid GCP credentials"):
        build_google_tts(environ={"GOOGLE_TTS_CREDENTIALS_JSON": '{"type":"service_account"}'})

    # Corrupt PEM key must fail eagerly and never echo key material.
    bad_pem_sa = json.dumps(
        {
            "type": "service_account",
            "project_id": "p",
            "private_key": f"-----BEGIN PRIVATE KEY-----\n{secret_marker}\n-----END PRIVATE KEY-----\n",
            "client_email": "x@p.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )
    with pytest.raises(ValueError) as bad_exc:
        build_google_tts(environ={"GOOGLE_TTS_CREDENTIALS_JSON": bad_pem_sa})
    assert secret_marker not in str(bad_exc.value)

    # Corrupt credential file on disk must fail eagerly.
    corrupt_file = tmp_path / "corrupt-sa.json"
    corrupt_file.write_text('{"type":"service_account"}', encoding="utf-8")
    with pytest.raises(ValueError, match="not a valid GCP credentials file"):
        build_google_tts(environ={"GOOGLE_APPLICATION_CREDENTIALS": str(corrupt_file)})

    # Valid credential file on disk succeeds and binds validated Credentials object.
    valid_file = tmp_path / "valid-sa.json"
    valid_file.write_text(SAMPLE_SA, encoding="utf-8")
    g_file = build_google_tts(environ={"GOOGLE_APPLICATION_CREDENTIALS": str(valid_file)})
    assert isinstance(g_file._credentials, GoogleCredentials)

    # Malformed authorized_user with numeric expiry or null fields must raise ValueError
    # (never AttributeError) and degrade cleanly to Bella alone in build_tts().
    bad_user_numeric_expiry = json.dumps(
        {
            "type": "authorized_user",
            "client_id": "cid",
            "client_secret": "csec",
            "refresh_token": "rtok",
            "expiry": 123456789,
        }
    )
    with pytest.raises(ValueError, match="not valid GCP credentials"):
        build_google_tts(environ={"GOOGLE_TTS_CREDENTIALS_JSON": bad_user_numeric_expiry})

    bad_user_nulls = json.dumps(
        {
            "type": "authorized_user",
            "client_id": None,
            "client_secret": "csec",
            "refresh_token": None,
        }
    )
    with pytest.raises(ValueError, match="not valid GCP credentials"):
        build_google_tts(environ={"GOOGLE_TTS_CREDENTIALS_JSON": bad_user_nulls})

    bad_sa_nulls = json.dumps(
        {
            "type": "service_account",
            "private_key": None,
            "client_email": None,
            "token_uri": None,
        }
    )
    with pytest.raises(ValueError, match="not valid GCP credentials"):
        build_google_tts(environ={"GOOGLE_TTS_CREDENTIALS_JSON": bad_sa_nulls})

    degraded_expiry = build_tts(
        {
            "TUTOR_TTS": "elevenlabs",
            "ELEVENLABS_API_KEY": "el-test",
            "TUTOR_TTS_FALLBACK": "google",
            "GOOGLE_TTS_CREDENTIALS_JSON": bad_user_numeric_expiry,
        }
    )
    assert isinstance(degraded_expiry, DialogueTTS)

    # Malformed default gcloud ADC file with numeric expiry must also degrade cleanly.
    adc_dir = tmp_path / "gcloud-bad-adc"
    adc_dir.mkdir()
    (adc_dir / "application_default_credentials.json").write_text(
        bad_user_numeric_expiry, encoding="utf-8"
    )
    orig_cloudsdk = os.environ.get("CLOUDSDK_CONFIG")
    orig_gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    os.environ["CLOUDSDK_CONFIG"] = str(adc_dir)
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    try:
        degraded_adc = build_tts(
            {
                "TUTOR_TTS": "elevenlabs",
                "ELEVENLABS_API_KEY": "el-test",
                "TUTOR_TTS_FALLBACK": "google",
            }
        )
        assert isinstance(degraded_adc, DialogueTTS)
    finally:
        if orig_cloudsdk is None:
            os.environ.pop("CLOUDSDK_CONFIG", None)
        else:
            os.environ["CLOUDSDK_CONFIG"] = orig_cloudsdk
        if orig_gac is not None:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = orig_gac

    # build_tts degrades cleanly to primary alone and logs a fixed warning without secret text.
    degraded = build_tts(
        {
            "TUTOR_TTS": "elevenlabs",
            "ELEVENLABS_API_KEY": "el-test",
            "TUTOR_TTS_FALLBACK": "google",
            "GOOGLE_TTS_CREDENTIALS_JSON": bad_pem_sa,
        }
    )
    assert isinstance(degraded, DialogueTTS)
    warnings = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "TTS fallback google disabled" in warnings
    assert secret_marker not in warnings


def test_cartesia_fallback_never_steals_primary_voice():
    # Omitting TUTOR_TTS_FALLBACK_VOICE must disable Cartesia fallback rather than
    # reusing ElevenLabs's TUTOR_TTS_VOICE.
    degraded = build_tts(
        {
            "TUTOR_TTS": "elevenlabs",
            "TUTOR_TTS_VOICE": "hpp4J3VqNfWAUOO0d1Us",
            "ELEVENLABS_API_KEY": "el-test",
            "TUTOR_TTS_FALLBACK": "cartesia",
            "CARTESIA_API_KEY": "cart-test",
        }
    )
    assert isinstance(degraded, DialogueTTS)

    armed = build_tts(
        {
            "TUTOR_TTS": "elevenlabs",
            "TUTOR_TTS_VOICE": "hpp4J3VqNfWAUOO0d1Us",
            "ELEVENLABS_API_KEY": "el-test",
            "TUTOR_TTS_FALLBACK": "cartesia",
            "TUTOR_TTS_FALLBACK_VOICE": "cartesia-sv-voice",
            "CARTESIA_API_KEY": "cart-test",
        }
    )
    assert isinstance(armed, FallbackTTS)
    assert isinstance(armed._fallback, cartesia.TTS)
    assert armed._fallback._opts.voice == "cartesia-sv-voice"


def test_build_tts_elevenlabs_with_google_fallback_and_invalid_settings():
    env = {
        "TUTOR_TTS": "elevenlabs",
        "ELEVENLABS_API_KEY": "el-test",
        "TUTOR_TTS_FALLBACK": "google",
        "GOOGLE_TTS_CREDENTIALS_JSON": SAMPLE_SA,
    }
    voice = build_tts(env)
    assert isinstance(voice, FallbackTTS)
    assert isinstance(voice._primary, DialogueTTS)
    assert isinstance(voice._fallback, google.TTS)
    assert "eleven_v4_turbo" in tts_route(voice)
    assert DEFAULT_GOOGLE_VOICE in tts_route(voice)

    g = build_tts({"TUTOR_TTS": "google", "GOOGLE_TTS_CREDENTIALS_JSON": SAMPLE_SA})
    assert isinstance(g, google.TTS)
    assert DEFAULT_GOOGLE_VOICE in tts_route(g)

    with pytest.raises(ValueError, match="not valid JSON"):
        build_tts({"TUTOR_TTS": "google", "GOOGLE_TTS_CREDENTIALS_JSON": "oops"})
    with pytest.raises(ValueError, match="TUTOR_TTS_FALLBACK"):
        build_tts({"TUTOR_TTS": "elevenlabs", "ELEVENLABS_API_KEY": "k", "TUTOR_TTS_FALLBACK": "bogus"})
    with pytest.raises(ValueError, match="TUTOR_TTS_FALLBACK_COOLDOWN_S"):
        parse_cooldown_s({"TUTOR_TTS_FALLBACK_COOLDOWN_S": "-5"})


def test_quota_classifier_and_analytics_privacy():
    assert is_quota_or_auth_error(APIStatusError("x", status_code=402))
    assert is_quota_or_auth_error(APIStatusError("x", status_code=429))
    assert is_quota_or_auth_error(APIStatusError("quota_exceeded", status_code=1008))
    assert not is_quota_or_auth_error(APIConnectionError("socket reset"))

    primary = FakeTTS(provider="ElevenLabs", model="eleven_v4_turbo", voice_id="bella")
    fallback = FakeTTS(provider="Google Cloud Platform", model="chirp_3", voice_id="aoede", aligned=False)
    engine = FallbackTTS(primary, fallback)
    summary = json.dumps(engine.stats_for_analytics())
    assert "PRIVATE KEY" not in summary
    assert "el-test" not in summary
