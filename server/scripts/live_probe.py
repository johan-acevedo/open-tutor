"""Milestone A live probe: a scripted fictional learner joins a real session.

It talks to the running tutor worker through LiveKit Cloud with recorded Swedish
clips, shares a fictional homework image, interrupts, works quietly, mumbles and
ends the session. It records the tutor's audio and a JSON timeline.

    bin/with-env uv run python scripts/live_probe.py --clips DIR --out DIR

Clips (mono WAV): hello, interrupt, tryself, mumble, answer. Fictional material only.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import time
import wave
from pathlib import Path

from fastapi.testclient import TestClient
from livekit import rtc
from PIL import Image, ImageDraw, ImageFont

from open_tutor.web import create_app

RATE = 24000
FRAME = RATE // 50  # 20 ms


def worksheet() -> bytes:
    image = Image.new("RGB", (1200, 700), "#fbfaf5")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 44)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    except OSError:
        font = small = ImageFont.load_default()
    draw.text((60, 50), "Matte åk 7 – Ekvationer", fill="#222", font=font)
    draw.text((60, 180), "Uppgift 3.  Lös ekvationen:  3x + 5 = 20", fill="#222", font=small)
    draw.text((60, 300), "Uppgift 4.  Lös ekvationen:  2x + 4 = 14", fill="#222", font=small)
    draw.text((60, 420), "Uppgift 5.  Förklara hur du tänkte.", fill="#222", font=small)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=88)
    return out.getvalue()


def load_clip(path: Path) -> bytes:
    with wave.open(str(path)) as clip:
        assert clip.getframerate() == RATE and clip.getnchannels() == 1
        return clip.readframes(clip.getnframes())


class Probe:
    def __init__(self, clips: Path, out: Path) -> None:
        self.clips = {p.stem: load_clip(p) for p in clips.glob("*.wav")}
        self.out = out
        self.t0 = time.monotonic()
        self.events: list[dict] = []
        self.state = "initializing"
        self.mode = "talking"
        self.state_changed = asyncio.Event()
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.recorded = bytearray()
        self.notes: list[dict] = []
        self.board: list[dict] = []
        self.disconnected = asyncio.Event()
        self.voiced: list[float] = []  # probe times of 20 ms tutor frames that carry sound

    def log(self, kind: str, **data) -> None:
        entry = {"t": round(time.monotonic() - self.t0, 2), "event": kind, **data}
        self.events.append(entry)
        print(json.dumps(entry, ensure_ascii=False)[:300], flush=True)

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

    async def speaking_during(self, seconds: float) -> float:
        """Seconds the tutor spent speaking within the window."""
        spoken, end = 0.0, time.monotonic() + seconds
        while time.monotonic() < end:
            await asyncio.sleep(0.1)
            if self.state == "speaking":
                spoken += 0.1
        return round(spoken, 1)

    async def say(self, name: str) -> None:
        self.log("child_says", clip=name)
        await self.queue.put(self.clips[name])

    async def mic(self, source: rtc.AudioSource) -> None:
        silence = bytes(FRAME * 2)
        pending = b""
        while True:
            if not pending and not self.queue.empty():
                pending = self.queue.get_nowait()
            chunk, pending = (pending[: FRAME * 2], pending[FRAME * 2 :]) if pending else (silence, b"")
            chunk = chunk.ljust(FRAME * 2, b"\0")
            await source.capture_frame(rtc.AudioFrame(chunk, RATE, 1, FRAME))

    async def record(self, track: rtc.Track) -> None:
        async for event in rtc.AudioStream(track, sample_rate=RATE, num_channels=1):
            data = bytes(event.frame.data)
            self.recorded.extend(data)
            samples = memoryview(data).cast("h")
            if samples and max(abs(x) for x in samples) > 500:
                self.voiced.append(time.monotonic() - self.t0)

    async def run(self) -> dict:
        client = TestClient(create_app())
        session = client.post(
            "/api/session",
            json={"learner": {"name": "Leo", "grade": 7, "notes": []}},
            headers={"x-tutor-code": os.environ.get("TUTOR_ACCESS_CODE", "")},
        ).json()
        room = rtc.Room()

        @room.on("participant_attributes_changed")
        def attrs(changed, participant):
            if "lk.agent.state" in changed:
                self.state = changed["lk.agent.state"]
                self.state_changed.set()
                self.log("agent_state", state=self.state)
            if "tutor.mode" in changed:
                self.mode = changed["tutor.mode"]
                self.log("tutor_mode", mode=changed["tutor.mode"])

        @room.on("track_subscribed")
        def subscribed(track, publication, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                asyncio.create_task(self.record(track))

        room.on("disconnected", lambda *_: self.disconnected.set())

        def transcription(reader, identity):
            async def read():
                text = await reader.read_all()
                if text.strip() and identity != room.local_participant.identity:
                    self.log("tutor_caption", text=text)
            asyncio.create_task(read())

        def note(reader, identity):
            async def read():
                self.notes.append(json.loads(await reader.read_all()))
                self.log("note", note=self.notes[-1])
            asyncio.create_task(read())

        await room.connect(session["url"], session["token"])
        room.register_text_stream_handler("lk.transcription", transcription)
        room.register_text_stream_handler("note", note)

        def board(method):
            async def handler(data: rtc.RpcInvocationData) -> str:
                item = json.loads(data.payload)
                self.board.append({"method": method, **item})
                self.log("board", method=method, id=item.get("id"), item_kind=item.get("kind"),
                         title=item.get("title"), detail=json.dumps(item, ensure_ascii=False)[:240])
                await asyncio.sleep(0.15)  # stand-in for browser render time
                return json.dumps({"ok": True})
            return handler

        for method in ("board.show", "board.update", "board.focus"):
            room.local_participant.register_rpc_method(method, board(method))

        source = rtc.AudioSource(RATE, 1)
        track = rtc.LocalAudioTrack.create_audio_track("mic", source)
        await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
        mic = asyncio.create_task(self.mic(source))
        self.log("connected", room=session["room"])

        results: dict = {}
        # 1. The tutor greets first.
        results["greeted"] = await self.wait_state({"speaking"}, 25)
        results["greeting_after_s"] = self.events[-1]["t"] if results["greeted"] else None
        await self.wait_state({"listening"}, 30)
        # 2. Child says what they have, then shares homework.
        await self.say("hello")
        await asyncio.sleep(1)
        await self.wait_state({"speaking"}, 25)
        await self.wait_state({"listening"}, 40)
        image = worksheet()
        (self.out / "worksheet.jpg").write_bytes(image)
        await room.local_participant.send_bytes(
            image, topic="homework", name="matte.jpg", mime_type="image/jpeg",
            attributes={"kind": "photo", "source": "matte.jpg", "itemId": "h1"},
        )
        self.log("homework_sent")
        await self.wait_state({"speaking"}, 30)
        await self.wait_state({"listening"}, 60)
        # 3. Ask about task 3, then interrupt the explanation.
        await self.say("interrupt")
        await self.wait_state({"speaking"}, 30)
        await asyncio.sleep(2.5)
        if self.state == "speaking":
            started = time.monotonic()
            await self.say("interrupt")
            stopped = await self.wait_state({"listening", "thinking"}, 12)
            results["interrupt_stop_s"] = round(time.monotonic() - started, 2) if stopped else None
            # The interrupted reply must not keep playing: count tutor audio from 0.5 s after
            # the state change until the tutor starts its next reply.
            stop_t = time.monotonic() - self.t0
            await self.wait_state({"speaking"}, 30)
            next_t = time.monotonic() - self.t0
            results["audio_after_interrupt_s"] = round(
                0.02 * len([t for t in self.voiced if stop_t + 0.5 <= t < next_t - 0.3]), 2)
            results["interrupt_gap_s"] = round(next_t - stop_t, 2)
        await self.wait_state({"listening"}, 60)
        # 4. Quiet work: the child tries alone; 30 s of silence.
        await self.say("tryself")
        await self.wait_state({"speaking"}, 30)
        await self.wait_state({"listening"}, 40)
        await asyncio.sleep(1)
        results["quiet_mode"] = self.mode
        results["spoke_during_30s_quiet_s"] = await self.speaking_during(30)
        # 5. Thinking aloud during quiet work.
        await self.say("mumble")
        results["spoke_after_mumble_s"] = await self.speaking_during(16)
        await self.wait_state({"listening"}, 30)
        # 6. The answer, then end.
        await self.say("answer")
        await self.wait_state({"speaking"}, 30)
        await self.wait_state({"listening"}, 40)
        await room.local_participant.send_text(json.dumps({"type": "end"}), topic="session-event")
        self.log("end_sent")
        try:
            await asyncio.wait_for(self.disconnected.wait(), 45)
        except asyncio.TimeoutError:
            self.log("no_disconnect")
        mic.cancel()
        await room.disconnect()
        results["board_items"] = len([b for b in self.board if b["method"] == "board.show"])
        results["notes"] = self.notes
        with wave.open(str(self.out / "tutor.wav"), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE), w.writeframes(bytes(self.recorded))
        report = {"results": results, "events": self.events, "board": self.board}
        (self.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clips", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    print(json.dumps(asyncio.run(Probe(args.clips, args.out).run()), ensure_ascii=False, indent=2), flush=True)
    os._exit(0)  # the native LiveKit client can abort during interpreter teardown


if __name__ == "__main__":
    main()
