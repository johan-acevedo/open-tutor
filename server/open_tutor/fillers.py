"""The fox's filler sounds: one short sound while the reply is still on its way.

A child who has just stopped talking expects the fox to answer. When the tutor
model takes a second or two longer, the silence reads as "nobody heard me". A
small sound from the fox fills it, the way people do in conversation.

How it works, and why this way:

- **The clips are pre-made in the fox's own voice** (``TUTOR_TTS``/voice), cached
  on disk under a key built from the TTS provider, model and voice, so changing
  the voice regenerates them. They are generated in the background on first use
  (never during a turn) and played from disk, so a filler costs no TTS call and
  no latency at that moment. If generation fails, the feature stays off and says
  so once.
- **Playback uses LiveKit's ``BackgroundAudioPlayer``**, which publishes its own
  audio track. It therefore never touches the speech pipeline: no chat history,
  no caption, no transcript, no ``chat_item`` in the debug trail, and no speech
  handle that could queue the real reply behind it. Its ``PlayHandle.stop()``
  plus ``AudioSource.clear_queue()`` cuts the sound the moment the child speaks
  or the reply starts. See docs.livekit.io/agents/multimodality/audio/background-audio.
- **One decision point**: ``Fillers._on_item`` arms the timer when a *child*
  turn is committed; the timer only fires while the agent is still thinking, the
  child is not speaking and the tutor is in talking mode. A reply that starts
  sooner, or the child speaking again, cancels it.

``TUTOR_FILLERS=1`` switches it on; ``TUTOR_FILLER_AFTER_S`` sets the delay
(default 0.7 s).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
from livekit.agents import AudioConfig, BackgroundAudioPlayer, PlayHandle

from .debug_log import record_active

log = logging.getLogger("open-tutor")

DEFAULT_DELAY_S = 0.7
DEFAULT_VOLUME = 0.55
# A clip is trimmed of silence and must then land in this window. The brief asks
# for 300-900 ms; the window leaves room for a slower voice while still cutting
# anything that came out as a whole sentence.
MIN_CLIP_S = 0.18
MAX_CLIP_S = 0.95
# Bump when the texts or the checks change, so cached clips are remade.
CLIP_VERSION = 1
SILENCE_FLOOR = 350  # int16 peak amplitude below which a sample counts as silence
PHRASE_WEIGHT = 0.25  # sounds are the workhorses; phrases are the exception


@dataclass(frozen=True)
class ClipSpec:
    """One filler sound, with the spellings tried in order."""

    name: str
    kind: str  # "sound" or "phrase"
    texts: tuple[str, ...]


# Mostly sounds that fit anywhere. The two phrases are deliberately neutral
# ("let's see") so they still make sense right after a short answer, and they are
# drawn rarely (PHRASE_WEIGHT).
SPECS: tuple[ClipSpec, ...] = (
    ClipSpec("mm", "sound", ("Mm.", "Mmm.", "Mm, mm.")),
    ClipSpec("mm-long", "sound", ("Mmm...", "Mmmm.", "Mm-m.")),
    ClipSpec("hmm", "sound", ("Hmm.", "Hmm...", "Hm.")),
    ClipSpec("aha", "sound", ("Aha.", "Aha!", "A-ha.")),
    ClipSpec("ska-vi-se", "phrase", ("Ska vi se...", "Ska vi se.", "Ska vi se nu...")),
    ClipSpec("lat-mig-se", "phrase", ("Låt mig se...", "Låt mig se.", "Låt mig se nu...")),
)


@dataclass(frozen=True)
class Clip:
    name: str
    path: Path
    kind: str


# ---- clip generation ------------------------------------------------------------


def voice_fingerprint(engine: Any) -> str:
    """Identify the voice a set of clips was made with.

    Anything that changes how the fox sounds belongs here: TTS provider, model,
    voice id and voice controls such as expressivity. A change regenerates the
    clips instead of replaying the previous voice.
    """
    provider = str(getattr(engine, "provider", type(engine).__name__))
    model = str(getattr(engine, "model", "") or "")
    voice = ""
    for attribute in ("voice_id", "voice"):
        value = getattr(engine, attribute, None)
        if value:
            voice = str(value)
            break
    expressivity = getattr(engine, "expressivity", None)
    parts = [f"v{CLIP_VERSION}", provider, model, voice]
    if expressivity is not None:
        parts.append(f"expressivity={expressivity}")
    return "|".join(parts)


def clip_directory(engine: Any, base: Path | None = None) -> Path:
    """Where this voice's clips live; ``TUTOR_FILLER_CLIPS_DIR`` overrides the parent."""
    fingerprint = voice_fingerprint(engine)
    if base is None:
        base = Path(os.environ.get("TUTOR_FILLER_CLIPS_DIR")
                    or Path.home() / ".cache" / "open-tutor" / "fillers")
    digest = hashlib.sha256(fingerprint.encode()).hexdigest()[:10]
    slug = "".join(char if char.isalnum() else "-" for char in fingerprint.split("|")[1:3])
    return base / f"{slug.strip('-')}-{digest}"


def trim_silence(pcm: bytes, sample_rate: int, channels: int = 1,
                 floor: int = SILENCE_FLOOR, relative: float = 0.06,
                 pad_s: float = 0.02) -> bytes:
    """Drop leading and trailing silence so the sound starts and ends tight.

    Loudness is judged per 5 ms block and against 6% of the clip's own peak, so a
    quiet breath before the hum is trimmed too, not just digital silence.
    """
    samples = np.frombuffer(pcm, dtype=np.int16)
    channels = max(1, channels)
    usable = samples.size - (samples.size % channels)
    if usable == 0 or sample_rate <= 0:
        return b""
    frames = samples[:usable].reshape(-1, channels)
    peak = int(np.abs(frames).max())
    if peak <= 0:
        return b""
    threshold = max(floor, int(relative * peak))
    block = max(1, int(0.005 * sample_rate))
    count = frames.shape[0]
    loud = np.zeros(count, dtype=bool)
    for start in range(0, count, block):
        chunk = frames[start:start + block]
        loud[start:start + len(chunk)] = np.abs(chunk).max() > threshold
    hits = np.flatnonzero(loud)
    if hits.size == 0:
        return b""
    # Keep a little air around the sound so it does not start mid-click.
    pad = int(pad_s * sample_rate)
    start = max(0, int(hits[0]) - pad)
    end = min(count, int(hits[-1]) + 1 + pad)
    return frames[start:end].tobytes()


def clip_duration(pcm: bytes, sample_rate: int, channels: int = 1) -> float:
    if sample_rate <= 0 or not pcm:
        return 0.0
    frames = len(pcm) / (2 * max(1, channels))
    return frames / sample_rate


def energy_segments(pcm: bytes, sample_rate: int, channels: int = 1,
                    threshold: float = 0.25, min_s: float = 0.04) -> list[tuple[float, float]]:
    """Where the sound is loud, in seconds.

    A cheap stand-in for listening: "Mm" is one sustained hum, "Aha" two parts,
    a three-word phrase three. Counting them catches a TTS that spells letters out
    ("em-em") or reads punctuation aloud, which no duration check would.
    """
    if sample_rate <= 0 or channels < 1:
        return []
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    usable = samples.size - (samples.size % channels)
    frames = samples[:usable].reshape(-1, channels).mean(axis=1)
    hop = max(1, int(0.01 * sample_rate))
    if frames.size < hop:
        return []
    window = frames[: (frames.size // hop) * hop].reshape(-1, hop)
    envelope = np.sqrt(np.mean(window**2, axis=1))
    peak = float(envelope.max()) if envelope.size else 0.0
    if peak <= 0:
        return []
    envelope = envelope / peak
    smooth = np.convolve(envelope, np.ones(5) / 5, mode="same")
    needed = max(1, int(min_s / 0.01))
    segments: list[tuple[float, float]] = []
    start: int | None = None
    for index, loud in enumerate(smooth > threshold):
        if loud and start is None:
            start = index
        elif not loud and start is not None:
            if index - start >= needed:
                segments.append((start * 0.01, index * 0.01))
            start = None
    if start is not None and len(smooth) - start >= needed:
        segments.append((start * 0.01, len(smooth) * 0.01))
    return segments


def clip_problem(pcm: bytes, sample_rate: int, channels: int = 1) -> str | None:
    """Why a synthesized clip cannot be used, or ``None`` when it is fine."""
    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size == 0:
        return "empty"
    peak = int(np.abs(samples).max())
    if peak < 1200:
        return f"too quiet (peak {peak})"
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    if rms < 400:
        return f"almost silent (rms {rms:.0f})"
    duration = clip_duration(pcm, sample_rate, channels)
    if duration < MIN_CLIP_S:
        return f"too short ({duration:.2f} s)"
    if duration > MAX_CLIP_S:
        return f"too long ({duration:.2f} s)"
    return None


def write_wav(path: Path, pcm: bytes, sample_rate: int, channels: int = 1) -> None:
    """Write 16-bit PCM as WAV atomically, so a crash never leaves a half file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".wav.part")
    os.close(handle)
    temp = Path(temp_name)
    try:
        with wave.open(str(temp), "wb") as out:
            out.setnchannels(max(1, channels))
            out.setsampwidth(2)
            out.setframerate(sample_rate)
            out.writeframes(pcm)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


async def synthesize_pcm(engine: Any, text: str) -> tuple[bytes, int, int]:
    """One short phrase through the session's own TTS; returns raw audio and format."""
    chunks: list[bytes] = []
    sample_rate, channels = 0, 1
    async for event in engine.synthesize(text):
        frame = getattr(event, "frame", None)
        if frame is None:
            continue
        sample_rate = int(frame.sample_rate) or sample_rate
        channels = int(frame.num_channels) or channels
        chunks.append(bytes(frame.data))
    return b"".join(chunks), sample_rate, channels


async def make_clip(engine: Any, spec: ClipSpec, directory: Path) -> Clip | None:
    """Synthesize one filler, trying its spellings until one passes the checks."""
    for text in spec.texts:
        try:
            pcm, sample_rate, channels = await synthesize_pcm(engine, text)
        except Exception as error:  # a provider hiccup must not break the session
            log.warning("filler clip %s: synthesis failed (%s)", spec.name,
                        type(error).__name__)
            return None
        trimmed = trim_silence(pcm, sample_rate, channels)
        problem = clip_problem(trimmed, sample_rate, channels)
        if problem is not None:
            log.info("filler clip %s: %r rejected (%s)", spec.name, text, problem)
            continue
        path = directory / f"{spec.name}.wav"
        write_wav(path, trimmed, sample_rate, channels)
        log.info("filler clip %s: made from %r (%.2f s)", spec.name, text,
                 clip_duration(trimmed, sample_rate, channels))
        return Clip(spec.name, path, spec.kind)
    log.warning("filler clip %s: no spelling produced a usable sound", spec.name)
    return None


async def make_clips(engine: Any, directory: Path,
                     specs: tuple[ClipSpec, ...] = SPECS) -> list[Clip]:
    """Make every clip that is not cached yet and return the ones that exist."""
    clips: list[Clip] = []
    for spec in specs:
        path = directory / f"{spec.name}.wav"
        if path.is_file():
            clips.append(Clip(spec.name, path, spec.kind))
            continue
        clip = await make_clip(engine, spec, directory)
        if clip is not None:
            clips.append(clip)
    return clips


def cached_clips(directory: Path, specs: tuple[ClipSpec, ...] = SPECS) -> list[Clip]:
    return [Clip(spec.name, directory / f"{spec.name}.wav", spec.kind)
            for spec in specs if (directory / f"{spec.name}.wav").is_file()]


class FillerClips:
    """The clip set for one voice, generated once and reused from disk."""

    def __init__(self, engine: Any, directory: Path | None = None) -> None:
        self.engine = engine
        self.directory = directory or clip_directory(engine)
        self.clips: list[Clip] = []
        self._prepared = False
        self._failed = False

    @property
    def ready(self) -> bool:
        return bool(self.clips)

    def load_cached(self) -> list[Clip]:
        """Adopt clips already on disk (no TTS call)."""
        if not self.clips:
            self.clips = cached_clips(self.directory)
        return self.clips

    async def prepare(self) -> list[Clip]:
        """Generate whatever is missing. Runs in the background, never in a turn."""
        if self._prepared or self._failed:
            return self.clips
        self._prepared = True
        if self.load_cached():
            return self.clips
        try:
            self.clips = await make_clips(self.engine, self.directory)
        except Exception as error:  # disk, provider or decoder
            self._failed = True
            log.warning("filler sounds are off: could not make the clips (%s: %s)",
                        type(error).__name__, error)
            return self.clips
        if not self.clips:
            self._failed = True
            log.warning("filler sounds are off: no clip passed the checks")
        return self.clips


# ---- the decision and the playback ----------------------------------------------


class Fillers:
    """Decides when the fox makes a small sound, and plays it through LiveKit.

    The rules, in one place:

    - only for a *child* turn (speech or typed), never for a session event such as
      the greeting or a screen prompt;
    - only once the reply is late by ``delay`` seconds, and only while the agent
      is still thinking: a reply that has started, or a child who has started
      speaking again, cancels it;
    - at most one per turn, never the same clip twice in a row, and nothing in
      quiet-work or resource mode;
    - nothing it plays reaches the chat context, the transcript or the caption.
    """

    def __init__(
        self,
        *,
        clips: FillerClips | None = None,
        engine: Any = None,
        delay: float = DEFAULT_DELAY_S,
        volume: float = DEFAULT_VOLUME,
        player: Any = None,
        rng: random.Random | None = None,
        mode: Callable[[], str] | None = None,
    ) -> None:
        self.clips = clips if clips is not None else (
            FillerClips(engine) if engine is not None else None)
        self.delay = max(0.05, float(delay))
        self.volume = max(0.0, min(1.0, float(volume)))
        self._player = player
        self._owns_player = player is None
        self._rng = rng or random.Random()
        self._mode = mode or (lambda: "talking")
        self._session: Any = None
        self._turn = 0
        # A turn stays open until the reply starts, the child speaks again or the
        # agent goes quiet: only then can another child turn arm a filler.
        self._turn_open = False
        self._armed_turn: int | None = None
        self._played_turn: int | None = None
        self._timer: asyncio.Task | None = None
        self._playing: PlayHandle | None = None
        self._playing_clip: str | None = None
        self._started_playing_at = 0.0
        self._last_clip: str | None = None
        self._closed = False
        self._prep_task: asyncio.Task | None = None

    # -- lifecycle ---------------------------------------------------------------

    async def start(self, room: Any = None) -> None:
        """Publish the background track and start making the clips."""
        if self.clips is not None:
            self.clips.load_cached()
            if not self.clips.ready:
                self._prep_task = asyncio.create_task(self._prepare_clips())
        if self._player is not None or room is None:
            return
        try:
            player = BackgroundAudioPlayer()
            await player.start(room=room)
            self._player = player
            log.info("filler sounds ready from %s", self.clips.directory if self.clips else "?")
        except Exception as error:  # no track, no fillers; never break the session
            log.warning("filler sounds are off: %s: %s", type(error).__name__, error)
            self._player = None

    async def _prepare_clips(self) -> None:
        assert self.clips is not None
        try:
            await self.clips.prepare()
        except Exception as error:  # prepare() already logs; belt and braces
            log.warning("filler sounds are off: %s: %s", type(error).__name__, error)

    def attach(self, session: Any, mode: Callable[[], str] | None = None) -> None:
        """Follow the session's turns and state. Call before ``session.start()``."""
        self._session = session
        if mode is not None:
            self._mode = mode
        session.on("conversation_item_added", self._on_item)
        session.on("agent_state_changed", self._on_agent_state)
        session.on("user_state_changed", self._on_user_state)

    async def aclose(self) -> None:
        self._closed = True
        self._cancel(reason="closed", stop_playback=True)
        if self._prep_task is not None:
            self._prep_task.cancel()
            self._prep_task = None
        player, self._player = self._player, None
        if player is not None and self._owns_player:
            try:
                await player.aclose()
            except Exception as error:
                log.warning("closing the filler track failed: %s", error)

    # -- session events ----------------------------------------------------------

    def _on_item(self, event: Any) -> None:
        item = getattr(event, "item", None)
        if getattr(item, "type", None) != "message" or self._closed:
            return
        role = getattr(item, "role", "")
        text = _item_text(item)
        if role == "user":
            # The worker's own prompts ("[Session event, ...]", "[Screen page ...]")
            # and the greeting are not the child's turn: no filler for them.
            if not text or text.startswith("["):
                return
            self.arm()
        elif role == "assistant" and text:
            # The reply's words are in: whatever happens next, no filler.
            self._cancel(reason="reply_text", stop_playback=True)

    def _on_agent_state(self, event: Any) -> None:
        state = getattr(event, "new_state", "")
        if state == "speaking":
            self._cancel(reason="reply_audio", stop_playback=True)
        elif state == "listening":
            # The turn is over (answered or not): the next child turn gets its own
            # chance at a filler.
            self._cancel(reason="turn_closed", stop_playback=True)

    def _on_user_state(self, event: Any) -> None:
        if getattr(event, "new_state", "") == "speaking":
            self._cancel(reason="child_speaking", stop_playback=True)

    # -- the decision ------------------------------------------------------------

    def arm(self) -> None:
        """The child's turn just ended and a reply was requested: start the clock."""
        blocker = self._arm_blocker()
        if blocker is not None:
            self._record_skip("arm", blocker)
            return
        self._turn += 1
        self._turn_open = True
        self._armed_turn = self._turn
        if self._timer is not None:
            self._timer.cancel()
        self._timer = asyncio.create_task(self._wait_and_play(self._turn))

    def _arm_blocker(self) -> str | None:
        if self._closed:
            return "closed"
        if self._player is None:
            return "no_player"
        if self.clips is None or not self.clips.ready:
            return "no_clips"
        if self._mode() != "talking":
            return f"mode:{self._mode()}"
        if self._turn_open:
            return "same_turn"  # the same turn: it has its one chance already
        return None

    async def _wait_and_play(self, turn: int) -> None:
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            raise
        if self._closed or turn != self._armed_turn or self._played_turn == turn:
            return
        blocker = self._play_blocker()
        if blocker is not None:
            self._record_skip("delay", blocker)
            return
        self._play_now(turn)

    def _play_blocker(self) -> str | None:
        """The last look before the sound: everything must still be true."""
        session = self._session
        if session is not None:
            state = getattr(session, "agent_state", "thinking")
            if state != "thinking":
                return f"tutor_{state}"  # the reply started, or nothing is being answered
            if getattr(session, "user_state", "listening") == "speaking":
                return "child_speaking"
        if self._mode() != "talking":
            return f"mode:{self._mode()}"
        if self.clips is None or not self.clips.ready:
            return "no_clips"
        if self._player is None:
            return "no_player"
        return None

    def _record_skip(self, where: str, reason: str) -> None:
        record_active("filler_skipped", {"where": where, "reason": reason,
                                         "turn": self._turn})

    def _pick(self) -> Clip:
        assert self.clips is not None
        available = [clip for clip in self.clips.clips if clip.name != self._last_clip]
        if not available:
            available = list(self.clips.clips)
        weights = [PHRASE_WEIGHT if clip.kind == "phrase" else 1.0 for clip in available]
        return self._rng.choices(available, weights=weights, k=1)[0]

    def _play_now(self, turn: int) -> None:
        clip = self._pick()
        self._armed_turn = None
        self._played_turn = turn
        self._last_clip = clip.name
        try:
            handle = self._player.play(AudioConfig(source=str(clip.path), volume=self.volume))
        except Exception as error:
            log.warning("filler sound %s could not play: %s", clip.name, error)
            return
        self._playing = handle
        self._playing_clip = clip.name
        self._started_playing_at = asyncio.get_running_loop().time()
        log.info("filler %s after %.2f s", clip.name, self.delay)
        record_active("filler", {"clip": clip.name, "kind": clip.kind,
                                 "turn": turn, "after_s": round(self.delay, 3)})

    # -- stopping ----------------------------------------------------------------

    def _cancel(self, *, reason: str, stop_playback: bool) -> None:
        self._armed_turn = None
        if reason != "closed":
            self._turn_open = False
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()
        self._timer = None
        if stop_playback:
            self.stop(reason=reason)

    def stop(self, *, reason: str) -> None:
        """Cut the sound at once (the child spoke, or the reply began)."""
        handle, self._playing = self._playing, None
        clip, self._playing_clip = self._playing_clip, None
        if handle is None or handle.done():
            return
        try:
            handle.stop()
        except Exception as error:
            log.warning("stopping filler %s failed: %s", clip, error)
        # The player keeps up to 400 ms queued in its audio source; clear it so the
        # sound cannot run into the child's words or the reply. Nothing else uses
        # this source (the speech track is a separate one).
        queue = getattr(self._player, "_audio_source", None)
        clear = getattr(queue, "clear_queue", None)
        if callable(clear):
            try:
                clear()
            except Exception:
                pass
        played = 0.0
        try:
            played = asyncio.get_running_loop().time() - self._started_playing_at
        except RuntimeError:
            pass
        record_active("filler_stopped", {"clip": clip, "reason": reason,
                                         "played_s": round(played, 3)})


def _item_text(item: Any) -> str:
    try:
        text = item.text_content  # a property, not a method
    except Exception:
        return ""
    return text if isinstance(text, str) else ""


def build_fillers(engine: Any, delay: float | None = None,
                  environ: dict[str, str] | None = None) -> Fillers | None:
    """The configured fillers, or ``None`` when ``TUTOR_FILLERS`` is off."""
    env = os.environ if environ is None else environ
    if env.get("TUTOR_FILLERS") != "1":
        return None
    return Fillers(engine=engine, delay=DEFAULT_DELAY_S if delay is None else delay)
