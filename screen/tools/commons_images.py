"""Search and download one Wikimedia Commons bitmap for a Smart Screen page.

A page names either what it wants (``<ot-image query="Colosseum Rome">``) or a
Commons picture it found itself (``<ot-image src="https://...">``). This module
answers both through the Commons API and keeps the author and licence of
whatever it returns. It fetches nothing but Commons' own image hosts, and the
download is at most 2 MiB of JPEG, PNG or WebP.

    result = await search_images("Colosseum Rome")
    image = await download_image(result.candidates[0])

A candidate that fails a boundary is not fetched: it lands in ``result.rejected``
with a short reason, and the caller decides whether to show a page without it.
A request that fails (offline, HTTP error, redirect) raises, since that is a
server-side failure and not something the model wrote.

Run the tests with: uv run --project server pytest screen/tests/test_commons_images.py
"""

from __future__ import annotations

import contextlib
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser

import httpx

API = "https://commons.wikimedia.org/w/api.php"
FILE_PAGE = "https://commons.wikimedia.org/wiki/"
COMMONS_HOST = "commons.wikimedia.org"
IMAGE_HOSTS = frozenset({"upload.wikimedia.org", "thumb.wikimedia.org"})
MEDIA_PATH = "/wikipedia/commons/"
MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_RESULTS = 3
MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 5.0
USER_AGENT = "open-tutor-screen-images/1.0 (+https://github.com/johan-acevedo/open-tutor)"


@dataclass(frozen=True)
class Candidate:
    """A Commons bitmap the page may show, with the credit line that goes with it."""

    title: str
    source_url: str
    image_url: str
    mime_type: str
    credit: str


@dataclass
class SearchResult:
    """Candidates to show, and the files or links that were refused and why."""

    candidates: list[Candidate] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)


class _PlainText(HTMLParser):
    """Collect the text of an extmetadata value: Artist arrives as an HTML anchor."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain(value: str) -> str:
    """Strip HTML from a metadata value without a regex tag remover."""
    if "<" not in value:
        return " ".join(value.split())
    parser = _PlainText()
    parser.feed(value)
    parser.close()
    return " ".join("".join(parser.parts).split())


def _value(metadata: dict, key: str) -> str:
    entry = metadata.get(key)
    value = entry.get("value") if isinstance(entry, dict) else None
    return value if isinstance(value, str) else ""


def _rejected(title: str, reason: str, source: str = "", licence_url: str = "") -> dict[str, str]:
    entry = {"title": title, "reason": reason}
    if source:
        entry["source"] = source
    if licence_url:
        entry["licence_url"] = licence_url
    return entry


def _decoded_path(url: str) -> str:
    """Percent-decode a path until it stops changing, so traversal cannot hide."""
    path = urllib.parse.urlsplit(url).path
    for _ in range(3):
        decoded = urllib.parse.unquote(path)
        if decoded == path:
            return path
        path = decoded
    return path


def _port_problem(parts: urllib.parse.SplitResult) -> bool:
    """True for a port that is not 443 or not a number at all."""
    try:
        return parts.port not in (None, 443)
    except ValueError:
        return True


def _media_url_problem(url: str) -> str:
    """Why this URL is not a Commons bitmap on Wikimedia's image hosts (empty if it is)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        return "image URL is not https"
    if parts.username or parts.password or _port_problem(parts):
        return "image URL has credentials or a port"
    host = (parts.hostname or "").lower()
    if host not in IMAGE_HOSTS:
        return f"image host {host or 'missing'} is not Wikimedia"
    path = _decoded_path(url)
    if not path.startswith(MEDIA_PATH):
        return "image path is not a Commons file"
    if any(segment in {"", ".", ".."} for segment in path[len(MEDIA_PATH):].split("/")):
        return "image path has a traversal segment"
    return ""


def _source_url(info: dict, title: str) -> str:
    """The Commons file page for this file, from the API or rebuilt from the title."""
    raw = str(info.get("descriptionurl") or "")
    parts = urllib.parse.urlsplit(raw)
    if parts.scheme == "https" and (parts.hostname or "").lower() == COMMONS_HOST and parts.path.startswith("/wiki/File:"):
        return raw
    return FILE_PAGE + urllib.parse.quote(title.replace(" ", "_"), safe=":/")


def _candidate(page: dict) -> Candidate | dict[str, str]:
    """Turn one search or imageinfo page into a candidate, or into a rejection."""
    title = str(page.get("title") or "").strip()
    if page.get("missing") is not None or page.get("invalid") is not None:
        return _rejected(title, "no such Commons file")
    info = next((item for item in page.get("imageinfo") or [] if isinstance(item, dict)), None)
    if not title or info is None:
        return _rejected(title, "no imageinfo")
    metadata = info.get("extmetadata") if isinstance(info.get("extmetadata"), dict) else {}
    licence_url = _value(metadata, "LicenseUrl")
    source_url = _source_url(info, title)
    mime = str(info.get("thumbmime") or info.get("mime") or "").split(";")[0].strip().lower()
    if mime not in MIME_TYPES:
        return _rejected(title, f"unsupported media type {mime or 'unknown'}", source_url, licence_url)
    thumbnail = str(info.get("thumburl") or "")
    image_url = thumbnail or str(info.get("url") or "")
    problem = _media_url_problem(image_url)
    if problem:
        return _rejected(title, problem, source_url, licence_url)
    if not thumbnail:
        # Only the full-size file is left, so its declared size is the download.
        size = info.get("size")
        if not isinstance(size, int) or size <= 0:
            return _rejected(title, "unknown file size", source_url, licence_url)
        if size > MAX_BYTES:
            return _rejected(title, f"{size} bytes is over the {MAX_BYTES} byte limit", source_url, licence_url)
    author = _plain(_value(metadata, "Artist"))
    licence = _plain(_value(metadata, "LicenseShortName"))
    if not author:
        return _rejected(title, "no author", source_url, licence_url)
    if not licence:
        return _rejected(title, "no licence", source_url, licence_url)
    if licence_url and urllib.parse.urlsplit(licence_url).scheme not in {"http", "https"}:
        return _rejected(title, "bad licence URL", source_url, licence_url)
    return Candidate(
        title=title,
        source_url=source_url,
        image_url=image_url,
        mime_type=mime,
        credit=f"Bild: {author}, {licence}, Wikimedia Commons",
    )


def _result(payload: object) -> SearchResult:
    pages = payload.get("query", {}).get("pages") if isinstance(payload, dict) else None
    if not isinstance(pages, dict):
        pages = {}
    ordered = sorted(
        (page for page in pages.values() if isinstance(page, dict)),
        key=lambda page: page.get("index") if isinstance(page.get("index"), int) else 0,
    )
    result = SearchResult()
    for page in ordered:
        outcome = _candidate(page)
        if isinstance(outcome, Candidate):
            result.candidates.append(outcome)
        else:
            result.rejected.append(outcome)
    result.candidates = result.candidates[:MAX_RESULTS]
    return result


@contextlib.asynccontextmanager
async def _http(client: httpx.AsyncClient | None):
    """Use the caller's client, or a short-lived one that follows nothing."""
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as own:
        yield own


async def _query(params: dict[str, str], client: httpx.AsyncClient | None) -> SearchResult:
    async with _http(client) as http:
        response = await http.get(API, params=params, timeout=TIMEOUT, follow_redirects=False)
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError:
        raise ValueError("Commons API returned no JSON") from None
    return _result(payload)


async def search_images(query: str, *, client: httpx.AsyncClient | None = None) -> SearchResult:
    """Find at most three Commons bitmaps for a free-text query, with credits."""
    words = " ".join(str(query or "").split())
    if not words:
        return SearchResult(rejected=[_rejected("", "empty query")])
    return await _query(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": "6",
            "gsrlimit": str(MAX_RESULTS),
            "gsrsearch": f"filetype:bitmap {words}",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
            "iiurlwidth": "800",
        },
        client,
    )


def _commons_title(src: str) -> tuple[str, str]:
    """The Commons file title behind a media URL or File: page link, or a reason.

    The model supplies the link, so only the file name is taken from it and the
    metadata is looked up again: a credit written into the link is never trusted.
    """
    text = str(src or "").strip()
    if not text:
        return "", "empty src"
    parts = urllib.parse.urlsplit(text)
    if parts.scheme != "https" or parts.username or parts.password or _port_problem(parts):
        return "", "not a plain https link"
    host = (parts.hostname or "").lower()
    path = _decoded_path(text)
    if any(segment in {".", ".."} for segment in path.split("/")):
        return "", "link has a traversal segment"
    if host == COMMONS_HOST:
        if not path.startswith("/wiki/File:"):
            return "", "not a Commons file page"
        name = path[len("/wiki/File:"):]
    elif host in IMAGE_HOSTS:
        if not path.startswith(MEDIA_PATH):
            return "", "not a Commons media path"
        segments = path[len(MEDIA_PATH):].split("/")
        name = segments[-2] if segments[0] == "thumb" and len(segments) >= 5 else segments[-1]
        # A thumbnail segment carries its width: 960px-Foo.jpg is the file Foo.jpg.
        width, px, rest = name.partition("px-")
        if px and width.isdigit() and rest:
            name = rest
    else:
        return "", f"host {host or 'missing'} is not Wikimedia"
    name = name.strip()
    if not name or "/" in name or name.startswith("."):
        return "", "bad file name"
    return "File:" + name.replace("_", " "), ""


async def lookup_image(src: str, *, client: httpx.AsyncClient | None = None) -> SearchResult:
    """Resolve a Commons media URL or File: link the model named into a credited candidate."""
    text = str(src or "").strip()
    title, problem = _commons_title(text)
    if problem:
        return SearchResult(rejected=[_rejected(text, problem, text)])
    result = await _query(
        {
            "action": "query",
            "format": "json",
            "titles": title,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime",
            "iiurlwidth": "800",
        },
        client,
    )
    if not result.candidates and not result.rejected:
        result.rejected.append(_rejected(title, "no such Commons file", text))
    return result


def _sniff(data: bytes) -> str:
    """The bitmap type the bytes actually are, or empty for anything else."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


async def download_image(candidate: Candidate, *, client: httpx.AsyncClient | None = None) -> bytes:
    """Fetch the candidate's bitmap: JPEG, PNG or WebP, at most 2 MiB, no redirects."""
    problem = _media_url_problem(candidate.image_url)
    if problem:
        raise ValueError(f"Refusing to download: {problem}")
    if candidate.mime_type.lower() not in MIME_TYPES:
        raise ValueError(f"Refusing to download: unsupported media type {candidate.mime_type}")
    chunks: list[bytes] = []
    total = 0
    async with _http(client) as http:
        async with http.stream("GET", candidate.image_url, timeout=TIMEOUT, follow_redirects=False) as response:
            if response.is_redirect:
                raise ValueError("Refusing to download: the image URL redirects")
            if response.status_code != 200:
                raise ValueError(f"Image request failed with HTTP {response.status_code}")
            declared = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if declared not in MIME_TYPES:
                raise ValueError(f"Refusing to download: the response is {declared or 'untyped'}, not a bitmap")
            length = response.headers.get("content-length", "")
            if length.isdigit() and int(length) > MAX_BYTES:
                raise ValueError(f"Refusing to download: {length} bytes is over the {MAX_BYTES} byte limit")
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError(f"Refusing to download: the image grew past {MAX_BYTES} bytes")
                chunks.append(chunk)
    data = b"".join(chunks)
    sniffed = _sniff(data)
    if sniffed not in MIME_TYPES:
        raise ValueError(f"Refusing to download: the bytes are {sniffed or 'not a bitmap'}")
    return data
