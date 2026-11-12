"""Authoritative runtime metadata for the hamburger-menu Sessionsinfo.

The agent worker publishes this once per session as the ``tutor.runtime``
participant attribute (JSON, see ``RUNTIME_ATTR``). The browser parses it
strictly and shows it under Sessionsinfo; nothing here is ever a secret.

Rules, enforced by tests:
- Only descriptive values: route names, model ids, hosts, reasoning levels,
  on/off flags. Never credentials, API keys, tokens, signed URLs, the whole
  environment, or endpoint URLs with userinfo/query/fragment.
- Every provider-specific value is read off the actual built engine objects
  (``.provider`` / ``.model`` / ``.sample_rate`` / ``.capabilities`` and the
  options they were built with). Routes we do not recognise report
  ``"okänd"`` instead of a guessed vendor default.
"""

from __future__ import annotations

import os
import socket
from importlib import metadata as importlib_metadata
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .config import AGENT_NAME, llm_route
from .debug_log import record_active

RUNTIME_ATTR = "tutor.runtime"
RUNTIME_VERSION = 1

MAX_TEXT = 200

# Human route names for the configured TUTOR_LLM routes (see config.LLM_ROUTES).
ROUTE_DISPLAY = {
    "go": "OpenCode Go",
    "gemini-dev": "Google (endast utveckling)",
}

# TTS engine provider -> SDK distribution that serves it. DialogueTTS and
# ZonosTTS are our own adapters on top of livekit-agents primitives.
TTS_SDK = {
    "Deepgram": "livekit-plugins-deepgram",
    "ElevenLabs": "livekit-plugins-elevenlabs",
    "Cartesia": "livekit-plugins-cartesia",
    "ZONOS3": "livekit-agents",
    "Soniox": "livekit-plugins-soniox",
}


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    text = value if isinstance(value, str) else str(value)
    return text[:limit]


def redact_url(value: Any) -> str:
    """Keep scheme://host[:port][/path]; drop userinfo, query and fragment.

    Returns "" when the value is not a usable http/https/ws/wss URL, so
    callers never publish a token, a signed URL, or garbage.
    """
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https", "ws", "wss") or not parts.hostname:
        return ""
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port:
        host = f"{host}:{port}"
    netloc = host
    path = parts.path or ""
    return _text(urlunsplit((parts.scheme, netloc, path, "", "")))


def _sdk_version(distribution: str) -> str:
    try:
        return _text(importlib_metadata.version(distribution))
    except importlib_metadata.PackageNotFoundError:
        return "okänd"
    except Exception:
        return "okänd"


def _field(label: str, value: Any) -> dict[str, str]:
    return {"label": label, "value": _text(value) if str(value).strip() else "okänd"}


def _describe_llm(llm: Any, environ: Any) -> list[dict[str, str]]:
    try:
        route = llm_route(environ)
    except ValueError:
        route = None
    actual_model = getattr(llm, "model", None) or getattr(route, "model", None)
    fields = [
        _field("Tjänst", ROUTE_DISPLAY.get(getattr(route, "name", ""), "okänd")),
        _field("Modell", actual_model or "okänd"),
        _field(
            "Gränssnitt",
            {"responses": "Responses-API (strömmande)", "chat": "Chat Completions"}.get(
                getattr(route, "api", ""), "okänd"
            ),
        ),
        _field("Värd", redact_url(getattr(route, "base_url", "") or "")),
        _field(
            "Resonemang",
            getattr(route, "reasoning_effort", None) or "standard (inget explicit val)",
        ),
        _field("SDK", f"livekit-plugins-openai {_sdk_version('livekit-plugins-openai')}"),
    ]
    return fields


def _describe_stt(stt: Any) -> list[dict[str, str]]:
    params = getattr(stt, "_params", None)
    hints = getattr(params, "language_hints", None) if params is not None else None
    delay = getattr(params, "max_endpoint_delay_ms", None) if params is not None else None
    fields = [
        _field("Leverantör", getattr(stt, "provider", None) or "okänd"),
        _field("Modell", getattr(stt, "model", None) or "okänd"),
        _field("Språk", ", ".join(hints) if hints else "okänd"),
        _field("Tystnadsgräns", f"{delay} ms" if isinstance(delay, int) else "okänd"),
        _field("Värd", redact_url(getattr(stt, "_base_url", "") or "")),
        _field("SDK", f"livekit-plugins-soniox {_sdk_version('livekit-plugins-soniox')}"),
    ]
    return fields


def _tts_endpoint(tts: Any) -> str:
    """The synthesis endpoint from the actual engine options, redacted.

    DialogueTTS speaks the documented single-context text-to-dialogue socket
    (see dialogue_tts.PATH); Deepgram/Zonos/plugin engines carry their base
    URL in their options. Anything else reports unknown — never a guess.
    """
    provider = getattr(tts, "provider", "")
    if provider == "ElevenLabs" and hasattr(tts, "_opts"):
        from .dialogue_tts import PATH as DIALOGUE_PATH

        opts = tts._opts
        if type(tts).__name__ == "DialogueTTS":
            base = redact_url(getattr(opts, "base_url", ""))
            if base:
                return f"{base.rstrip('/')}{DIALOGUE_PATH}"
            return "okänd"
        return redact_url(getattr(opts, "base_url", "") or "")
    opts = getattr(tts, "_opts", None)
    if opts is not None and getattr(opts, "base_url", None):
        return redact_url(opts.base_url)
    base_url = getattr(tts, "base_url", None)
    if isinstance(base_url, str) and base_url:
        return redact_url(base_url)
    return "okänd"


def _describe_tts(tts: Any) -> list[dict[str, str]]:
    capabilities = getattr(tts, "capabilities", None)
    streaming = getattr(capabilities, "streaming", None)
    fields = [
        _field("Leverantör", getattr(tts, "provider", None) or "okänd"),
        _field("Modell", getattr(tts, "model", None) or "okänd"),
        _field(
            "Samplingsfrekvens",
            f"{getattr(tts, 'sample_rate', '')} Hz" if getattr(tts, "sample_rate", None) else "okänd",
        ),
        _field(
            "Strömmande",
            "ja" if streaming is True else ("nej" if streaming is False else "okänd"),
        ),
    ]
    expressivity = getattr(tts, "expressivity", None)
    if isinstance(expressivity, int) and not isinstance(expressivity, bool):
        fields.append(_field("Uttrycksfullhet", str(expressivity)))
    fields.append(_field("Anslutning", _tts_endpoint(tts)))
    provider = getattr(tts, "provider", "")
    if provider in TTS_SDK:
        fields.append(_field("SDK", f"{TTS_SDK[provider]} {_sdk_version(TTS_SDK[provider])}"))
    else:
        fields.append(_field("SDK", f"livekit-agents {_sdk_version('livekit-agents')}"))
    return fields


def _on_off(environ: Any, name: str) -> str:
    get = environ.get if hasattr(environ, "get") else (lambda key, default="": os.environ.get(key, default))
    return "på" if get(name) == "1" else "av"


def build_runtime_info(
    *,
    room: str,
    agent_name: str = AGENT_NAME,
    llm: Any,
    stt: Any,
    tts: Any,
    adaptive: bool | None = None,
    min_endpoint_delay: float | None = None,
    max_endpoint_delay: float | None = None,
    environ: dict[str, str] | Any | None = None,
) -> dict[str, Any]:
    """Assemble the publishable runtime payload. No secrets, ever."""
    env: Any = os.environ if environ is None else environ
    get = env.get if hasattr(env, "get") else (lambda key, default="": os.environ.get(key, default))
    if adaptive is None:
        adaptive = get("TUTOR_ADAPTIVE_INTERRUPTION") == "1"
    if min_endpoint_delay is None:
        try:
            min_endpoint_delay = float(get("TUTOR_MIN_ENDPOINT", "0.6"))
        except (TypeError, ValueError):
            min_endpoint_delay = 0.6
    if max_endpoint_delay is None:
        max_endpoint_delay = 4.0
    try:
        host = socket.gethostname()[:MAX_TEXT] or "okänd"
    except Exception:
        host = "okänd"
    sections = [
        {
            "title": "Samtal",
            "fields": [
                _field("Rum", room or "okänd"),
                _field("Agent", agent_name or "okänd"),
                _field("Värd", host),
                _field("Agent-SDK", f"livekit-agents {_sdk_version('livekit-agents')}"),
            ],
        },
        {"title": "Språkmodell", "fields": _describe_llm(llm, env)},
        {"title": "Lyssning (tal till text)", "fields": _describe_stt(stt)},
        {"title": "Röst (text till tal)", "fields": _describe_tts(tts)},
        {
            "title": "Avbrott och felsökning",
            "fields": [
                _field("Avbrottsläge", "adaptivt" if adaptive else "röststyrt (VAD)"),
                _field("Tyst start", f"{min_endpoint_delay} s"),
                _field("Max väntan", f"{max_endpoint_delay} s"),
                _field("Felsökningslogg", _on_off(env, "TUTOR_DEBUG_LOG")),
                _field("Bildlagring", _on_off(env, "TUTOR_DEBUG_ARTIFACTS")),
                _field("Molninspelning", _on_off(env, "TUTOR_CLOUD_RECORDING")),
            ],
        },
    ]
    return {"version": RUNTIME_VERSION, "sections": sections}


async def publish_runtime_info(
    room: Any,
    *,
    llm: Any,
    stt: Any,
    tts: Any,
    agent_name: str = AGENT_NAME,
    adaptive: bool | None = None,
    min_endpoint_delay: float | None = None,
    max_endpoint_delay: float | None = None,
    environ: dict[str, str] | Any | None = None,
) -> dict[str, Any]:
    """Build the payload and merge it into the worker's participant attributes.

    Merges with the attributes already set (e.g. ``tutor.mode``) so neither
    this publish nor a later mode update can wipe the other.
    """
    import json

    payload = build_runtime_info(
        room=getattr(room, "name", "") or "",
        agent_name=agent_name,
        llm=llm,
        stt=stt,
        tts=tts,
        adaptive=adaptive,
        min_endpoint_delay=min_endpoint_delay,
        max_endpoint_delay=max_endpoint_delay,
        environ=environ,
    )
    current = dict(getattr(room.local_participant, "attributes", None) or {})
    current[RUNTIME_ATTR] = json.dumps(payload, ensure_ascii=False)
    await room.local_participant.set_attributes(current)
    record_active("runtime_info", payload)
    return payload
