"""Find web images through the Parallel Images API (fast mode) for Smart Screen pages.

A page names what it wants (``<ot-image query="Colosseum Rome">``) and this
module answers through ``POST https://api.parallel.ai/v1/images/search`` with
``mode: "fast"``. It returns the same :class:`Candidate` shape as
``commons_images`` so the page pipeline (bounded download, vision review,
credit line) treats both sources alike. The one deliberate difference is the
download: Commons serves from two known hosts, while Parallel returns image
URLs on any public host, so every connection target is resolved and refused
unless all of its addresses are public first -- once per redirect hop.

Per-image records (source, query, latency, verdict) go to ``PageImages.events``;
the module-level cool-down state is exposed through :func:`state` for
meta.json. A request problem never raises past the caller as a page failure:
:class:`ParallelUnavailable` means "do not even try" (no key, or cooling
down) and :class:`ParallelError` means "this attempt failed".

Run the tests with: uv run --project server pytest screen/tests/test_parallel_images.py
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import os
import socket
import time
import urllib.parse

import aiohttp
import httpx

from screen.tools import commons_images as commons

log = logging.getLogger(__name__)

API = "https://api.parallel.ai/v1/images/search"
MAX_RESULTS = 3
MAX_BYTES = 2 * 1024 * 1024
SEARCH_TIMEOUT = 8.0
DOWNLOAD_TIMEOUT = 5.0
MAX_REDIRECTS = 3
USER_AGENT = "open-tutor-smart-screen/1.0 (+https://github.com/johan-acevedo/open-tutor)"
CLIENT_MODEL = "open-tutor-smart-screen"
LOCATION = "se"  # Swedish-first product: geo-target results to Sweden.
COOLDOWN_AUTH_S = 10 * 60  # 401/402/403/429 or a quota/credit body: paying more will not help yet.
COOLDOWN_TRANSIENT_S = 60  # 5xx, timeouts, broken responses: back off briefly.

# Explicitly refused even where ``ipaddress`` might call an address global on
# some Python version: carrier-grade NAT, which includes our own tailnet.
EXTRA_PRIVATE_NETS = (ipaddress.ip_network("100.64.0.0/10"),)


class ParallelUnavailable(Exception):
    """Parallel must not be tried right now: no key, or still cooling down."""


class ParallelError(Exception):
    """This Parallel attempt failed (network, HTTP error, bad payload)."""


# Process-wide cool-down: every session shares one Parallel quota.
_cooldown_until: float = 0.0
_cooldown_reason: str = ""


def state() -> dict[str, object]:
    """Cool-down state for diagnostics (never a key)."""
    now = time.monotonic()
    if now < _cooldown_until:
        return {"available": False, "reason": _cooldown_reason,
                "retry_in_s": round(_cooldown_until - now, 1)}
    return {"available": True, "reason": "", "retry_in_s": 0.0}


def _cool_down(seconds: float, reason: str) -> None:
    global _cooldown_until, _cooldown_reason
    _cooldown_until = max(_cooldown_until, time.monotonic() + seconds)
    _cooldown_reason = reason


def _quota_body(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in ("quota", "credit", "balance", "insufficient", "payment"))


def _classify(status: int, body: str) -> tuple[float, str]:
    """Cool-down length and reason for a failed search response."""
    if status in (401, 403):
        return COOLDOWN_AUTH_S, f"Parallel auth failed (HTTP {status})"
    if status == 402 or (status == 429 and _quota_body(body)) or (400 <= status < 500 and _quota_body(body)):
        return COOLDOWN_AUTH_S, f"Parallel out of credits/quota (HTTP {status})"
    if status == 429:
        return COOLDOWN_AUTH_S, f"Parallel rate-limited (HTTP {status})"
    return COOLDOWN_TRANSIENT_S, f"Parallel error (HTTP {status})"


@contextlib.asynccontextmanager
async def _http(client: httpx.AsyncClient | None):
    """Use the caller's client, or a short-lived one that follows nothing.

    The owned client ignores proxy environment variables: image search and
    download must never be steered through a proxy the deployment did not
    configure explicitly."""
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT, follow_redirects=False,
                                 trust_env=False,
                                 headers={"User-Agent": USER_AGENT}) as own:
        yield own


def _candidate(entry: object) -> commons.Candidate | dict[str, str]:
    if not isinstance(entry, dict):
        return {"title": "", "reason": "Parallel returned a malformed result"}
    title = entry.get("title") if isinstance(entry.get("title"), str) else ""
    image_url = entry.get("image_url") if isinstance(entry.get("image_url"), str) else ""
    source_page_url = entry.get("source_page_url") if isinstance(entry.get("source_page_url"), str) else ""
    if not image_url or not source_page_url:
        return {"title": title or "", "reason": "Parallel result is missing its URLs"}
    if image_url.startswith("http://"):
        # Parallel often returns plain-http file URLs, but the page frame only
        # loads https (CSP ``img-src data: https:``) and we never ship http:
        # offer the same path over TLS and let the download refuse it if the
        # host does not serve valid https.
        image_url = "https://" + image_url[len("http://"):]
    problem = _url_problem(image_url)
    if problem:
        return {"title": title or "", "reason": problem}
    host = (urllib.parse.urlsplit(source_page_url).hostname or "").lower() or "okänd källa"
    return commons.Candidate(
        title=title or host,
        source_url=source_page_url,
        image_url=image_url,
        mime_type="",  # unknown until the bytes are sniffed on download
        credit=f"Källa: {host}",
        source="parallel",
    )


def _result(payload: object) -> commons.SearchResult:
    entries = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ParallelError("Parallel returned no results list")
    result = commons.SearchResult()
    for entry in entries[:MAX_RESULTS]:
        outcome = _candidate(entry)
        if isinstance(outcome, commons.Candidate):
            result.candidates.append(outcome)
        else:
            result.rejected.append(outcome)
    return result


async def search_images(objective: str, queries: list[str], *,
                        client: httpx.AsyncClient | None = None,
                        api_key: str | None = None,
                        max_results: int = MAX_RESULTS) -> commons.SearchResult:
    """Find at most three web images through Parallel fast mode, with credits.

    Raises :class:`ParallelUnavailable` without touching the network when
    there is no key or Parallel is cooling down, and :class:`ParallelError`
    when this attempt fails (starting the matching cool-down).
    """
    key = api_key if api_key is not None else os.environ.get("PARALLEL_API_KEY", "")
    if not key:
        raise ParallelUnavailable("no PARALLEL_API_KEY")
    now = time.monotonic()
    if now < _cooldown_until:
        raise ParallelUnavailable(f"cooling down: {_cooldown_reason}")
    words = [str(query or "").strip()[:200] for query in queries or []]
    words = [word for word in words if word][:3]
    if not words:
        return commons.SearchResult(rejected=[{"title": "", "reason": "empty query"}])
    body = {"objective": str(objective or "")[:5000], "search_queries": words,
            "mode": "fast",
            "advanced_settings": {"max_results": max(1, min(max_results, MAX_RESULTS)),
                                  "location": LOCATION},
            "client_model": CLIENT_MODEL}
    try:
        async with _http(client) as http:
            response = await http.post(API, json=body,
                                       headers={"x-api-key": key, "Content-Type": "application/json"},
                                       timeout=SEARCH_TIMEOUT, follow_redirects=False)
    except httpx.HTTPError as error:
        # Any transport failure (timeouts, resets, proxy errors, broken TLS)
        # cools down briefly: hammering a struggling endpoint helps nothing.
        _cool_down(COOLDOWN_TRANSIENT_S, f"Parallel unreachable ({type(error).__name__})")
        log.warning("parallel image search unreachable: %s", type(error).__name__)
        raise ParallelError(f"Parallel unreachable: {type(error).__name__}") from error
    if response.status_code != 200:
        text = ""
        with contextlib.suppress(Exception):
            text = response.text[:500]
        seconds, reason = _classify(response.status_code, text)
        _cool_down(seconds, reason)
        log.warning("parallel image search %s", reason)
        raise ParallelError(reason)
    try:
        payload = response.json()
    except ValueError:
        _cool_down(COOLDOWN_TRANSIENT_S, "Parallel returned no JSON")
        raise ParallelError("Parallel returned no JSON") from None
    try:
        return _result(payload)
    except ParallelError as error:
        # A 200 OK with a structurally wrong body is a broken endpoint, not
        # an empty result: cool down briefly. A legitimate ``results: []``
        # stays a normal empty result (no cool-down, see ``_result``).
        _cool_down(COOLDOWN_TRANSIENT_S, str(error))
        raise


def reset_cooldown() -> None:
    """Forget any cool-down (tests only)."""
    global _cooldown_until, _cooldown_reason
    _cooldown_until, _cooldown_reason = 0.0, ""


# ---------------------------------------------------------------------------
# SSRF-safe download: any public https host, nothing else.
# ---------------------------------------------------------------------------


def _default_resolve(host: str) -> list[str]:
    """All addresses the system resolves for ``host`` (blocking DNS)."""
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        if address not in addresses:
            addresses.append(address)
    return addresses


async def _resolve(host: str, resolve) -> list[str]:
    if resolve is None:
        return await asyncio.to_thread(_default_resolve, host)
    result = resolve(host)
    if asyncio.isfuture(result) or asyncio.iscoroutine(result):
        result = await result
    return list(result)


def _address_problem(address: str) -> str:
    """Why this IP must never receive our request (empty when it may)."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return f"unparsable IP address {address!r}"
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified or not ip.is_global
            or any(ip in net for net in EXTRA_PRIVATE_NETS)):
        return f"refusing non-public address {address}"
    return ""


async def _validated_addresses(host: str, resolve) -> list[str]:
    """This hop's addresses, validated public before any connection is made.

    One resolution per hop: the returned addresses are exactly the set the
    fetch layer must connect to, so a DNS change after validation cannot
    steer the connection anywhere unvalidated (DNS rebinding)."""
    try:
        addresses = await _resolve(host, resolve)
    except ParallelError:
        raise
    except Exception as error:
        raise ParallelError(f"cannot resolve {host}: {type(error).__name__}") from error
    if not addresses:
        raise ValueError(f"Refusing to download: host {host or 'missing'} resolves to nothing")
    for address in addresses:
        problem = _address_problem(address)
        if problem:
            raise ValueError(f"Refusing to download: {problem}")
    return list(addresses)


def _url_problem(url: str) -> str:
    """Why this URL is not a fetchable image on a public https host (empty if ok)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        return "image URL is not https"
    if parts.username or parts.password:
        return "image URL has credentials"
    try:
        if parts.port not in (None, 443):
            return "image URL has a port"
    except ValueError:
        return "image URL has a bad port"
    if not (parts.hostname or ""):
        return "image URL has no host"
    return ""


def _sniff(data: bytes) -> str:
    """The bitmap type the bytes actually are, or empty for anything else."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


class _PinnedResolver(aiohttp.abc.AbstractResolver):
    """Resolve only from a fixed pin table: no system DNS at fetch time.

    Each redirect hop is resolved and validated up front
    (:func:`_validated_addresses`); the fetch layer then connects only to
    those addresses. The URL hostname is still used for SNI, certificate
    verification and the Host header, so TLS authenticates the name while
    TCP goes to the validated IP. A lookup for any unpinned host raises
    instead of touching system DNS, and proxies stay off
    (``trust_env=False``)."""

    def __init__(self, pins: dict[str, list[str]]):
        self._pins = {str(host).lower(): list(addresses) for host, addresses in pins.items()}

    async def resolve(self, host: str, port: int = 0,
                      family: int = socket.AF_UNSPEC):
        addresses = self._pins.get(str(host).lower())
        if not addresses:
            raise socket.gaierror(f"refusing unpinned host {host!r}")
        resolved = []
        for address in addresses:
            try:
                is_v6 = ipaddress.ip_address(address).version == 6
            except ValueError:
                raise socket.gaierror(f"refusing unpinned address {address!r}") from None
            shown = f"[{address}]" if is_v6 else address
            resolved.append({"hostname": host, "host": shown, "port": port,
                             "family": socket.AF_INET6 if is_v6 else socket.AF_INET,
                             "proto": 0, "flags": socket.AI_NUMERICHOST})
        return resolved

    async def close(self) -> None:
        return None


async def _fetch(url: str, pins: dict[str, list[str]], *, ssl=None):
    """One HTTP hop to a pinned host: no redirects, no proxy, capped body.

    Returns ``(status, headers, body)``. ``pins`` maps the URL hostname to
    its validated addresses; nothing else is ever resolved. Raises
    :class:`ParallelError` on any transport failure."""
    timeout = aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT, sock_connect=min(3.0, DOWNLOAD_TIMEOUT))
    connector = aiohttp.TCPConnector(resolver=_PinnedResolver(pins), use_dns_cache=False,
                                     limit=1, ssl=True if ssl is None else ssl)
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout, trust_env=False,
                                         headers={"User-Agent": USER_AGENT}) as session:
            async with session.get(url, allow_redirects=False) as response:
                body = await response.content.read(MAX_BYTES + 1)
                headers = {key.lower(): value for key, value in response.headers.items()}
                return response.status, headers, body
    except (aiohttp.ClientError, asyncio.TimeoutError) as error:
        raise ParallelError(f"Image download failed: {type(error).__name__}") from error


async def download_image(candidate: commons.Candidate, *, resolve=None, fetch=None) -> tuple[bytes, str]:
    """Fetch the candidate's bitmap: JPEG, PNG or WebP, at most 2 MiB.

    Any public https host is allowed, but the hostname is resolved and every
    address refused unless public -- once for each of at most 3 redirect
    hops, which are followed manually so no hop skips the check. Each hop
    connects only to its validated addresses (pinned: no second DNS lookup
    at connect time), while TLS still verifies the hostname. Returns the
    bytes and the sniffed media type. ``resolve`` is a test seam
    (``host -> [ip, ...]``); ``fetch`` replaces the network hop
    (``(url, pins) -> (status, headers, body)``) for unit tests.
    """
    problem = _url_problem(candidate.image_url)
    if problem:
        raise ValueError(f"Refusing to download: {problem}")
    url = candidate.image_url
    get = fetch if fetch is not None else _fetch
    for _ in range(MAX_REDIRECTS + 1):
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        problem = _url_problem(url)
        if problem:
            raise ValueError(f"Refusing to download: {problem}")
        addresses = await _validated_addresses(host, resolve)
        try:
            status, headers, body = await get(url, {host: addresses})
        except ParallelError:
            raise
        except Exception as error:
            raise ParallelError(f"Image download failed: {type(error).__name__}") from error
        if status in (301, 302, 303, 307, 308):
            target = headers.get("location", "")
            url = urllib.parse.urljoin(url, target)
            if not url or not target:
                raise ValueError("Refusing to download: the redirect has no target")
            continue
        if status != 200:
            raise ValueError(f"Image request failed with HTTP {status}")
        declared = headers.get("content-type", "").split(";")[0].strip().lower()
        if not declared.startswith("image/"):
            raise ValueError(f"Refusing to download: the response is {declared or 'untyped'}, not an image")
        length = headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_BYTES:
            raise ValueError(f"Refusing to download: {length} bytes is over the {MAX_BYTES} byte limit")
        if len(body) > MAX_BYTES:
            raise ValueError(f"Refusing to download: the image grew past {MAX_BYTES} bytes")
        sniffed = _sniff(body)
        if sniffed not in commons.MIME_TYPES:
            raise ValueError(f"Refusing to download: the bytes are {sniffed or 'not a bitmap'}")
        return body, sniffed
    raise ValueError("Refusing to download: too many redirects")
