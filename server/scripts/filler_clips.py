"""Make (or show) the fox's filler clips for the configured TTS voice.

The worker makes these itself on first use (fillers.py); this script exists so a
person can generate them ahead of time, look at the checks, and listen to the
files. Nothing here touches a session or a room.

    OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env \
        server/bin/with-env uv run --project server python server/scripts/filler_clips.py \
        --out /tmp/filler-clips

``--force`` regenerates even when the cache already holds the clips.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

import numpy as np
from livekit.agents.utils import http_context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_tutor.agent import build_tts, tts_route  # noqa: E402
from open_tutor.fillers import (  # noqa: E402
    SPECS,
    clip_directory,
    clip_duration,
    energy_segments,
    make_clips,
    voice_fingerprint,
)


def inspect(path: Path) -> str:
    import wave

    with wave.open(str(path), "rb") as wav:
        pcm = wav.readframes(wav.getnframes())
        sample_rate, channels = wav.getframerate(), wav.getnchannels()
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    peak = int(np.abs(samples).max()) if samples.size else 0
    rms = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0
    duration = clip_duration(pcm, sample_rate, channels)
    # Shape instead of ears: one hum, two parts ("a-ha"), or three words.
    shape = len(energy_segments(pcm, sample_rate, channels))
    return (f"{duration:5.2f} s  peak {peak:5d}  rms {rms:6.0f}  "
            f"{sample_rate} Hz {channels} ch  {shape} part(s)")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None,
                        help="copy the clips here and print absolute paths")
    parser.add_argument("--force", action="store_true", help="regenerate cached clips")
    parser.add_argument("--dir", type=Path, default=None, help="cache directory override")
    args = parser.parse_args()

    engine = build_tts()
    directory = args.dir or clip_directory(engine)
    print(f"TTS route:   {tts_route(engine)}")
    print(f"Fingerprint: {voice_fingerprint(engine)}")
    print(f"Cache:       {directory}")
    if args.force and directory.is_dir():
        for spec in SPECS:
            (directory / f"{spec.name}.wav").unlink(missing_ok=True)
    # A script is not a job: the TTS plugins need an http session bound to this context.
    async with http_context.open():
        clips = await make_clips(engine, directory)
        await engine.aclose()
    if not clips:
        print("No clip passed the checks; the feature would stay off.")
        return 1

    print(f"\nKept {len(clips)} of {len(SPECS)} clips:")
    out = args.out
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
    for clip in clips:
        line = f"  {clip.name:12s} {clip.kind:6s} {inspect(clip.path)}"
        if out is not None:
            target = out / clip.path.name
            shutil.copy2(clip.path, target)
            line += f"\n               {target.resolve()}"
        print(line, flush=True)

    rejected = [spec.name for spec in SPECS if spec.name not in {c.name for c in clips}]
    if rejected:
        print(f"\nRejected (no spelling passed): {', '.join(rejected)}")
    print("\nListen to the files: the durations above are the only automated check; "
          "the words are checked by ear.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
