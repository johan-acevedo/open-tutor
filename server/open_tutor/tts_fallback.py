"""Google Cloud Chirp 3: HD builder and session-sticky TTS failover wrapper.

Why not LiveKit's stock ``tts.FallbackAdapter`` directly:
- Stock ``FallbackAdapter`` sets ``aligned_transcript = all(...)``, which drops
  ElevenLabs Bella's word-by-word synced captions to sentence-level even while
  Bella is healthy, because Google Cloud Chirp 3: HD returns ``aligned_transcript=False``.
  LiveKit 1.8.10's ``_aligned_transcript_or_text`` already falls back cleanly to
  plain spoken text whenever a stream emits no ``TimedString``s, and refreshing
  ``self._capabilities`` on failover lets subsequent replies forward plain
  captions immediately without waiting for an empty aligned stream to close.
- A child should not hear voices ping-pong mid-lesson, nor wait through repeated
  retries when ElevenLabs monthly credits run out: failover is fast (zero inner
  retries; outer stream owns retries), session-sticky for the rest of the call,
  and persists a shared file-backed cooldown across LiveKit job processes on
  quota/auth failures so the next session starts straight on the fallback voice.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from livekit import rtc
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIError,
    APIStatusError,
    APITimeoutError,
    tts,
    utils,
)
from livekit.agents.tts.tts import _ChunkedStreamFromStream
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, USERDATA_TIMED_TRANSCRIPT
from livekit.plugins import google as google_plugin

from .debug_log import record_active

log = logging.getLogger("open-tutor")

DEFAULT_GOOGLE_VOICE = "sv-SE-Chirp3-HD-Aoede"
DEFAULT_GOOGLE_LANGUAGE = "sv-SE"
DEFAULT_SAMPLE_RATE = 24000
DEFAULT_COOLDOWN_S = 600.0
_CLOUD_PLATFORM_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)

_QUOTA_STATUS_CODES = frozenset({401, 402, 429})
_QUOTA_MARKERS = (
    "quota",
    "credit",
    "insufficient",
    "limit_exceeded",
    "payment_required",
    "unauthorized",
    "unauthenticated",
    "voice_not_found",
)


def describe_tts(engine: Any) -> str:
    """Human-readable route label for logs and analytics. Never contains keys."""
    if hasattr(engine, "route") and callable(engine.route):
        return str(engine.route())
    provider = str(getattr(engine, "provider", type(engine).__name__))
    model = str(getattr(engine, "model", "") or "")
    voice = extract_voice_name(engine)
    parts = [p for p in (provider, model, voice) if p]
    return " ".join(parts)


def extract_voice_name(engine: Any) -> str:
    """Best-effort voice id/name across ElevenLabs, Google, Deepgram and Cartesia."""
    for attr in ("voice_id", "voice"):
        val = getattr(engine, attr, None)
        if isinstance(val, str) and val:
            return val
    opts = getattr(engine, "_opts", None)
    if opts is not None:
        for attr in ("voice_id", "voice_name"):
            val = getattr(opts, attr, None)
            if isinstance(val, str) and val:
                return val
        voice_obj = getattr(opts, "voice", None)
        if isinstance(voice_obj, str) and voice_obj:
            return voice_obj
        name = getattr(voice_obj, "name", None)
        if isinstance(name, str) and name:
            return name
    return ""


def is_quota_or_auth_error(error: BaseException) -> bool:
    """True when the provider refused the request for quota/billing/auth reasons.

    Those will not recover within a second, so we put the primary on cooldown
    across sessions instead of paying a failed handshake on every new call.
    """
    status = getattr(error, "status_code", None)
    if isinstance(status, int) and status in _QUOTA_STATUS_CODES:
        return True
    msg = str(error).lower()
    return any(marker in msg for marker in _QUOTA_MARKERS)


def parse_cooldown_s(environ: dict[str, str] | Any | None = None) -> float:
    env = os.environ if environ is None else environ
    raw = str(env.get("TUTOR_TTS_FALLBACK_COOLDOWN_S", DEFAULT_COOLDOWN_S)).strip()
    try:
        val = float(raw)
    except ValueError:
        raise ValueError(f"TUTOR_TTS_FALLBACK_COOLDOWN_S must be a number, not {raw!r}") from None
    if val < 0:
        raise ValueError(f"TUTOR_TTS_FALLBACK_COOLDOWN_S must not be negative, not {raw!r}")
    return val


def default_cooldown_path(environ: dict[str, str] | Any | None = None) -> Path:
    """Shared per-host cooldown file so separate LiveKit job processes share state."""
    env = os.environ if environ is None else environ
    override = (env.get("TUTOR_TTS_COOLDOWN_FILE") or "").strip()
    if override:
        return Path(override)
    cache_home = (env.get("XDG_CACHE_HOME") or "").strip() or str(Path.home() / ".cache")
    return Path(cache_home) / "open-tutor" / "tts-cooldowns.json"


def _non_empty_str(mapping: dict[str, Any], key: str) -> bool:
    val = mapping.get(key)
    return isinstance(val, str) and bool(val.strip())


def _load_google_credentials_from_info(creds_info: Any) -> Any:
    """Eagerly parse and validate explicit GCP credentials (service_account or authorized_user).

    Uses credential-type-specific loaders instead of the deprecated generic
    ``load_credentials_from_dict`` / ``load_credentials_from_file`` helpers so
    corrupt keys, null required fields, bad types (e.g. numeric ``expiry``), or
    unsupported credential types fail cleanly with ``ValueError`` at build time
    without warnings or secret leakage.
    """
    from google.oauth2 import credentials as user_credentials
    from google.oauth2 import service_account

    if not isinstance(creds_info, dict):
        raise ValueError("invalid credentials object")
    cred_type = creds_info.get("type")
    try:
        if cred_type == "service_account":
            if not all(
                _non_empty_str(creds_info, k)
                for k in ("private_key", "client_email", "token_uri")
            ):
                raise ValueError("incomplete service_account credentials")
            creds = service_account.Credentials.from_service_account_info(
                creds_info, scopes=_CLOUD_PLATFORM_SCOPES
            )
            if not getattr(creds, "service_account_email", None) or not getattr(creds, "signer", None):
                raise ValueError("invalid service_account credentials")
            return creds
        if cred_type == "authorized_user":
            if not all(
                _non_empty_str(creds_info, k)
                for k in ("client_id", "client_secret", "refresh_token")
            ):
                raise ValueError("incomplete authorized_user credentials")
            expiry = creds_info.get("expiry")
            if expiry is not None and not isinstance(expiry, str):
                raise ValueError("invalid authorized_user expiry")
            creds = user_credentials.Credentials.from_authorized_user_info(
                creds_info, scopes=_CLOUD_PLATFORM_SCOPES
            )
            if not getattr(creds, "refresh_token", None):
                raise ValueError("invalid authorized_user credentials")
            return creds
    except ValueError:
        raise
    except Exception:
        # Normalize any third-party parser error (e.g. AttributeError/TypeError)
        # into a fixed ValueError so malformed fallback credentials never abort a session.
        raise ValueError("invalid GCP credentials") from None
    raise ValueError("unsupported GCP credential type")


def build_google_tts(
    *,
    voice: str = "",
    language: str = DEFAULT_GOOGLE_LANGUAGE,
    environ: dict[str, str] | Any | None = None,
) -> google_plugin.TTS:
    """Build a streaming Google Cloud Chirp 3: HD TTS engine.

    Credentials come from:
    1. ``GOOGLE_TTS_CREDENTIALS_JSON`` (compact JSON string, e.g. from Infisical),
    2. ``GOOGLE_APPLICATION_CREDENTIALS`` (path to a service account JSON file), or
    3. Application Default Credentials (``gcloud auth application-default login``).

    Parses and validates credentials eagerly via ``google.oauth2`` / ``google.auth``
    and passes the validated ``Credentials`` object to ``livekit-plugins-google``
    so corrupt or incomplete credentials fail at session start instead of
    mid-lesson. Never logs or includes credential values in exceptions.
    """
    import google.auth
    from google.auth.exceptions import GoogleAuthError

    env = os.environ if environ is None else environ
    voice_name = (voice or DEFAULT_GOOGLE_VOICE).strip()
    raw_json = (env.get("GOOGLE_TTS_CREDENTIALS_JSON") or "").strip()
    if raw_json:
        try:
            creds_info = json.loads(raw_json)
        except json.JSONDecodeError:
            raise ValueError("GOOGLE_TTS_CREDENTIALS_JSON is not valid JSON") from None
        try:
            creds = _load_google_credentials_from_info(creds_info)
        except ValueError:
            raise ValueError("GOOGLE_TTS_CREDENTIALS_JSON is not valid GCP credentials") from None
        return google_plugin.TTS(
            language=language,
            voice_name=voice_name,
            sample_rate=DEFAULT_SAMPLE_RATE,
            use_streaming=True,
            credentials=creds,
        )

    creds_file = (env.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if creds_file:
        if not os.path.isfile(creds_file):
            raise ValueError("GOOGLE_APPLICATION_CREDENTIALS file does not exist")
        try:
            creds_info = json.loads(Path(creds_file).read_text(encoding="utf-8"))
            creds = _load_google_credentials_from_info(creds_info)
        except (OSError, ValueError):
            raise ValueError(
                "GOOGLE_APPLICATION_CREDENTIALS is not a valid GCP credentials file"
            ) from None
        return google_plugin.TTS(
            language=language,
            voice_name=voice_name,
            sample_rate=DEFAULT_SAMPLE_RATE,
            use_streaming=True,
            credentials=creds,
        )

    try:
        creds, _ = google.auth.default(scopes=_CLOUD_PLATFORM_SCOPES)
    except Exception:
        # Normalize any ADC parse error (including AttributeError on malformed
        # gcloud ADC files such as numeric expiry) to ValueError so build_tts()
        # degrades cleanly to primary alone.
        raise ValueError(
            "Google Cloud TTS needs GOOGLE_TTS_CREDENTIALS_JSON, "
            "GOOGLE_APPLICATION_CREDENTIALS, or gcloud ADC"
        ) from None
    return google_plugin.TTS(
        language=language,
        voice_name=voice_name,
        sample_rate=DEFAULT_SAMPLE_RATE,
        use_streaming=True,
        credentials=creds,
    )


class CooldownLedger:
    """Cooldown store for primary TTS routes that hit quota/auth limits.

    When ``path`` (or ``path_factory``) is provided, deadlines are persisted as
    Unix epoch timestamps in a private (0600) JSON file via atomic replace so
    separate LiveKit job processes on the same host share cooldown state.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        *,
        path: Path | str | None = None,
        path_factory: Callable[[], Path] | None = None,
    ) -> None:
        self._clock = clock
        self._path = Path(path) if path is not None else None
        self._path_factory = path_factory
        self._until: dict[str, float] = {}

    def _resolve_path(self) -> Path | None:
        if self._path is not None:
            return self._path
        if self._path_factory is not None:
            return self._path_factory()
        return None

    @contextlib.contextmanager
    def _file_lock(self, path: Path) -> Iterator[None]:
        """Serialize read-modify-write updates across concurrent LiveKit job processes."""
        lock_path = path.with_name(f".{path.name}.lock")
        fd: int | None = None
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            os.chmod(lock_path, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            if fd is not None:
                os.close(fd)
                fd = None
        try:
            yield
        finally:
            if fd is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)

    def _read_disk(self, path: Path) -> dict[str, float]:
        try:
            raw = path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except (OSError, ValueError):
            return {}
        if not isinstance(parsed, dict):
            return {}
        out: dict[str, float] = {}
        for k, v in parsed.items():
            if isinstance(k, str) and isinstance(v, (int, float)):
                out[k] = float(v)
        return out

    def _write_disk(self, path: Path, entries: dict[str, float], now: float) -> None:
        live = {k: v for k, v in entries.items() if v > now}
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(path.parent), prefix=".tts-cooldowns-", suffix=".tmp"
            )
            tmp_path = Path(tmp_name)
            try:
                os.chmod(tmp_path, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(live, handle, sort_keys=True)
                os.replace(tmp_path, path)
            finally:
                tmp_path.unlink(missing_ok=True)
        except OSError:
            log.debug("could not persist TTS cooldown file", exc_info=True)

    def is_cooling_down(self, key: str) -> bool:
        return self.remaining_s(key) > 0.0

    def remaining_s(self, key: str) -> float:
        now = self._clock()
        deadline = self._until.get(key, 0.0)
        path = self._resolve_path()
        if path is not None:
            disk = self._read_disk(path)
            disk_deadline = disk.get(key, 0.0)
            if disk_deadline > deadline:
                deadline = disk_deadline
                self._until[key] = deadline
        rem = deadline - now
        if rem <= 0.0:
            self._until.pop(key, None)
            return 0.0
        return rem

    def trip(self, key: str, seconds: float) -> None:
        if seconds <= 0.0:
            return
        now = self._clock()
        deadline = max(self._until.get(key, 0.0), now + seconds)
        self._until[key] = deadline
        path = self._resolve_path()
        if path is not None:
            with self._file_lock(path):
                disk = self._read_disk(path)
                disk[key] = max(disk.get(key, 0.0), deadline)
                self._write_disk(path, disk, now)

    def clear(self) -> None:
        self._until.clear()
        path = self._resolve_path()
        if path is not None:
            with self._file_lock(path):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


_COOLDOWNS = CooldownLedger(path_factory=default_cooldown_path)


def reset_cooldowns() -> None:
    """Clear shared TTS cooldowns (for tests)."""
    _COOLDOWNS.clear()


def _error_summary(error: BaseException) -> dict[str, Any]:
    info: dict[str, Any] = {"error_type": type(error).__name__}
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        info["status_code"] = status
    return info


class _RedactPluginPayloadFilter(logging.Filter):
    """Strip structured raw provider payloads (e.g. Cartesia error/lk.pii.data)
    from third-party TTS plugin log records so spoken text never lands in logs."""

    _SCRUB_KEYS = ("error", "lk.pii.data", "payload", "body")

    def filter(self, record: logging.LogRecord) -> bool:
        for key in self._SCRUB_KEYS:
            if key in record.__dict__:
                record.__dict__[key] = "<redacted>"
        return True


def _install_plugin_log_redaction() -> None:
    """Idempotently attach structured-payload redaction to noisy TTS plugin loggers."""
    for logger_name in ("livekit.plugins.cartesia",):
        plugin_logger = logging.getLogger(logger_name)
        if not any(isinstance(f, _RedactPluginPayloadFilter) for f in plugin_logger.filters):
            plugin_logger.addFilter(_RedactPluginPayloadFilter())


def _sanitize_error(
    error: BaseException,
    provider: str,
    *,
    force_non_retryable: bool = False,
) -> APIError:
    """Strip provider bodies and raw messages so spoken text can never reach SDK logs or spans.

    Preserves only error class family, provider name, HTTP/WS status code, and
    retryability. Converts provider-originated 499 statuses into
    ``APIConnectionError`` so LiveKit's stream loop does not silently treat a
    provider abort as a completed utterance. Always raise the returned exception
    ``from None``.
    """
    err_type = type(error).__name__
    retryable = False if force_non_retryable else bool(getattr(error, "retryable", True))
    if isinstance(error, APIStatusError):
        if error.status_code == 499:
            return APIConnectionError(
                f"TTS provider {provider} aborted ({err_type}, status=499)",
                retryable=retryable,
            )
        return APIStatusError(
            f"TTS provider {provider} failed ({err_type}, status={error.status_code})",
            status_code=error.status_code,
            request_id=None,
            body=None,
            retryable=retryable,
        )
    if isinstance(error, APITimeoutError):
        return APITimeoutError(
            f"TTS provider {provider} timed out ({err_type})",
            retryable=retryable,
        )
    return APIConnectionError(
        f"TTS provider {provider} failed ({err_type})",
        retryable=retryable,
    )


def _wrap_child_run(
    child: Any, provider: str, raw_errors: list[BaseException]
) -> None:
    """Sanitize child stream errors INSIDE LiveKit's inner ``_attempt_span``.

    Prevents raw provider errors (which may echo spoken text) from being
    recorded on OpenTelemetry spans or emitted by the child's ``_main_task``,
    prevents provider 499 statuses from being swallowed as success, and raises
    a sanitized empty-audio error before LiveKit's ``_main_task`` can record
    ``no audio frames were pushed for text: <utterance>`` on the request span.
    The raw error is retained in memory only for ``is_quota_or_auth_error``.
    """
    orig_run = getattr(child, "_run", None)
    if not callable(orig_run):
        return

    async def _sanitized_run(output_emitter: tts.AudioEmitter) -> None:
        try:
            await orig_run(output_emitter)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            raw_errors.append(err)
            raise _sanitize_error(err, provider) from None

        pushed_text = getattr(child, "_pushed_text", None)
        if pushed_text is None:
            pushed_text = getattr(child, "_input_text", "")
        if str(pushed_text).strip():
            if not getattr(output_emitter, "_started", False):
                err = _EmptyAudioError()
                raw_errors.append(err)
                raise APIConnectionError(
                    f"TTS provider {provider} produced no audio", retryable=True
                ) from None
            output_emitter.end_input()
            await output_emitter.join()
            if output_emitter.pushed_duration() <= 0.0:
                err = _EmptyAudioError()
                raw_errors.append(err)
                raise APIConnectionError(
                    f"TTS provider {provider} produced no audio", retryable=True
                ) from None

    child._run = _sanitized_run


class _EmptyAudioError(Exception):
    """Internal signal when a child engine returned no PCM for non-empty text."""


class FallbackTTS(tts.TTS):
    """Primary TTS with seamless mid-turn, session-sticky, and quota-cooldown fallback."""

    def __init__(
        self,
        primary: tts.TTS,
        fallback: tts.TTS,
        *,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        cooldowns: CooldownLedger | None = None,
        cooldown_key: str | None = None,
    ) -> None:
        if primary.num_channels != fallback.num_channels:
            raise ValueError("primary and fallback TTS must have the same number of channels")
        _install_plugin_log_redaction()
        self._primary = primary
        self._fallback = fallback
        self._cooldown_s = max(0.0, float(cooldown_s))
        self._cooldowns = cooldowns if cooldowns is not None else _COOLDOWNS
        self._cooldown_key = cooldown_key or describe_tts(primary)
        self._started_on_fallback = self._cooldowns.is_cooling_down(self._cooldown_key)
        self._using_fallback = self._started_on_fallback
        self._failovers = 0
        self._served_counts: dict[str, int] = {}

        active = self._fallback if self._using_fallback else self._primary
        sample_rate = max(primary.sample_rate, fallback.sample_rate)
        super().__init__(
            capabilities=tts.TTSCapabilities(
                streaming=primary.capabilities.streaming or fallback.capabilities.streaming,
                # Keep primary's word-level caption sync while primary is active;
                # LiveKit 1.8.10's _aligned_transcript_or_text degrades cleanly
                # to spoken text on the failover turn, and _trip_fallback refreshes
                # this flag so subsequent turns skip waiting on an empty aligned stream.
                aligned_transcript=active.capabilities.aligned_transcript,
            ),
            sample_rate=sample_rate,
            num_channels=primary.num_channels,
        )

    @property
    def active_engine(self) -> tts.TTS:
        """The engine currently serving this session (used by fillers and logs)."""
        return self._fallback if self._using_fallback else self._primary

    @property
    def provider(self) -> str:
        return self.active_engine.provider

    @property
    def model(self) -> str:
        return self.active_engine.model

    @property
    def using_fallback(self) -> bool:
        return self._using_fallback

    def route(self) -> str:
        p = describe_tts(self._primary)
        f = describe_tts(self._fallback)
        if self._started_on_fallback:
            return f"{f} (primary {p} cooling down)"
        return f"{p} (fallback {f})"

    def _note_served(self, engine: tts.TTS) -> None:
        label = engine.provider
        self._served_counts[label] = self._served_counts.get(label, 0) + 1

    def _trip_fallback(self, error: BaseException, *, mid_audio: bool = False) -> None:
        was_fallback = self._using_fallback
        self._using_fallback = True
        self._capabilities = tts.TTSCapabilities(
            streaming=self._fallback.capabilities.streaming,
            aligned_transcript=self._fallback.capabilities.aligned_transcript,
        )
        self._failovers += 1
        quota = is_quota_or_auth_error(error)
        applied_cooldown = self._cooldown_s if quota else 0.0
        if quota and applied_cooldown > 0.0:
            self._cooldowns.trip(self._cooldown_key, applied_cooldown)
        details = {
            "from": describe_tts(self._primary),
            "to": describe_tts(self._fallback),
            "quota": quota,
            "cooldown_s": round(applied_cooldown, 1),
            "mid_audio": mid_audio,
            **_error_summary(error),
        }
        if not was_fallback:
            log.warning(
                "TTS failover %s -> %s (%s, quota=%s, cooldown=%.0fs)",
                details["from"],
                details["to"],
                details["error_type"],
                quota,
                applied_cooldown,
            )
        record_active("tts_failover", details)

    def stats_for_analytics(self) -> dict[str, Any]:
        """Privacy-safe per-session TTS failover summary (counts & provider names only)."""
        return {
            "tts_fallback_armed": True,
            "tts_started_on_fallback": self._started_on_fallback,
            "tts_failovers": self._failovers,
            "tts_served_by": dict(sorted(self._served_counts.items())),
        }

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        return _FallbackChunkedStream(tts=self, input_text=text, conn_options=conn_options)

    def stream(
        self, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.SynthesizeStream:
        return _FallbackSynthesizeStream(tts=self, conn_options=conn_options)

    async def aclose(self) -> None:
        for engine in (self._primary, self._fallback):
            try:
                await engine.aclose()
            except Exception:  # noqa: BLE001 - best-effort teardown
                log.debug("closing TTS engine failed", exc_info=True)


def _resample_if_needed(
    frame: rtc.AudioFrame, target_sr: int, resampler: rtc.AudioResampler | None
) -> tuple[bytes, rtc.AudioResampler | None]:
    if frame.sample_rate == target_sr:
        return bytes(frame.data), resampler
    if resampler is None:
        resampler = rtc.AudioResampler(
            input_rate=frame.sample_rate,
            output_rate=target_sr,
            num_channels=frame.num_channels,
        )
    out = bytearray()
    for resampled in resampler.push(frame):
        out.extend(resampled.data)
    return bytes(out), resampler


def _inner_conn_options(conn_options: APIConnectOptions) -> APIConnectOptions:
    """Single retry owner: inner child streams never retry or emit SDK retry logs.

    The outer ``FallbackTTS`` stream owns the retry budget (``conn_options.max_retry``)
    so retries do not multiply and raw child error bodies never reach LiveKit's
    retry warning logger.
    """
    return APIConnectOptions(
        max_retry=0,
        retry_interval=conn_options.retry_interval,
        timeout=conn_options.timeout,
    )


class _FallbackChunkedStream(tts.ChunkedStream):
    def __init__(
        self, *, tts: FallbackTTS, input_text: str, conn_options: APIConnectOptions
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._ftts = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        request_id = utils.shortuuid()
        initialized = False
        emitted_audio = False
        inner_opts = _inner_conn_options(self._conn_options)

        def ensure_initialized() -> None:
            nonlocal initialized
            if not initialized:
                output_emitter.initialize(
                    request_id=request_id,
                    sample_rate=self._ftts.sample_rate,
                    num_channels=self._ftts.num_channels,
                    mime_type="audio/pcm",
                )
                initialized = True

        if not self._input_text.strip():
            ensure_initialized()
            output_emitter.flush()
            return

        raw_errors: list[BaseException] = []

        async def run_engine(engine: tts.TTS) -> None:
            nonlocal emitted_audio
            raw_errors.clear()
            resampler: rtc.AudioResampler | None = None
            pending_words: list[Any] = []
            stream = engine.synthesize(self._input_text, conn_options=inner_opts)
            if isinstance(stream, _ChunkedStreamFromStream):
                # Streaming-only adapters (like DialogueTTS) implement synthesize()
                # via a nested engine.stream(). Drive engine.stream() directly so
                # _wrap_child_run sanitizes the actual inner stream before its
                # _attempt_span or 499 handler runs.
                await stream.aclose()
                child_stream = engine.stream(conn_options=inner_opts)
                _wrap_child_run(child_stream, engine.provider, raw_errors)
                child_stream.push_text(self._input_text)
                child_stream.end_input()
                stream_iter: Any = child_stream
            else:
                _wrap_child_run(stream, engine.provider, raw_errors)
                stream_iter = stream
            try:
                async for ev in stream_iter:
                    frame = ev.frame
                    if not frame or not frame.data:
                        continue
                    words = frame.userdata.get(USERDATA_TIMED_TRANSCRIPT) if frame.userdata else None
                    if words:
                        pending_words.extend(words)
                    pcm, resampler = _resample_if_needed(frame, self._ftts.sample_rate, resampler)
                    if pcm:
                        ensure_initialized()
                        output_emitter.push(pcm)
                        emitted_audio = True
                        if pending_words:
                            output_emitter.push_timed_transcript(pending_words)
                            pending_words.clear()
                if resampler is not None:
                    for flushed in resampler.flush():
                        if flushed.data:
                            ensure_initialized()
                            output_emitter.push(bytes(flushed.data))
                            emitted_audio = True
                    if emitted_audio and pending_words:
                        output_emitter.push_timed_transcript(pending_words)
                        pending_words.clear()
            finally:
                await stream_iter.aclose()
            if raw_errors:
                raise _sanitize_error(
                    raw_errors[-1], engine.provider, force_non_retryable=emitted_audio
                ) from None
            if not emitted_audio:
                raise _EmptyAudioError()

        if self._ftts.using_fallback:
            try:
                await run_engine(self._ftts._fallback)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                raw = raw_errors[-1] if raw_errors else err
                raise _sanitize_error(
                    raw, self._ftts._fallback.provider, force_non_retryable=emitted_audio
                ) from None
            self._ftts._note_served(self._ftts._fallback)
            if initialized:
                output_emitter.flush()
            return

        try:
            await run_engine(self._ftts._primary)
            self._ftts._note_served(self._ftts._primary)
            if initialized:
                output_emitter.flush()
            return
        except asyncio.CancelledError:
            raise
        except Exception as err:
            raw = raw_errors[-1] if raw_errors else err
            self._ftts._trip_fallback(raw, mid_audio=emitted_audio)
            if emitted_audio:
                raise _sanitize_error(
                    raw, self._ftts._primary.provider, force_non_retryable=True
                ) from None
            try:
                await run_engine(self._ftts._fallback)
            except asyncio.CancelledError:
                raise
            except Exception as fb_err:
                fb_raw = raw_errors[-1] if raw_errors else fb_err
                raise _sanitize_error(
                    fb_raw, self._ftts._fallback.provider, force_non_retryable=emitted_audio
                ) from None
            self._ftts._note_served(self._ftts._fallback)
            if initialized:
                output_emitter.flush()


class _FallbackSynthesizeStream(tts.SynthesizeStream):
    """Stream text to primary; if primary fails before emitting PCM, replay the
    buffered text into fallback seamlessly and stay on fallback for the session.

    Contract: matches LiveKit 1.8.10's single-segment ``SynthesizeStream``
    lifecycle (one segment per stream instance, matching ``Agent.default.tts_node``;
    text pushed after a second non-empty ``flush()`` is dropped by the base class).
    """

    def __init__(self, *, tts: FallbackTTS, conn_options: APIConnectOptions) -> None:
        super().__init__(tts=tts, conn_options=conn_options)
        self._ftts = tts

    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        request_id = utils.shortuuid()
        initialized = False
        emitted_audio = False
        inner_opts = _inner_conn_options(self._conn_options)

        def ensure_initialized() -> None:
            nonlocal initialized
            if not initialized:
                output_emitter.initialize(
                    request_id=request_id,
                    sample_rate=self._ftts.sample_rate,
                    num_channels=self._ftts.num_channels,
                    stream=True,
                    mime_type="audio/pcm",
                )
                output_emitter.start_segment(segment_id=request_id)
                initialized = True

        # Buffer every incoming text chunk/flush so a pre-audio primary failure
        # can replay the exact utterance into the fallback stream without loss.
        history: list[str | object] = []
        has_text = False
        input_done = False
        input_changed = asyncio.Event()

        async def collect_input() -> None:
            nonlocal has_text, input_done
            try:
                async for item in self._input_ch:
                    history.append(item)
                    if not isinstance(item, self._FlushSentinel) and str(item).strip():
                        has_text = True
                    input_changed.set()
            finally:
                input_done = True
                input_changed.set()

        collector = asyncio.create_task(collect_input(), name="tts-fallback-input")

        raw_errors: list[BaseException] = []

        async def run_engine(engine: tts.TTS) -> None:
            nonlocal emitted_audio
            raw_errors.clear()
            resampler: rtc.AudioResampler | None = None
            pending_words: list[Any] = []
            first_sent_at = 0.0
            child_started_at = 0.0
            child = engine.stream(conn_options=inner_opts)
            _wrap_child_run(child, engine.provider, raw_errors)
            orig_mark_started = getattr(child, "_mark_started", None)
            if callable(orig_mark_started):
                def _capture_mark_started() -> None:
                    nonlocal child_started_at
                    orig_mark_started()
                    if child_started_at == 0.0:
                        raw = getattr(child, "_started_time", 0.0)
                        child_started_at = float(raw) if isinstance(raw, (int, float)) and raw > 0.0 else time.perf_counter()

                child._mark_started = _capture_mark_started  # type: ignore[method-assign]

            async def feed_child() -> None:
                nonlocal first_sent_at
                idx = 0
                try:
                    while True:
                        while idx < len(history):
                            item = history[idx]
                            idx += 1
                            if isinstance(item, self._FlushSentinel):
                                child.flush()
                            else:
                                text = str(item)
                                if first_sent_at == 0.0 and text.strip():
                                    first_sent_at = time.perf_counter()
                                child.push_text(text)
                        if input_done:
                            child.end_input()
                            return
                        input_changed.clear()
                        # Re-check after clear to avoid a missed wakeup.
                        if idx < len(history) or input_done:
                            continue
                        await input_changed.wait()
                except asyncio.CancelledError:
                    raise

            def sync_started_time() -> None:
                # Preserve the child provider's exact synthesis-start timestamp
                # so outer TTSMetrics reports accurate TTFB and time-to-first-sentence.
                if child_started_at > 0.0:
                    self._started_time = child_started_at
                    return
                child_started = getattr(child, "_started_time", 0.0)
                if isinstance(child_started, (int, float)) and child_started > 0.0:
                    self._started_time = float(child_started)
                elif self._started_time == 0.0:
                    self._started_time = first_sent_at or time.perf_counter()

            feeder = asyncio.create_task(feed_child(), name="tts-fallback-feed")
            try:
                async for ev in child:
                    frame = ev.frame
                    if not frame or not frame.data:
                        continue
                    words = frame.userdata.get(USERDATA_TIMED_TRANSCRIPT) if frame.userdata else None
                    if words:
                        pending_words.extend(words)
                    pcm, resampler = _resample_if_needed(frame, self._ftts.sample_rate, resampler)
                    if pcm:
                        if not emitted_audio:
                            sync_started_time()
                        ensure_initialized()
                        output_emitter.push(pcm)
                        emitted_audio = True
                        if pending_words:
                            output_emitter.push_timed_transcript(pending_words)
                            pending_words.clear()
                if resampler is not None:
                    for flushed in resampler.flush():
                        if flushed.data:
                            if not emitted_audio:
                                sync_started_time()
                            ensure_initialized()
                            output_emitter.push(bytes(flushed.data))
                            emitted_audio = True
                    if emitted_audio and pending_words:
                        output_emitter.push_timed_transcript(pending_words)
                        pending_words.clear()
            finally:
                await utils.aio.gracefully_cancel(feeder)
                await child.aclose()
            if raw_errors:
                raise _sanitize_error(
                    raw_errors[-1], engine.provider, force_non_retryable=emitted_audio
                ) from None
            if not emitted_audio:
                raise _EmptyAudioError()

        try:
            # Wait until either speakable text arrives or the stream closes empty.
            while not has_text and not input_done:
                input_changed.clear()
                if has_text or input_done:
                    break
                await input_changed.wait()

            if not has_text:
                # Empty/whitespace-only stream: start and close the emitter cleanly
                # without touching a provider or triggering AudioEmitter errors.
                ensure_initialized()
                return

            if self._ftts.using_fallback:
                try:
                    await run_engine(self._ftts._fallback)
                except asyncio.CancelledError:
                    raise
                except Exception as err:
                    raw = raw_errors[-1] if raw_errors else err
                    raise _sanitize_error(
                        raw, self._ftts._fallback.provider, force_non_retryable=emitted_audio
                    ) from None
                self._ftts._note_served(self._ftts._fallback)
                return

            try:
                await run_engine(self._ftts._primary)
                self._ftts._note_served(self._ftts._primary)
                return
            except asyncio.CancelledError:
                raise
            except Exception as err:
                raw = raw_errors[-1] if raw_errors else err
                self._ftts._trip_fallback(raw, mid_audio=emitted_audio)
                if emitted_audio:
                    # Audio already reached the child's speakers: do NOT replay on
                    # fallback, and signal partial failure (non-retryable) so LiveKit
                    # marks the reply interrupted instead of complete.
                    raise _sanitize_error(
                        raw, self._ftts._primary.provider, force_non_retryable=True
                    ) from None
                try:
                    await run_engine(self._ftts._fallback)
                except asyncio.CancelledError:
                    raise
                except Exception as fb_err:
                    fb_raw = raw_errors[-1] if raw_errors else fb_err
                    raise _sanitize_error(
                        fb_raw, self._ftts._fallback.provider, force_non_retryable=emitted_audio
                    ) from None
                self._ftts._note_served(self._ftts._fallback)
        finally:
            await utils.aio.gracefully_cancel(collector)
            if initialized:
                output_emitter.end_segment()
