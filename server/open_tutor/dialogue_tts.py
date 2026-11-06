"""ElevenLabs Eleven v4 voices over the single-context text-to-dialogue WebSocket.

ElevenLabs serves `eleven_v4` and `eleven_v4_turbo` only through text-to-dialogue. The
documented realtime endpoint for them is `wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input`
(one dialogue per socket). LiveKit's ElevenLabs plugin 1.8.10 sends v3 and v4 models to
`text-to-dialogue/multi-stream-input` instead, which ElevenLabs documents as v3-only. It
answered for v4 Turbo in a probe on 2026-11-04, but an undocumented route is not one to
build a family service on, so this adapter speaks the documented protocol:

    -> {"voices": [voice_id]}                         first message, exactly one voice
    -> {"inputs": [{"text": ..., "voice_id": ...}]}   one per sentence, then {"flush": true}
    -> {"keep_alive": true}                           while the reply waits for text (20 s idle limit)
    -> {"close_socket": true}                         after the last sentence
    <- {"audio": b64, "alignment": {...} | null, ...}  alignment times restart at 0 per message
    <- {"is_final_audio_for_turn": true}               after each flush
    <- {"is_final": true}                              after close_socket
    <- {"message", "error", "code"}                    on failure, then the socket closes

Each utterance gets its own socket (about 90 ms to connect from the home lab). An
interruption cancels the stream, which closes that socket, so no audio of an
interrupted reply can arrive afterwards.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import weakref
from dataclasses import dataclass
from urllib.parse import urlencode

import aiohttp
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIError,
    APIStatusError,
    APITimeoutError,
    tokenize,
    tts,
    utils,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS
from livekit.agents.voice.io import TimedString

log = logging.getLogger("open-tutor")

API_BASE_URL = "wss://api.elevenlabs.io/v1"
PATH = "/text-to-dialogue/stream-input"
SAMPLE_RATE = 24000
OUTPUT_FORMAT = f"pcm_{SAMPLE_RATE}"  # raw 16-bit mono: exact clock for caption timing
KEEP_ALIVE_INTERVAL = 10.0  # the server closes a socket idle for 20 s


def is_dialogue_model(model: str) -> bool:
    return model.startswith(("eleven_v3", "eleven_v4"))


@dataclass(frozen=True)
class DialogueOptions:
    api_key: str
    voice_id: str
    model: str
    language: str
    base_url: str = API_BASE_URL
    enable_logging: bool = True

    def url(self) -> str:
        query = {
            "model_id": self.model,
            "output_format": OUTPUT_FORMAT,
            "language_code": self.language,
            "sync_alignment": "true",
            "apply_text_normalization": "auto",
            "enable_logging": str(self.enable_logging).lower(),
        }
        return f"{self.base_url}{PATH}?{urlencode(query)}"


class _Captions:
    """Turns per-message character alignment into word timings on the utterance clock.

    In the recorded v4 Turbo stream, alignment times restart at 0 in every message, and
    the spans of one turn (the audio for one flushed sentence) add up to that turn's
    audio. So a turn starts at the audio received before it, and within the turn each
    message continues where the previous message's alignment ended. A word is emitted
    once the next one starts.
    """

    def __init__(self) -> None:
        self.audio_ms = 0.0
        self._turn_start_ms = 0.0
        self._turn_clock_ms = 0.0
        self._chars: list[tuple[str, float, float]] = []  # (char, start ms, end ms)

    def add(self, alignment: dict | None, audio_bytes: int) -> list[TimedString]:
        words: list[TimedString] = []
        if alignment:
            chars = alignment.get("chars") or []
            starts = alignment.get("char_start_times_ms") or []
            durations = alignment.get("char_durations_ms") or []
            if chars and len(chars) == len(starts) == len(durations):
                base = self._turn_start_ms + self._turn_clock_ms
                for char, start, duration in zip(chars, starts, durations):
                    self._chars.append((char, base + start, base + start + duration))
                self._turn_clock_ms += starts[-1] + durations[-1]
                words = self._take(final=False)
        self.audio_ms += audio_bytes / (2 * SAMPLE_RATE) * 1000
        return words

    def end_turn(self) -> None:
        self._turn_start_ms = self.audio_ms
        self._turn_clock_ms = 0.0

    def finish(self) -> list[TimedString]:
        return self._take(final=True)

    def _take(self, final: bool) -> list[TimedString]:
        # A word is its characters plus the spaces after it, so the joined captions read
        # exactly like the spoken text. It is complete once the next word starts.
        starts = [
            i for i, (char, _, _) in enumerate(self._chars)
            if not char.isspace() and (i == 0 or self._chars[i - 1][0].isspace())
        ]
        if final and self._chars:
            starts.append(len(self._chars))
        if not starts or starts[0] != 0:
            starts.insert(0, 0)
        words = []
        for a, b in zip(starts, starts[1:]):
            if a == b:
                continue
            text = "".join(char for char, _, _ in self._chars[a:b])
            end = self._chars[b][1] if b < len(self._chars) else self._chars[b - 1][2]
            words.append(TimedString(text=text, start_time=self._chars[a][1] / 1000, end_time=end / 1000))
        self._chars = self._chars[starts[-1]:]
        return words


class DialogueTTS(tts.TTS):
    def __init__(
        self,
        *,
        api_key: str,
        voice_id: str,
        model: str = "eleven_v4_turbo",
        language: str = "sv",
        base_url: str = API_BASE_URL,
        http_session: aiohttp.ClientSession | None = None,
        tokenizer: tokenize.SentenceTokenizer | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("ElevenLabs needs ELEVENLABS_API_KEY in the backend environment")
        if not is_dialogue_model(model):
            raise ValueError(f"{model} is not a text-to-dialogue model")
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=True, aligned_transcript=True),
            sample_rate=SAMPLE_RATE,
            num_channels=1,
        )
        self._opts = DialogueOptions(api_key=api_key, voice_id=voice_id, model=model, language=language, base_url=base_url)
        self._session = http_session
        self._tokenizer = tokenizer or tokenize.blingfire.SentenceTokenizer()
        self._streams = weakref.WeakSet[DialogueStream]()
        self._route_logged = False

    @property
    def model(self) -> str:
        return self._opts.model

    @property
    def provider(self) -> str:
        return "ElevenLabs"

    def route(self) -> str:
        """The actual synthesis route, for logs. No key."""
        return f"elevenlabs {PATH} model {self._opts.model} voice {self._opts.voice_id} lang {self._opts.language}"

    def _ensure_session(self) -> aiohttp.ClientSession:
        if not self._session:
            self._session = utils.http_context.http_session()
        return self._session

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        return self._synthesize_with_stream(text, conn_options=conn_options)

    def stream(self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS) -> DialogueStream:
        stream = DialogueStream(tts=self, conn_options=conn_options)
        self._streams.add(stream)
        return stream

    async def aclose(self) -> None:
        for stream in list(self._streams):
            await stream.aclose()
        self._streams.clear()


class DialogueStream(tts.SynthesizeStream):
    def __init__(self, *, tts: DialogueTTS, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts, conn_options=conn_options)
        self._tts: DialogueTTS = tts
        self._opts = tts._opts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        request_id = utils.shortuuid()
        output_emitter.initialize(
            request_id=request_id,
            sample_rate=SAMPLE_RATE,
            num_channels=1,
            stream=True,
            mime_type="audio/pcm",
        )
        output_emitter.start_segment(segment_id=request_id)
        opened = time.perf_counter()
        try:
            ws = await asyncio.wait_for(
                self._tts._ensure_session().ws_connect(
                    self._opts.url(), headers={"xi-api-key": self._opts.api_key}, heartbeat=None
                ),
                self._conn_options.timeout,
            )
        except asyncio.TimeoutError as error:
            raise APITimeoutError() from error
        except aiohttp.WSServerHandshakeError as error:
            raise APIStatusError(message=error.message, status_code=error.status) from error
        except Exception as error:
            raise APIConnectionError("could not connect to ElevenLabs text-to-dialogue") from error
        if not self._tts._route_logged:
            self._tts._route_logged = True
            log.info("tts connected: %s", self._tts.route())

        sentences = self._tts._tokenizer.stream()
        last_send = time.monotonic()
        first_text: float | None = None

        async def send(message: dict) -> None:
            nonlocal last_send
            await ws.send_str(json.dumps(message, ensure_ascii=False))
            last_send = time.monotonic()

        async def read_input() -> None:
            async for data in self._input_ch:
                if isinstance(data, self._FlushSentinel):
                    sentences.flush()
                else:
                    sentences.push_text(data)
            sentences.end_input()

        async def send_text() -> None:
            nonlocal first_text
            await send({"voices": [self._opts.voice_id]})
            async for sentence in sentences:
                text = sentence.token.strip()
                if not text:
                    continue
                if first_text is None:
                    first_text = time.perf_counter()
                # The server waits for ~40 characters before speaking; flushing each
                # sentence lets a short reply such as "Ja." start at once.
                await send({"inputs": [{"text": text + " ", "voice_id": self._opts.voice_id}]})
                await send({"flush": True})
                self._mark_started()
            await send({"close_socket": True})

        async def keep_alive() -> None:
            while True:
                await asyncio.sleep(max(0.0, last_send + KEEP_ALIVE_INTERVAL - time.monotonic()))
                if time.monotonic() - last_send >= KEEP_ALIVE_INTERVAL:
                    await send({"keep_alive": True})

        async def receive() -> None:
            captions = _Captions()
            first_audio: float | None = None
            while True:
                message = await ws.receive()
                if message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    raise APIStatusError(
                        "ElevenLabs text-to-dialogue closed before the reply finished",
                        status_code=ws.close_code or -1,
                    )
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = json.loads(message.data)
                if data.get("error"):
                    # Machine-readable code and message only; never the text.
                    raise APIStatusError(
                        f"ElevenLabs text-to-dialogue: {data.get('error')}: {data.get('message')}",
                        status_code=int(data.get("code") or -1),
                        retryable=False,
                    )
                audio = base64.b64decode(data["audio"]) if data.get("audio") else b""
                words = captions.add(data.get("alignment"), len(audio))
                if audio:
                    if first_audio is None and first_text is not None:
                        first_audio = time.perf_counter()
                        log.info(
                            "tts first audio %.0f ms after first sentence (%.0f ms after connect start)",
                            (first_audio - first_text) * 1000,
                            (first_audio - opened) * 1000,
                        )
                    output_emitter.push(audio)
                if words:
                    output_emitter.push_timed_transcript(words)
                if data.get("is_final_audio_for_turn"):
                    captions.end_turn()
                if data.get("is_final"):
                    output_emitter.push_timed_transcript(captions.finish())
                    return

        tasks = [
            asyncio.create_task(read_input()),
            asyncio.create_task(send_text()),
            asyncio.create_task(keep_alive()),
        ]
        try:
            await receive()
        except (APIError, asyncio.CancelledError):
            raise
        except Exception as error:
            raise APIConnectionError("ElevenLabs text-to-dialogue failed") from error
        finally:
            # Cancellation (an interruption) lands here too: closing the socket stops
            # generation, and nothing more is pushed to the emitter.
            await utils.aio.gracefully_cancel(*tasks)
            await sentences.aclose()
            await ws.close()
            output_emitter.end_segment()
