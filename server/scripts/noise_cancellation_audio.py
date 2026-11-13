"""Make the audio for the noise-cancellation measurement (fictional Swedish material).

Everything here is synthesized with the session's own voice (Deepgram Flux TTS, the Swedish
voice in the worker's environment); no recording of a real person is used. The "other voice"
in the room is the same synthesized line, slowed and pitched down, so the two speakers are
easy for a recogniser to tell apart but neither is anybody real.

    OPEN_TUTOR_ENV=~/.config/open-tutor-nc-dev/env \
      server/bin/with-env uv run --project server python server/scripts/noise_cancellation_audio.py \
        --out /tmp/nc-audio

Writes 24 kHz mono 16-bit WAVs, which is what the probe publishes as the child's microphone:

- near.wav     one clear child sentence, alone (case b)
- background.wav  adult-like talk, three lines in a row (case a: alone in the room)
- mixed.wav    the child sentence with the background speech 14 dB quieter (case c)
- question.wav a short child question, to make the fox talk before the interruption test
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import wave
from pathlib import Path

import numpy as np
from livekit.agents.utils import http_context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_tutor.agent import build_tts  # noqa: E402
from open_tutor.fillers import synthesize_pcm, trim_silence, write_wav  # noqa: E402

RATE = 24000

CHILD = "Hej Räven, jag behöver hjälp med matteläxan, jag fattar inte ekvationerna."
QUESTION = "Räven, kan du förklara det där en gång till?"
ADULT = ("Ja alltså, jag tänkte att vi kan ta det där imorgon i stället, "
         "det är ju ändå fredag och vi hinner inte idag.")


def resample(samples: np.ndarray, factor: float) -> np.ndarray:
    """Play the same recording `factor` times slower: lower and slower, another speaker."""
    index = np.arange(0, len(samples), factor)
    return np.interp(index, np.arange(len(samples)), samples)


def peak_normalize(samples: np.ndarray, peak: float = 0.7) -> np.ndarray:
    top = float(np.max(np.abs(samples))) if samples.size else 0.0
    return samples * (peak / top) if top > 0 else samples


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as wav:
        assert wav.getframerate() == RATE and wav.getnchannels() == 1, path
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def to_pcm(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


def pad(samples: np.ndarray, seconds: float) -> np.ndarray:
    return np.concatenate([np.zeros(int(RATE * seconds), dtype=np.float32), samples])


def tile(samples: np.ndarray, gap: float, total_seconds: float) -> np.ndarray:
    """The line again and again with a pause between, as a television left talking."""
    silence = np.zeros(int(RATE * gap), dtype=np.float32)
    out = samples
    while len(out) < RATE * total_seconds:
        out = np.concatenate([out, silence, samples])
    return out


async def synthesize(engine, text: str) -> np.ndarray:
    pcm, sample_rate, channels = await synthesize_pcm(engine, text)
    assert sample_rate == RATE and channels == 1, (sample_rate, channels)
    trimmed = trim_silence(pcm, sample_rate, channels)
    return np.frombuffer(trimmed, dtype=np.int16).astype(np.float32) / 32768


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    engine = build_tts()
    async with http_context.open():  # TTS outside a job context needs its own http session
        child = pad(peak_normalize(await synthesize(engine, CHILD)), 0.3)
        question = pad(peak_normalize(await synthesize(engine, QUESTION)), 0.3)
        adult_raw = await synthesize(engine, ADULT)
        adult = pad(peak_normalize(resample(adult_raw, 1.18)), 0.3)  # slower, lower voice

    total = len(child) / RATE + 1.0
    background = tile(adult, gap=0.4, total_seconds=total)[: len(child)]

    def db(gain_db: float) -> float:
        return float(10 ** (gain_db / 20))

    # Case a: the other talk alone, 6 dB under the child's level. Case c: the child's
    # sentence with that talk 14 dB under it (a quieter voice across the room).
    case_a = background * db(-6)
    case_c = child + background * db(-14)
    # A parent talking at nearly the child's own level: the case BVC is meant for.
    case_c_loud = child + background * db(-4)

    for name, samples in (("near", child), ("question", question),
                          ("background", case_a), ("mixed", case_c),
                          ("mixed_loud", case_c_loud)):
        path = args.out / f"{name}.wav"
        write_wav(path, to_pcm(samples), RATE, 1)
        rms = float(np.sqrt(np.mean(samples**2))) or 1e-9
        active = samples[np.abs(samples) > 0.02]
        speech_rms = float(np.sqrt(np.mean(active**2))) if active.size else rms
        print(f"{name:12s} {len(samples) / RATE:5.2f} s  peak "
              f"{int(np.max(np.abs(samples)) * 32767):5d}  speech rms "
              f"{20 * np.log10(speech_rms):6.1f} dBFS  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
