"""Measure what background voice cancellation changes, with audio instead of a promise.

This probe publishes prepared WAVs as the child's microphone into a real session against a
running worker, and records what the tutor did with them. It answers three questions per
case, which are the three things a real home broke (docs/smart-screen.md, 2026-11-13):

1. Does the tutor treat the case audio as a child turn (a reply starts, and what did the
   recogniser hear)?
2. Does the case audio cut the fox off while it is answering (the VAD-interruption path)?
3. How long does the fox talk after the case audio begins, if it is interrupted?

Cases (made by noise_cancellation_audio.py, all fictional and synthesized):

- ``near``       one clear child sentence, alone (control: must still be heard)
- ``background`` other talk in the room, no near speaker (must not be heard as the child)
- ``mixed``      the child's sentence with quieter other talk under it

Run one case per session, against a worker started with the mode under test:

    OPEN_TUTOR_ENV=~/.config/open-tutor-nc-dev/env \\
      server/bin/with-env uv run --project server python \\
        server/scripts/noise_cancellation_probe.py --audio /tmp/nc-audio \\
        --case background --out /tmp/nc-runs/off-background

Writes ``probe.json`` with the timeline and the summary. Nothing here is part of CI; it
spends a little on the real providers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import wave
from pathlib import Path

from fastapi.testclient import TestClient
from livekit import rtc

from open_tutor.web import create_app

RATE = 24000
FRAME = RATE // 50  # 20 ms


def load_wav(path: Path) -> bytes:
    with wave.open(str(path)) as clip:
        assert clip.getframerate() == RATE and clip.getnchannels() == 1, path
        return clip.readframes(clip.getnframes())


class Probe:
    def __init__(self, case: str, audio: Path, out: Path) -> None:
        self.case = case
        self.clip = load_wav(audio / f"{case}.wav")
        self.question = load_wav(audio / "question.wav")
        self.clip_seconds = len(self.clip) / (FRAME * 2) * 0.02
        self.out = out
        self.t0 = time.monotonic()
        self.events: list[dict] = []
        self.state = "initializing"
        self.state_changed = asyncio.Event()
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.play_started = 0.0
        self.disconnected = asyncio.Event()

    # ---- plumbing -----------------------------------------------------------------

    def log(self, kind: str, **data) -> None:
        entry = {"t": round(time.monotonic() - self.t0, 2), "event": kind, **data}
        self.events.append(entry)
        print(json.dumps(entry, ensure_ascii=False)[:400], flush=True)

    async def wait_state(self, wanted: set[str], timeout: float) -> bool:
        end = time.monotonic() + timeout
        while self.state not in wanted:
            self.state_changed.clear()
            remaining = end - time.monotonic()
            if remaining <= 0:
                return False
            try:
                await asyncio.wait_for(self.state_changed.wait(), remaining)
            except asyncio.TimeoutError:
                return False
        return True

    async def play(self, pcm: bytes, name: str) -> None:
        self.play_started = time.monotonic()
        self.log("play", clip=name, seconds=round(len(pcm) / (FRAME * 2) * 0.02, 2))
        await self.queue.put(pcm)

    async def mic(self, source: rtc.AudioSource) -> None:
        silence = bytes(FRAME * 2)
        pending = b""
        while True:
            if not pending and not self.queue.empty():
                pending = self.queue.get_nowait()
            chunk, pending = (pending[: FRAME * 2], pending[FRAME * 2:]) if pending else (silence, b"")
            chunk = chunk.ljust(FRAME * 2, b"\0")
            await source.capture_frame(rtc.AudioFrame(chunk, RATE, 1, FRAME))

    async def queue_empty(self, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.queue.empty():
                return True
            await asyncio.sleep(0.05)
        return False

    # ---- the two tests ------------------------------------------------------------

    async def listening_test(self) -> dict:
        """Play the case audio while the fox is listening: is it taken for the child?"""
        self.log("phase", name="listening_test")
        await self.play(self.clip, self.case)
        heard = await self.wait_state({"thinking", "speaking"}, self.clip_seconds + 10)
        result = {"reacted": heard}
        if heard:
            result["reacted_after_s"] = round(time.monotonic() - self.play_started, 2)
            result["reply_generated"] = await self.wait_state({"speaking"}, 20)
            # Let the reply finish (or give up) so the room is quiet for the next test.
            result["back_to_listening"] = await self.wait_state({"listening"}, 45)
        else:
            result["reply_generated"] = False
            result["back_to_listening"] = True
        await self.queue_empty(3)
        await asyncio.sleep(1.0)
        return result

    async def interruption_test(self) -> dict:
        """Make the fox talk, then play the case audio over it: is the fox cut off?"""
        self.log("phase", name="interruption_test")
        await self.wait_state({"listening"}, 30)
        await self.play(self.question, "question")
        result = {"fox_spoke": await self.wait_state({"speaking"}, 25)}
        if not result["fox_spoke"]:
            return result
        await asyncio.sleep(1.2)  # the fox is one sentence in; the audio has to interrupt
        if self.state != "speaking":
            result["fox_still_speaking_when_audio_starts"] = False
        result["fox_still_speaking_when_audio_starts"] = self.state == "speaking"
        await self.play(self.clip, self.case)
        cut = await self.wait_state({"listening", "thinking"}, 6)
        result["interrupted"] = cut and self.state != "speaking"
        result["interrupt_after_audio_s"] = (
            round(time.monotonic() - self.play_started, 2) if cut else None
        )
        if cut:
            await self.wait_state({"speaking", "listening"}, 40)
        await self.queue_empty(3)
        return result

    async def run(self) -> dict:
        client = TestClient(create_app())
        session = client.post(
            "/api/session",
            json={"learner": {"name": "Nils", "grade": 7, "notes": []}},
            headers={"x-tutor-code": os.environ.get("TUTOR_ACCESS_CODE", "")},
        ).json()
        room = rtc.Room()

        @room.on("participant_attributes_changed")
        def attrs(changed, participant):
            if "lk.agent.state" in changed:
                self.state = changed["lk.agent.state"]
                self.state_changed.set()
                self.log("agent_state", state=self.state)

        room.on("disconnected", lambda *_: self.disconnected.set())

        def transcription(reader, identity):
            async def read():
                text = await reader.read_all()
                if text.strip():
                    self.log("transcript", who="child" if identity == room.local_participant.identity
                             else "tutor", text=text[:200])
            asyncio.create_task(read())

        await room.connect(session["url"], session["token"])
        room.register_text_stream_handler("lk.transcription", transcription)

        def board(method):
            async def handler(data: rtc.RpcInvocationData) -> str:
                return json.dumps({"ok": True})
            return handler

        for method in ("board.show", "board.update", "board.focus"):
            room.local_participant.register_rpc_method(method, board(method))

        source = rtc.AudioSource(RATE, 1)
        track = rtc.LocalAudioTrack.create_audio_track("mic", source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        mic = asyncio.create_task(self.mic(source))
        self.log("connected", room=session["room"])

        results: dict = {"case": self.case, "room": session["room"]}
        # The greeting is fixed TTS and cannot be interrupted (agent.py); wait it out.
        results["greeted"] = await self.wait_state({"speaking"}, 30)
        results["listening_after_greeting"] = await self.wait_state({"listening"}, 40)
        results["listening_test"] = await self.listening_test()
        results["interruption_test"] = await self.interruption_test()

        await room.local_participant.send_text(json.dumps({"type": "end"}), topic="session-event")
        try:
            await asyncio.wait_for(self.disconnected.wait(), 30)
        except asyncio.TimeoutError:
            self.log("no_disconnect")
        mic.cancel()
        await room.disconnect()
        report = {"results": results, "events": self.events}
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--case", choices=("near", "background", "mixed", "mixed_loud"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(Probe(args.case, args.audio, args.out).run())
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    os._exit(0)  # the native LiveKit client can abort during interpreter teardown


if __name__ == "__main__":
    main()
