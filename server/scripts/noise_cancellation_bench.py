"""What the noise-cancellation filter actually does to our three audio cases.

The end-to-end probe (noise_cancellation_probe.py) says what the tutor did; this says why.
One participant publishes a prepared WAV into a real LiveKit Cloud room and a second one
subscribes to that same track twice: through the filter under test and unfiltered. Both
recordings are written next to each other and compared by level, so the filter's own effect
on a clip is a number instead of an opinion.

    OPEN_TUTOR_ENV=~/.config/open-tutor-nc-dev/env \\
      server/bin/with-env uv run --project server python \\
        server/scripts/noise_cancellation_bench.py --audio /tmp/nc-audio --out /tmp/nc-bench

Needs the same LiveKit Cloud project as the worker: the enhanced models are Cloud features.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
import wave
from pathlib import Path

import numpy as np
from livekit.agents import stt as stt_api
from livekit.agents.utils import http_context
from livekit import api, rtc

from livekit.plugins import noise_cancellation

from open_tutor.agent import build_stt

RATE = 24000
FRAME = RATE // 50  # 20 ms

CASES = ("background", "near", "mixed", "mixed_loud")
MODELS = {"bvc": noise_cancellation.BVC, "nc": noise_cancellation.NC}


def load_wav(path: Path) -> bytes:
    with wave.open(str(path)) as clip:
        assert clip.getframerate() == RATE and clip.getnchannels() == 1, path
        return clip.readframes(clip.getnframes())


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm)


def db(value: float, floor: float = 1e-9) -> float:
    return round(20 * np.log10(max(value, floor)), 1)


def levels(pcm: bytes) -> dict:
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    speech = audio[np.abs(audio) > 0.02]
    return {"ms": int(len(audio) / RATE * 1000),
            "rms_db": db(float(np.sqrt(np.mean(audio**2))) if audio.size else 0.0),
            "speech_rms_db": db(float(np.sqrt(np.mean(speech**2))) if speech.size else 0.0),
            "peak": int(np.max(np.abs(audio)) * 32767) if audio.size else 0}


async def transcribe(pcm: bytes) -> str:
    """What the session's own recogniser hears in this recording."""
    recogniser = build_stt()
    stream = recogniser.stream()
    for start in range(0, len(pcm) - FRAME * 2 + 1, FRAME * 2):
        frame = pcm[start:start + FRAME * 2]
        stream.push_frame(rtc.AudioFrame(frame, RATE, 1, FRAME))
    stream.end_input()
    finals: list[str] = []
    async for event in stream:
        if event.type == stt_api.SpeechEventType.FINAL_TRANSCRIPT:
            finals.append(event.alternatives[0].text)
    await stream.aclose()
    return " ".join(t.strip() for t in finals if t.strip())


async def token(room: str, identity: str) -> str:
    grant = api.VideoGrants(room_join=True, room=room)
    return (api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
            .with_identity(identity).with_name(identity).with_grants(grant).to_jwt())


async def consume(track: rtc.Track, mode: str | None, out: bytearray, ready: asyncio.Event) -> None:
    options = {} if mode is None else {"noise_cancellation": MODELS[mode]()}
    stream = rtc.AudioStream(track, sample_rate=RATE, num_channels=1, **options)
    ready.set()
    async for event in stream:
        out.extend(bytes(event.frame.data))
    await stream.aclose()


async def run_case(case: str, audio: Path, mode: str, out: Path,
                   transcribe_recordings: bool = False) -> dict:
    pcm = load_wav(audio / f"{case}.wav")
    room_name = f"nc-bench-{mode}-{case}-{uuid.uuid4().hex[:6]}"
    publisher, subscriber = rtc.Room(), rtc.Room()
    raw, filtered = bytearray(), bytearray()
    got_track = asyncio.Event()
    ready = asyncio.Event()
    tasks: list[asyncio.Task] = []

    @subscriber.on("track_subscribed")
    def subscribed(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            tasks.append(asyncio.create_task(consume(track, None, raw, ready)))
            tasks.append(asyncio.create_task(consume(track, mode, filtered, ready)))
            got_track.set()

    await publisher.connect(os.environ["LIVEKIT_URL"], await token(room_name, "publisher"))
    await subscriber.connect(os.environ["LIVEKIT_URL"], await token(room_name, "listener"))
    source = rtc.AudioSource(RATE, 1)
    track = rtc.LocalAudioTrack.create_audio_track("case", source)
    await publisher.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    await asyncio.wait_for(got_track.wait(), 15)
    await asyncio.wait_for(ready.wait(), 15)

    silence = bytes(FRAME * 2)
    pending = pcm
    start = time.monotonic()
    while True:
        chunk, pending = (pending[: FRAME * 2], pending[FRAME * 2:]) if pending else (silence, b"")
        await source.capture_frame(rtc.AudioFrame(chunk.ljust(FRAME * 2, b"\0"), RATE, 1, FRAME))
        if not pending and time.monotonic() - start > len(pcm) / (FRAME * 2) * 0.02 + 1.5:
            break
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.5)
    for task in tasks:
        task.cancel()
    await publisher.disconnect()
    await subscriber.disconnect()

    out.mkdir(parents=True, exist_ok=True)
    write_wav(out / f"{case}-{mode}-raw.wav", bytes(raw))
    write_wav(out / f"{case}-{mode}-filtered.wav", bytes(filtered))
    raw_levels, filtered_levels = levels(bytes(raw)), levels(bytes(filtered))
    transcripts = {}
    if transcribe_recordings:
        async with http_context.open():
            transcripts = {"raw": await transcribe(bytes(raw)),
                           "filtered": await transcribe(bytes(filtered))}
    return {
        "case": case,
        "mode": mode,
        "raw": raw_levels,
        "filtered": filtered_levels,
        # Below about -1 dB the filter left the speech alone; -20 dB is a removal.
        "speech_change_db": round(filtered_levels["speech_rms_db"] - raw_levels["speech_rms_db"], 1),
        "transcripts": transcripts,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--models", default="bvc,nc")
    parser.add_argument("--cases", default=",".join(CASES))
    parser.add_argument("--stt", action="store_true",
                        help="also transcribe both recordings with the session's recogniser")
    args = parser.parse_args()

    results = []
    for mode in args.models.split(","):
        for case in args.cases.split(","):
            result = await run_case(case, args.audio, mode, args.out, args.stt)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            results.append(result)
    (args.out / "bench.json").write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
