"""Bounded backend gateways for the browser-owned Screen track.

Two first-slice endpoints, no lesson persistence:

- ``POST /api/screen/openai/{room}/chat/completions``: OpenAI-compatible
  streaming proxy for the Pi Durable browser Screen. Family-code auth
  (``Authorization: Bearer`` and/or ``x-tutor-code``), same-origin checks,
  country middleware (in ``web.py``), server-side ``OPENCODE_GO_API_KEY``,
  tutor-room validated and forwarded as ``x-opencode-session``. Only
  ``deepseek-v4.1-flash``; 2.5 MB body cap; 40 messages; 120k text chars;
  3 inline data images (~1.2 MB each); ``tools<=8``; ``content:null`` only
  for tool calls/results; token caps clamped to 8192; 30 req/min per IP+room;
  120 s upstream timeout. Streams upstream bytes, ``Cache-Control: no-store``,
  no body persistence or body logging, generic upstream errors. Does not touch
  the new-session-per-hour limiter.

- ``POST /api/screen/research/geography``: first-slice public research
  gateway over Nominatim + Wikimedia Commons, no new paid credentials.
  Returns concise place data plus up to 3 static map image candidates as
  bounded data URLs with ``sourceUrl``/``retrievedAt``/attribution/license.
  HTTPS-only host allowlist, DNS + private/loopback/link-local guards
  including redirects, 10 s external timeouts, small JSON/image caps (~2 MB
  total response), safe content types, rate limits, generic failures.
  No persistence. Deliberately not general web search.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import logging
import re
import secrets
import socket
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode, urljoin, urlparse

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import LLM_ROUTES, USER_AGENT

log = logging.getLogger("open-tutor")

# ---- chat proxy bounds (mirrors experiments/browser-screen/proxy/server.mjs) ----
ALLOWED_CHAT_MODEL = "deepseek-v4.1-flash"
ALLOWED_CHAT_MODELS = {ALLOWED_CHAT_MODEL}
MAX_BODY_BYTES = 2_500_000
MAX_TOKENS = 8192
MAX_MESSAGES = 40
MAX_TEXT_CHARS = 120_000
MAX_IMAGES = 3
MAX_IMAGE_BYTES = 1_200_000
CHAT_RATE_LIMIT = 30  # requests per minute per IP+room
CHAT_WINDOW_S = 60.0
UPSTREAM_TIMEOUT_S = 120

ROOM_RE = re.compile(r"^tutor-[A-Za-z0-9_-]{8,64}$")
GO_DEFAULT_BASE = LLM_ROUTES["go"]["base_url"]

# ---- geography bounds ----
GEO_ALLOWED_HOSTS = frozenset({
    "nominatim.openstreetmap.org",
    "commons.wikimedia.org",
    "upload.wikimedia.org",
    "thumb.wikimedia.org",
})
GEO_TIMEOUT_S = 10.0
GEO_JSON_MAX_BYTES = 256_000
GEO_IMAGE_MAX_BYTES = 500_000
GEO_TOTAL_MAX_BYTES = 2_000_000
GEO_RATE_LIMIT = 30
GEO_WINDOW_S = 60.0
GEO_BODY_MAX_BYTES = 16_384
GEO_QUERY_MIN = 2
GEO_QUERY_MAX = 200
ALLOWED_IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})

_chat_hits: dict[str, list[float]] = {}
_geo_hits: dict[str, list[float]] = {}


def reset_rate_limits() -> None:
    """Clear in-memory rate buckets (tests only; production never calls this)."""
    _chat_hits.clear()
    _geo_hits.clear()


def is_room_valid(room: str) -> bool:
    return bool(ROOM_RE.match(room or ""))


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first[:80]
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client else None
    return (host or "unknown")[:80]


def family_authorized(request: Request, access_code: str) -> bool:
    if not access_code:
        return True
    presented_code = request.headers.get("x-tutor-code", "")
    auth = request.headers.get("authorization", "")
    bearer = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    if presented_code and secrets.compare_digest(presented_code, access_code):
        return True
    if bearer and secrets.compare_digest(bearer, access_code):
        return True
    return False


def same_origin_ok(request: Request, allowed_origins: set[str]) -> bool:
    origin = request.headers.get("origin", "")
    referer = request.headers.get("referer", "")
    host_header = (request.headers.get("host", "") or "").split(",")[0].strip().lower()
    candidates = [value for value in (origin, referer) if value]
    if not candidates:
        return True  # non-browser client (no Origin), same as the proof proxy
    for value in candidates:
        try:
            netloc = urlparse(value).netloc.lower()
        except Exception:
            continue
        if netloc and netloc == host_header:
            return True
    if allowed_origins:
        for value in candidates:
            try:
                origin_only = f"{urlparse(value).scheme}://{urlparse(value).netloc}".lower()
            except Exception:
                continue
            if origin_only in allowed_origins:
                return True
    return False


def _approx_image_bytes(data_url: str) -> int:
    comma = data_url.find(",")
    b64 = data_url[comma + 1:] if comma >= 0 else data_url
    return (len(b64) * 3) // 4


def clamp_token_caps(body: dict[str, Any]) -> bool:
    """Clamp max_tokens/max_completion_tokens down to MAX_TOKENS. Returns True if clamped."""
    clamped = False
    for field in ("max_tokens", "max_completion_tokens"):
        value = body.get(field)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value > MAX_TOKENS:
            body[field] = MAX_TOKENS
            clamped = True
    return clamped


def validate_chat_body(body: Any) -> str | None:
    if not isinstance(body, dict):
        return "body must be a JSON object"
    if body.get("model") not in ALLOWED_CHAT_MODELS:
        return f"model not allowed: {body.get('model')!s}"[:120]
    for field in ("max_tokens", "max_completion_tokens"):
        if field in body and body[field] is not None:
            value = body[field]
            if isinstance(value, bool) or not isinstance(value, int) or not (1 <= value <= MAX_TOKENS):
                return f"{field} out of bounds (1..{MAX_TOKENS})"
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages or len(messages) > MAX_MESSAGES:
        return f"messages must be a non-empty array of at most {MAX_MESSAGES}"
    text_chars = 0
    images = 0
    for message in messages:
        if not isinstance(message, dict):
            return "message must be an object"
        content = message.get("content")
        if isinstance(content, str):
            text_chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    return "content part must be an object"
                ptype = part.get("type")
                if ptype == "text":
                    text_chars += len(str(part.get("text") or ""))
                elif ptype == "image_url":
                    images += 1
                    url = (part.get("image_url") or {}).get("url") if isinstance(part.get("image_url"), dict) else None
                    if not isinstance(url, str) or not url.startswith("data:image/"):
                        return "only inline data: images are allowed"
                    if _approx_image_bytes(url) > MAX_IMAGE_BYTES:
                        return "image too large"
                else:
                    return f"content part type not allowed: {ptype!s}"[:120]
        elif content is None:
            if not message.get("tool_calls") and not message.get("tool_call_id"):
                return "message content must be a string or array"
        else:
            return "message content must be a string or array"
        if text_chars > MAX_TEXT_CHARS:
            return "text payload too large"
        if images > MAX_IMAGES:
            return "too many images"
    tools = body.get("tools")
    if tools is not None and (not isinstance(tools, list) or len(tools) > 8):
        return "at most 8 tools per request"
    return None


def _rate_limited(bucket: dict[str, list[float]], key: str, limit: int,
                  window: float, now: float | None = None) -> bool:
    moment = time.monotonic() if now is None else now
    hits = [t for t in bucket.get(key, []) if moment - t < window]
    if len(hits) >= limit:
        bucket[key] = hits
        return True
    hits.append(moment)
    bucket[key] = hits
    return False


# ---- SSRF guards ----
def _resolve_host(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ValueError(f"dns failed for {host}") from error
    if not infos:
        raise ValueError(f"dns failed for {host}")
    for _family, _socktype, _proto, _canon, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as error:
            raise ValueError("bad resolved address") from error
        if (not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            raise ValueError(f"blocked address for {host}")


def ensure_safe_geo_url(url_str: str) -> str:
    try:
        parsed = urlparse(url_str)
    except Exception as error:
        raise ValueError("bad URL") from error
    if parsed.scheme != "https":
        raise ValueError("https only")
    host = (parsed.hostname or "").lower()
    if host not in GEO_ALLOWED_HOSTS:
        raise ValueError("host not allowed")
    if parsed.username or parsed.password:
        raise ValueError("userinfo not allowed")
    if parsed.port not in (None, 443):
        raise ValueError("port not allowed")
    _resolve_host(host)
    return url_str


def _strip_html(value: Any, limit: int = 300) -> str:
    text = str(value or "")
    text = re.sub(r"<[^>]+>", "", text).strip()
    return text[:limit]


def _nominatim_url(query: str) -> str:
    params = urlencode({"format": "jsonv2", "q": query, "limit": "1", "addressdetails": "1"})
    return f"https://nominatim.openstreetmap.org/search?{params}"


def _commons_url(query: str) -> str:
    params = urlencode({
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",
        "gsrlimit": "10",
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "iiextmetadatafilter": "Artist|LicenseShortName",
        # Wikimedia's thumbnail service may round larger requests up to a
        # multi-megabyte bucket. 320 keeps the static research artifact small
        # enough for the bounded gateway; generated SVG remains available for
        # diagrams that need larger scalable output.
        "iiurlwidth": "320",
    })
    return f"https://commons.wikimedia.org/w/api.php?{params}"


async def _fetch_json(url: str, *, max_bytes: int = GEO_JSON_MAX_BYTES) -> Any:
    current = ensure_safe_geo_url(url)
    timeout = aiohttp.ClientTimeout(total=GEO_TIMEOUT_S)
    for _ in range(4):
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                current,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                allow_redirects=False,
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location", "")
                    if not location:
                        raise RuntimeError("bad redirect")
                    current = ensure_safe_geo_url(urljoin(current, location))
                    continue
                if resp.status != 200:
                    raise RuntimeError(f"geo upstream {resp.status}")
                content_type = resp.headers.get("Content-Type", "")
                if "json" not in content_type.lower():
                    raise RuntimeError("unexpected content type")
                length = resp.headers.get("Content-Length")
                if length is not None:
                    try:
                        if int(length) > max_bytes:
                            raise RuntimeError("response too large")
                    except ValueError:
                        pass
                data = bytearray()
                async for chunk in resp.content.iter_chunked(16384):
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise RuntimeError("response too large")
                try:
                    return json.loads(bytes(data).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise RuntimeError("bad json") from error
    raise RuntimeError("too many redirects")


async def _fetch_image_bytes(url: str) -> tuple[bytes, str]:
    current = ensure_safe_geo_url(url)
    timeout = aiohttp.ClientTimeout(total=GEO_TIMEOUT_S)
    for _ in range(4):
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                current,
                headers={"User-Agent": USER_AGENT, "Accept": "image/png,image/jpeg,image/webp"},
                allow_redirects=False,
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location", "")
                    if not location:
                        raise RuntimeError("bad redirect")
                    current = ensure_safe_geo_url(urljoin(current, location))
                    continue
                if resp.status != 200:
                    raise RuntimeError(f"image upstream {resp.status}")
                mime = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if mime not in ALLOWED_IMAGE_MIMES:
                    raise RuntimeError("unsafe image type")
                length = resp.headers.get("Content-Length")
                if length is not None:
                    try:
                        if int(length) > GEO_IMAGE_MAX_BYTES:
                            raise RuntimeError("image too large")
                    except ValueError:
                        pass
                data = bytearray()
                async for chunk in resp.content.iter_chunked(16384):
                    data.extend(chunk)
                    if len(data) > GEO_IMAGE_MAX_BYTES:
                        raise RuntimeError("image too large")
                if not data:
                    raise RuntimeError("empty image")
                return bytes(data), mime
    raise RuntimeError("too many redirects")


def _shape_place(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        lat = float(item["lat"])
        lon = float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    bbox = None
    raw_bbox = item.get("boundingbox")
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
        try:
            bbox = [float(raw_bbox[0]), float(raw_bbox[1]), float(raw_bbox[2]), float(raw_bbox[3])]
        except (TypeError, ValueError):
            bbox = None
    address = item.get("address")
    clean_address: dict[str, str] = {}
    if isinstance(address, dict):
        for key, value in list(address.items())[:12]:
            if isinstance(key, str) and isinstance(value, (str, int, float)):
                clean_address[key[:40]] = str(value)[:100]
    return {
        "displayName": str(item.get("display_name", ""))[:300],
        "lat": lat,
        "lon": lon,
        "boundingBox": bbox,
        "address": clean_address,
        "category": str(item.get("category", ""))[:40],
        "type": str(item.get("type", ""))[:40],
    }


def _shape_commons_candidates(payload: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    pages: Any = None
    if isinstance(payload, dict):
        query = payload.get("query")
        if isinstance(query, dict):
            pages = query.get("pages")
    if not isinstance(pages, list):
        return candidates
    for page in pages[:10]:
        if not isinstance(page, dict):
            continue
        infos = page.get("imageinfo")
        info = infos[0] if isinstance(infos, list) and infos and isinstance(infos[0], dict) else None
        if not info:
            continue
        mime = str(info.get("mime", "")).split(";")[0].strip().lower()
        if mime not in ALLOWED_IMAGE_MIMES:
            continue
        image_url = info.get("thumburl") or info.get("url")
        if not isinstance(image_url, str) or not image_url.startswith("https://"):
            continue
        title = str(page.get("title", ""))
        if not title.startswith("File:"):
            continue
        source_url = f"https://commons.wikimedia.org/wiki/{quote(title, safe='')}"
        meta = info.get("extmetadata") if isinstance(info.get("extmetadata"), dict) else {}
        artist = meta.get("Artist") if isinstance(meta, dict) else None
        lic = meta.get("LicenseShortName") if isinstance(meta, dict) else None
        attribution = _strip_html((artist or {}).get("value") if isinstance(artist, dict) else artist)
        license_name = _strip_html((lic or {}).get("value") if isinstance(lic, dict) else lic, 120)
        candidates.append({
            "title": title[:200],
            "sourceUrl": source_url[:500],
            "imageUrl": image_url[:2000],
            "mime": mime,
            "attribution": attribution or "",
            "license": license_name or "",
        })
        if len(candidates) >= 10:
            break
    return candidates


async def geography_lookup(query: str) -> dict[str, Any]:
    """Nominatim place + up to 3 Commons map images as bounded data URLs."""
    cleaned = (query or "").strip()
    if not (GEO_QUERY_MIN <= len(cleaned) <= GEO_QUERY_MAX):
        raise ValueError("query out of bounds")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    place: dict[str, Any] | None = None
    try:
        nominatim = await _fetch_json(_nominatim_url(cleaned))
    except Exception as error:
        log.warning("geography nominatim failed: %s", type(error).__name__)
        raise RuntimeError("research unavailable") from error
    if isinstance(nominatim, list) and nominatim and isinstance(nominatim[0], dict):
        place = _shape_place(nominatim[0])

    try:
        commons = await _fetch_json(_commons_url(cleaned))
    except Exception as error:
        log.warning("geography commons failed: %s", type(error).__name__)
        raise RuntimeError("research unavailable") from error
    candidates = _shape_commons_candidates(commons)

    maps: list[dict[str, Any]] = []
    total_json = 0
    for candidate in candidates[:10]:
        if len(maps) >= 3:
            break
        try:
            data, mime = await _fetch_image_bytes(candidate["imageUrl"])
        except Exception as error:
            log.warning("geography image skipped: %s", type(error).__name__)
            continue
        if mime not in ALLOWED_IMAGE_MIMES:
            continue
        retrieved = datetime.now(timezone.utc).isoformat(timespec="seconds")
        data_url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        entry = {
            "dataUrl": data_url,
            "mime": mime,
            "bytes": len(data),
            "sourceUrl": candidate["sourceUrl"],
            "retrievedAt": retrieved,
            "attribution": candidate.get("attribution", "")[:300],
            "license": candidate.get("license", "")[:120],
        }
        tentative = total_json + len(data_url.encode())
        if tentative > GEO_TOTAL_MAX_BYTES:
            continue
        total_json = tentative
        maps.append(entry)

    body = {"query": cleaned, "place": place, "maps": maps, "retrievedAt": now}
    # Final guard: base64 inflates images ~33%; drop trailing maps until the
    # serialised body fits the ~2 MB total budget.
    while maps and len(json.dumps(body, ensure_ascii=False).encode()) > GEO_TOTAL_MAX_BYTES:
        maps.pop()
        body = {"query": cleaned, "place": place, "maps": maps, "retrievedAt": now}
    return body


def upstream_chat_url(env: dict[str, str]) -> str:
    base = (env.get("TUTOR_LLM_BASE_URL") or GO_DEFAULT_BASE).rstrip("/")
    return f"{base}/chat/completions"


def register_screen_routes(app: FastAPI, env: dict[str, str]) -> None:
    access_code = env.get("TUTOR_ACCESS_CODE", "")
    allowed_origins = {part.strip().lower() for part in env.get("TUTOR_SELF_ORIGINS", "").split(",") if part.strip()}

    @app.post("/api/screen/openai/{room}/chat/completions")
    async def screen_chat(room: str, request: Request):
        if not is_room_valid(room):
            return JSONResponse(status_code=400, content={"error": "invalid room"})
        if not family_authorized(request, access_code):
            return JSONResponse(status_code=401, content={"error": "unauthorized"})
        if not same_origin_ok(request, allowed_origins):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        if _rate_limited(_chat_hits, f"{client_ip(request)}\0{room}",
                         CHAT_RATE_LIMIT, CHAT_WINDOW_S):
            return JSONResponse(status_code=429, content={"error": "rate limited, try again shortly"})

        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > MAX_BODY_BYTES:
                    return JSONResponse(status_code=413, content={"error": "payload too large"})
            except ValueError:
                pass
        try:
            raw = await request.body()
        except Exception:
            return JSONResponse(status_code=400, content={"error": "invalid body"})
        if len(raw) > MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content={"error": "payload too large"})
        try:
            body = json.loads(raw.decode("utf-8") if raw else "")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse(status_code=400, content={"error": "invalid JSON"})
        clamped = clamp_token_caps(body) if isinstance(body, dict) else False
        problem = validate_chat_body(body)
        if problem:
            # Shape only; never lesson content.
            try:
                shape = (f"model={body.get('model')} messages={len(body.get('messages', []))} "
                         f"tools={len(body.get('tools', []) or [])} stream={body.get('stream')} "
                         f"max_tokens={body.get('max_tokens', body.get('max_completion_tokens'))}")
            except Exception:
                shape = "unshaped"
            log.warning("screen chat rejected: %s (%s)", problem, shape)
            return JSONResponse(status_code=400, content={"error": problem})
        if clamped:
            log.warning("screen chat clamped output tokens to %d", MAX_TOKENS)

        api_key = env.get("OPENCODE_GO_API_KEY", "")
        if not api_key:
            return JSONResponse(status_code=503, content={"error": "not configured"})

        upstream_url = upstream_chat_url(env)
        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "x-opencode-session": room,
            "User-Agent": USER_AGENT,
        }
        timeout = aiohttp.ClientTimeout(total=UPSTREAM_TIMEOUT_S)
        session = aiohttp.ClientSession(timeout=timeout)
        try:
            try:
                upstream = await session.post(upstream_url, json=body, headers=headers)
            except asyncio.TimeoutError:
                await session.close()
                log.warning("screen chat upstream timeout")
                return JSONResponse(status_code=502, content={"error": "upstream unavailable"})
            except Exception as error:
                await session.close()
                log.warning("screen chat upstream failed: %s", type(error).__name__)
                return JSONResponse(status_code=502, content={"error": "upstream unavailable"})
            if upstream.status < 200 or upstream.status >= 300:
                status = upstream.status
                try:
                    upstream.release()
                except Exception:
                    pass
                await session.close()
                log.warning("screen chat upstream HTTP %d", status)
                return JSONResponse(status_code=502, content={"error": f"upstream error {status}"})
            media_type = upstream.headers.get("Content-Type", "application/json").split(";")[0].strip() or "application/json"

            async def gen():
                try:
                    async for chunk in upstream.content.iter_chunked(8192):
                        if chunk:
                            yield chunk
                finally:
                    try:
                        upstream.release()
                    except Exception:
                        pass
                    await session.close()

            return StreamingResponse(gen(), media_type=media_type,
                                     headers={"Cache-Control": "no-store"})
        except Exception as error:  # pragma: no cover - defensive
            try:
                await session.close()
            except Exception:
                pass
            log.warning("screen chat failed: %s", type(error).__name__)
            return JSONResponse(status_code=502, content={"error": "upstream unavailable"})

    @app.post("/api/screen/research/geography")
    async def screen_geography(request: Request):
        if not family_authorized(request, access_code):
            return JSONResponse(status_code=401, content={"error": "unauthorized"})
        if not same_origin_ok(request, allowed_origins):
            return JSONResponse(status_code=403, content={"error": "forbidden"})
        if _rate_limited(_geo_hits, client_ip(request), GEO_RATE_LIMIT, GEO_WINDOW_S):
            return JSONResponse(status_code=429, content={"error": "rate limited, try again shortly"})
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > GEO_BODY_MAX_BYTES:
                    return JSONResponse(status_code=413, content={"error": "payload too large"})
            except ValueError:
                pass
        try:
            raw = await request.body()
        except Exception:
            return JSONResponse(status_code=400, content={"error": "invalid body"})
        if len(raw) > GEO_BODY_MAX_BYTES:
            return JSONResponse(status_code=413, content={"error": "payload too large"})
        try:
            data = json.loads(raw.decode("utf-8") if raw else "")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JSONResponse(status_code=422, content={"detail": "invalid JSON"})
        query = data.get("query") if isinstance(data, dict) else None
        cleaned = query.strip() if isinstance(query, str) else ""
        if not (GEO_QUERY_MIN <= len(cleaned) <= GEO_QUERY_MAX):
            return JSONResponse(status_code=422, content={"detail": "query must be 2..200 characters"})
        try:
            result = await geography_lookup(cleaned)
        except ValueError:
            return JSONResponse(status_code=422, content={"detail": "query must be 2..200 characters"})
        except Exception as error:
            log.warning("screen geography failed: %s", type(error).__name__)
            return JSONResponse(status_code=502, content={"error": "research unavailable"})
        return JSONResponse(status_code=200, content=result,
                            headers={"Cache-Control": "no-store"})
