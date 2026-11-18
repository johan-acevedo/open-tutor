"""Recorded/fast-mode Parallel responses + scripted vision replies; no live key.

Covers response parsing, the request shape (unknown fields return 422, so the
body carries only documented keys), error and cool-down paths, and the SSRF
boundary: private IPs, redirects onto private IPs, and hop limits. DNS is a
stub; HTTP is a MockTransport. PageImages strategy tests live at the bottom.

Run them with: uv run --project server pytest screen/tests/test_parallel_images.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from screen.tools import parallel_images as parallel
from screen.tools import commons_images as commons
from screen.tools.page_images import PageImages, image_slots

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
HTML = b"<!DOCTYPE html><html><body>Not a picture</body></html>"

SEARCH = {"search_id": "search_abc", "session_id": "session_abc",
          "results": [
              {"title": "Gustav II Adolf portrait", "image_url": "https://example.com/king.jpg",
               "source_page_url": "https://example.com/kings/gustav", "width": 1200, "height": 800},
              {"title": "Colosseum at dusk", "image_url": "https://photos.example.org/colosseum.png",
               "source_page_url": "https://photos.example.org/rome", "width": 1600, "height": 900},
          ],
          "warnings": [], "usage": [{"name": "sku_images", "count": 1}]}
ACCEPT = json.dumps({"accept": True, "reason": "Relevant portrait, nothing hidden."})
REJECT = json.dumps({"accept": False, "reason": "Wrong century."})

PUBLIC = ["93.184.216.34"]
PRIVATE = ["10.1.2.3"]


def search_transport(payload=SEARCH, status=200, body=None):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.host == "api.parallel.ai", request.url.host
        assert request.headers.get("x-api-key") == "test-key"
        if status != 200:
            return httpx.Response(status, text=body or "error")
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handle), requests


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    parallel.reset_cooldown()
    monkeypatch.setenv("PARALLEL_API_KEY", "test-key")
    yield
    parallel.reset_cooldown()


@pytest.mark.asyncio
async def test_parses_fast_results_with_site_credit():
    http, requests = search_transport()
    async with httpx.AsyncClient(transport=http) as client:
        result = await parallel.search_images("Portraits of Gustav II Adolf", ["Gustav II Adolf portrait"],
                                              client=client)
    assert len(result.candidates) == 2
    first, second = result.candidates
    assert first.source == "parallel"
    assert first.source_url == "https://example.com/kings/gustav"
    assert first.credit == "Källa: example.com"
    assert second.credit == "Källa: photos.example.org"
    assert not result.rejected


@pytest.mark.asyncio
async def test_request_body_carries_only_documented_fields():
    http, requests = search_transport(payload={"search_id": "s", "session_id": "s", "results": []})
    async with httpx.AsyncClient(transport=http) as client:
        await parallel.search_images("objective text", ["one", "two"], client=client)
    assert len(requests) == 1
    sent = json.loads(requests[0].content.decode())
    assert sent == {"objective": "objective text", "search_queries": ["one", "two"], "mode": "fast",
                    "advanced_settings": {"max_results": 3, "location": "se"},
                    "client_model": "open-tutor-smart-screen"}


@pytest.mark.asyncio
async def test_empty_queries_make_no_request():
    http, requests = search_transport()
    async with httpx.AsyncClient(transport=http) as client:
        result = await parallel.search_images("objective", [], client=client)
    assert not result.candidates and result.rejected and not requests


@pytest.mark.asyncio
async def test_missing_key_skips_the_network():
    http, requests = search_transport()
    import os
    os.environ.pop("PARALLEL_API_KEY")
    async with httpx.AsyncClient(transport=http) as client:
        with pytest.raises(parallel.ParallelUnavailable, match="no PARALLEL_API_KEY"):
            await parallel.search_images("objective", ["query"], client=client)
    assert not requests


@pytest.mark.parametrize("status,body,wait", [
    (402, "credits exhausted", parallel.COOLDOWN_AUTH_S),
    (429, "quota exceeded for images", parallel.COOLDOWN_AUTH_S),
    (429, "too many requests", parallel.COOLDOWN_AUTH_S),
    (401, "unauthorized", parallel.COOLDOWN_AUTH_S),
    (500, "boom", parallel.COOLDOWN_TRANSIENT_S),
])
@pytest.mark.asyncio
async def test_failures_cool_down_and_skip_the_network(status, body, wait):
    http, requests = search_transport(status=status, body=body)
    async with httpx.AsyncClient(transport=http) as client:
        with pytest.raises(parallel.ParallelError):
            await parallel.search_images("objective", ["query"], client=client)
        state = parallel.state()
        assert state["available"] is False
        assert wait - 5 <= state["retry_in_s"] <= wait
        with pytest.raises(parallel.ParallelUnavailable, match="cooling down"):
            await parallel.search_images("objective", ["query"], client=client)
    assert len(requests) == 1  # the cooled-down call made no request
    parallel.reset_cooldown()
    assert parallel.state()["available"] is True


@pytest.mark.asyncio
async def test_timeout_backs_off_briefly():
    def handle(request):
        raise httpx.ConnectTimeout("slow")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(parallel.ParallelError, match="unreachable"):
            await parallel.search_images("objective", ["query"], client=client)
    state = parallel.state()
    assert state["available"] is False
    assert state["retry_in_s"] <= parallel.COOLDOWN_TRANSIENT_S


@pytest.mark.asyncio
async def test_results_missing_urls_are_rejected_not_shipped():
    payload = {"search_id": "s", "session_id": "s",
               "results": [{"title": "no urls"}]}
    http, _ = search_transport(payload=payload)
    async with httpx.AsyncClient(transport=http) as client:
        result = await parallel.search_images("objective", ["query"], client=client)
    assert not result.candidates and len(result.rejected) == 1


@pytest.mark.asyncio
async def test_plain_http_file_urls_are_offered_over_tls():
    payload = {"search_id": "s", "session_id": "s",
               "results": [{"title": "King", "image_url": "http://plain.example/x.jpg",
                              "source_page_url": "https://plain.example/x"}]}
    http, _ = search_transport(payload=payload)
    async with httpx.AsyncClient(transport=http) as client:
        result = await parallel.search_images("objective", ["query"], client=client)
    assert [c.image_url for c in result.candidates] == ["https://plain.example/x.jpg"]


# ---------------------------------------------------------------------------
# SSRF-safe download.
# ---------------------------------------------------------------------------

def download_transport(routes):
    """routes: host -> list of (status, headers, body) or exception."""
    requests = []

    def handle(request):
        requests.append(request)
        choices = routes.get(request.url.host)
        if choices is None:
            return httpx.Response(404, text="no such host")
        action = choices[min(len(requests) - 1, len(choices) - 1)] if isinstance(choices, list) else choices
        if isinstance(action, Exception):
            raise action
        status, headers, body = action
        return httpx.Response(status, headers=headers, content=body)

    return httpx.MockTransport(handle), requests


def candidate(url="https://example.com/king.jpg"):
    return commons.Candidate(title="King", source_url="https://example.com/kings",
                             image_url=url, mime_type="", credit="Källa: example.com", source="parallel")


@pytest.mark.asyncio
async def test_downloads_from_a_public_host_and_sniffs_the_type():
    http, requests = download_transport({"example.com": (200, {"content-type": "image/jpeg"}, JPEG)})
    async with httpx.AsyncClient(transport=http) as client:
        data, mime = await parallel.download_image(candidate(), client=client,
                                                    resolve=lambda host: PUBLIC)
    assert data == JPEG and mime == "image/jpeg"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_private_loopback_link_local_and_cgnat_addresses_are_refused():
    http, requests = download_transport({})
    async with httpx.AsyncClient(transport=http) as client:
        for address in ("10.1.2.3", "172.16.0.9", "192.168.1.2", "127.0.0.1",
                        "169.254.169.254", "224.0.0.1", "::1", "100.64.0.1", "100.91.148.43"):
            with pytest.raises(ValueError, match="non-public"):
                await parallel.download_image(candidate(), client=client,
                                              resolve=lambda host, ip=address: [ip])
    assert not requests  # refused before any connection


@pytest.mark.asyncio
async def test_a_private_address_hiding_among_public_ones_still_refuses():
    http, requests = download_transport({})
    async with httpx.AsyncClient(transport=http) as client:
        with pytest.raises(ValueError, match="non-public"):
            await parallel.download_image(candidate(), client=client,
                                          resolve=lambda host: PUBLIC + PRIVATE)
    assert not requests


@pytest.mark.asyncio
async def test_redirect_to_a_private_host_is_refused():
    routes = {"example.com": (302, {"location": "http://127.0.0.1:9000/secret"}, b""),
              "127.0.0.1": (200, {"content-type": "image/jpeg"}, JPEG)}
    http, requests = download_transport(routes)
    async with httpx.AsyncClient(transport=http) as client:
        def resolve(host):
            return ["127.0.0.1"] if host == "127.0.0.1" else PUBLIC

        with pytest.raises(ValueError, match="non-public|not https"):
            await parallel.download_image(candidate(), client=client, resolve=resolve)
    assert all("127.0.0.1" not in str(r.url) for r in requests)


@pytest.mark.asyncio
async def test_public_redirect_chain_is_followed_and_rechecked():
    routes = {"example.com": (302, {"location": "https://cdn.example.net/pic.png"}, b""),
              "cdn.example.net": (200, {"content-type": "image/png"}, PNG)}
    http, _ = download_transport(routes)
    async with httpx.AsyncClient(transport=http) as client:
        data, mime = await parallel.download_image(candidate(), client=client,
                                                    resolve=lambda host: PUBLIC)
    assert data == PNG and mime == "image/png"


@pytest.mark.asyncio
async def test_too_many_redirects_are_refused():
    routes = {"example.com": (302, {"location": "https://example.com/loop"}, b"")}
    http, _ = download_transport(routes)
    async with httpx.AsyncClient(transport=http) as client:
        with pytest.raises(ValueError, match="too many redirects"):
            await parallel.download_image(candidate(), client=client, resolve=lambda host: PUBLIC)


@pytest.mark.asyncio
async def test_non_https_credentialed_and_html_targets_are_refused():
    http, requests = download_transport({"example.com": (200, {"content-type": "text/html"}, HTML)})
    async with httpx.AsyncClient(transport=http) as client:
        for url in ("http://example.com/king.jpg", "https://user@example.com/king.jpg",
                    "https://example.com:8443/king.jpg"):
            with pytest.raises(ValueError, match="not https|credentials|port"):
                await parallel.download_image(candidate(url), client=client,
                                              resolve=lambda host: PUBLIC)
        with pytest.raises(ValueError, match="not an image"):
            await parallel.download_image(candidate(), client=client, resolve=lambda host: PUBLIC)
    assert len(requests) == 1  # only the HTML one connected


@pytest.mark.asyncio
async def test_oversize_and_growing_streams_are_cut_off():
    big = (200, {"content-type": "image/jpeg", "content-length": str(3 * 1024 * 1024)}, JPEG)
    http, _ = download_transport({"example.com": big})
    async with httpx.AsyncClient(transport=http) as client:
        with pytest.raises(ValueError, match="over the"):
            await parallel.download_image(candidate(), client=client, resolve=lambda host: PUBLIC)
    def lying(request):
        response = httpx.Response(200, headers={"content-type": "image/jpeg"}, content=JPEG * 40000)
        del response.headers["content-length"]  # the server lies; the stream tells the truth
        return response

    http = httpx.MockTransport(lying)
    async with httpx.AsyncClient(transport=http) as client:
        with pytest.raises(ValueError, match="grew past"):
            await parallel.download_image(candidate(), client=client, resolve=lambda host: PUBLIC)


# ---------------------------------------------------------------------------
# PageImages strategy behind SCREEN_IMAGES.
# ---------------------------------------------------------------------------

COMMONS_SEARCH = {"query": {"pages": {"1": {
    "pageid": 1, "ns": 6, "title": "File:King.jpg", "index": 0,
    "imageinfo": [{"size": 500, "width": 100, "height": 100,
                   "url": "https://upload.wikimedia.org/wikipedia/commons/1/2/King.jpg",
                   "descriptionurl": "https://commons.wikimedia.org/wiki/File:King.jpg",
                   "mime": "image/jpeg",
                   "extmetadata": {"Artist": {"value": "Museum"},
                                   "LicenseShortName": {"value": "CC0"},
                                   "LicenseUrl": {"value": "https://creativecommons.org/publicdomain/zero/1.0/"}}}]}}}}

COLOSSEUM = (Path(__file__).parent / "fixtures" / "commons-images" / "colosseum.jpg").read_bytes()


def combined_transport(*, commons=COMMONS_SEARCH, parallel_payload=SEARCH,
                       parallel_status=200, image_bytes=JPEG):
    requests = []

    def handle(request):
        requests.append(request)
        host = request.url.host
        if host == "commons.wikimedia.org":
            return httpx.Response(200, json=commons)
        if host == "api.parallel.ai":
            if parallel_status != 200:
                return httpx.Response(parallel_status, text="credits exhausted")
            return httpx.Response(200, json=parallel_payload)
        if host in ("upload.wikimedia.org", "thumb.wikimedia.org"):
            return httpx.Response(200, content=COLOSSEUM, headers={"content-type": "image/jpeg"})
        return httpx.Response(200, content=image_bytes, headers={"content-type": "image/jpeg"})

    return httpx.MockTransport(handle), requests


@pytest.mark.asyncio
async def test_combined_searches_both_at_once_and_prefers_commons(monkeypatch):
    monkeypatch.setattr(parallel, "_default_resolve", lambda host: PUBLIC)
    http, requests = combined_transport()
    review = AsyncMock(return_value=ACCEPT)
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Årskurs 4, svenska kungar", review,
                            time.monotonic() + 10, client=client, image_mode="commons+parallel")
        body = await images.prepare('<ot-image query="Gustav II Adolf" alt="Kungen"></ot-image>')
    hosts = {r.url.host for r in requests}
    assert {"commons.wikimedia.org", "api.parallel.ai"} <= hosts  # both searched
    assert "query=" not in body
    attrs = image_slots(body)[0].attrs
    assert attrs["src"].startswith("https://upload.wikimedia.org/")  # Commons wins ties
    assert attrs["credit"] == "Bild: Museum, CC0, Wikimedia Commons"
    accepted = [e for e in images.events if e["decision"] == "accepted"][0]
    assert accepted["image_source"] == "commons" and accepted["query"] == "Gustav II Adolf"
    assert isinstance(accepted["latency_s"], float)


@pytest.mark.asyncio
async def test_combined_falls_back_to_parallel_when_commons_fails(monkeypatch):
    monkeypatch.setattr(parallel, "_default_resolve", lambda host: PUBLIC)
    http, _ = combined_transport(commons={"query": {"pages": {}}})
    review = AsyncMock(return_value=ACCEPT)
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Årskurs 4", review, time.monotonic() + 10,
                            client=client, image_mode="commons+parallel")
        body = await images.prepare('<ot-image query="Gustav II Adolf" alt="Kungen"></ot-image>')
    attrs = image_slots(body)[0].attrs
    assert attrs["src"] == "https://example.com/king.jpg"
    assert attrs["credit"] == "Källa: example.com"
    accepted = [e for e in images.events if e["decision"] == "accepted"][0]
    assert accepted["image_source"] == "parallel"


@pytest.mark.asyncio
async def test_parallel_only_never_touches_commons(monkeypatch):
    monkeypatch.setattr(parallel, "_default_resolve", lambda host: PUBLIC)
    http, requests = combined_transport()
    review = AsyncMock(return_value=ACCEPT)
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Årskurs 4", review, time.monotonic() + 10,
                            client=client, image_mode="parallel")
        body = await images.prepare('<ot-image query="Colosseum" alt="Amfiteatern"></ot-image>')
    assert not any(r.url.host == "commons.wikimedia.org" for r in requests)
    assert image_slots(body)[0].attrs["src"] == "https://example.com/king.jpg"


@pytest.mark.asyncio
async def test_parallel_cooldown_falls_back_to_commons_silently(monkeypatch):
    monkeypatch.setattr(parallel, "_default_resolve", lambda host: PUBLIC)
    http, requests = combined_transport(parallel_status=402)
    review = AsyncMock(return_value=ACCEPT)
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Årskurs 4", review, time.monotonic() + 10,
                            client=client, image_mode="commons+parallel")
        first = await images.prepare('<ot-image query="King" alt="Kungen"></ot-image>')
        # The 402 cooled Parallel down: the second slot searches Commons only.
        before = len(requests)
        second = await images.prepare('<ot-image query="King" alt="Kungen"></ot-image>')
        parallel_calls = [r for r in requests[before:] if r.url.host == "api.parallel.ai"]
    assert "upload.wikimedia.org" in first and "upload.wikimedia.org" in second
    assert not parallel_calls
    assert images.parallel_state["available"] is False
    assert any(e.get("image_source") == "parallel" and "credits" in e.get("reason", "")
               for e in images.events)


@pytest.mark.asyncio
async def test_parallel_without_a_key_uses_commons(monkeypatch):
    monkeypatch.setattr(parallel, "_default_resolve", lambda host: PUBLIC)
    monkeypatch.delenv("PARALLEL_API_KEY")
    http, requests = combined_transport()
    review = AsyncMock(return_value=ACCEPT)
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Årskurs 4", review, time.monotonic() + 10,
                            client=client, image_mode="commons+parallel")
        body = await images.prepare('<ot-image query="King" alt="Kungen"></ot-image>')
    assert not any(r.url.host == "api.parallel.ai" for r in requests)
    assert "upload.wikimedia.org" in body


@pytest.mark.asyncio
async def test_unknown_mode_fails_loudly():
    with pytest.raises(ValueError, match="Unknown image mode"):
        PageImages("Rom", AsyncMock(), time.monotonic() + 5, image_mode="parallel+commons")
