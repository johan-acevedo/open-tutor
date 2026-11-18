"""Recorded/fast-mode Parallel responses + scripted vision replies; no live key.

Covers response parsing, the request shape (unknown fields return 422, so the
body carries only documented keys), error and cool-down paths, and the SSRF
boundary: private IPs, redirects onto private IPs, and hop limits. DNS is a
stub; HTTP is a MockTransport. PageImages strategy tests live at the bottom.

Run them with: uv run --project server pytest screen/tests/test_parallel_images.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from open_tutor.reviewed_images import ReviewedImageStore
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
# SSRF-safe download: one validation per hop, pinned fetch, no proxy.
# ---------------------------------------------------------------------------

def fake_fetch(routes):
    """A one-hop fetcher: host -> (status, headers, body), list of those, or exception.

    Records every ``(url, pins)`` call and asserts the hop's host was
    validated first: the fetch never resolves by itself."""
    calls = []
    state = {host: (items if isinstance(items, list) else [items])
             for host, items in routes.items()}

    async def get(url, pins):
        host = urllib.parse.urlsplit(url).hostname or ""
        assert host in pins, f"fetch for {host} bypassed validation pins {pins}"
        calls.append((url, {name: list(ips) for name, ips in pins.items()}))
        items = state.get(host, [(404, {}, b"no such host")])
        seen = len([1 for visited, _ in calls if (urllib.parse.urlsplit(visited).hostname or "") == host])
        action = items[min(seen - 1, len(items) - 1)]
        if isinstance(action, Exception):
            raise action
        status, headers, body = action
        return status, {key.lower(): value for key, value in dict(headers).items()}, bytes(body)

    get.calls = calls
    return get


def candidate(url="https://example.com/king.jpg"):
    return commons.Candidate(title="King", source_url="https://example.com/kings",
                             image_url=url, mime_type="", credit="Källa: example.com", source="parallel")


@pytest.mark.asyncio
async def test_downloads_from_a_public_host_and_sniffs_the_type():
    get = fake_fetch({"example.com": (200, {"content-type": "image/jpeg"}, JPEG)})
    data, mime = await parallel.download_image(candidate(), resolve=lambda host: PUBLIC, fetch=get)
    assert data == JPEG and mime == "image/jpeg"
    assert get.calls == [("https://example.com/king.jpg", {"example.com": PUBLIC})]


@pytest.mark.asyncio
async def test_private_loopback_link_local_and_cgnat_addresses_are_refused():
    get = fake_fetch({})
    for address in ("10.1.2.3", "172.16.0.9", "192.168.1.2", "127.0.0.1",
                    "169.254.169.254", "224.0.0.1", "::1", "100.64.0.1", "100.91.148.43"):
        with pytest.raises(ValueError, match="non-public"):
            await parallel.download_image(candidate(), resolve=lambda host, ip=address: [ip], fetch=get)
    assert not get.calls  # refused before any connection


@pytest.mark.asyncio
async def test_a_private_address_hiding_among_public_ones_still_refuses():
    get = fake_fetch({})
    with pytest.raises(ValueError, match="non-public"):
        await parallel.download_image(candidate(), resolve=lambda host: PUBLIC + PRIVATE, fetch=get)
    assert not get.calls


@pytest.mark.asyncio
async def test_https_redirect_to_a_private_host_is_refused():
    get = fake_fetch({"example.com": (302, {"location": "https://127.0.0.1/secret"}, b"")})

    def resolve(host):
        return ["127.0.0.1"] if host == "127.0.0.1" else PUBLIC

    with pytest.raises(ValueError, match="non-public"):
        await parallel.download_image(candidate(), resolve=resolve, fetch=get)
    assert len(get.calls) == 1  # the private hop was validated and never fetched
    assert get.calls[0][0] == "https://example.com/king.jpg"


@pytest.mark.asyncio
async def test_public_redirect_chain_is_followed_and_rechecked():
    get = fake_fetch({"example.com": (302, {"location": "https://cdn.example.net/pic.png"}, b""),
                      "cdn.example.net": (200, {"content-type": "image/png"}, PNG)})
    seen = {"example.com": ["93.184.216.34"], "cdn.example.net": ["151.101.1.65"]}
    data, mime = await parallel.download_image(candidate(), resolve=lambda host: seen[host], fetch=get)
    assert data == PNG and mime == "image/png"
    assert [pins for _, pins in get.calls] == [{"example.com": seen["example.com"]},
                                               {"cdn.example.net": seen["cdn.example.net"]}]


@pytest.mark.asyncio
async def test_too_many_redirects_are_refused():
    get = fake_fetch({"example.com": (302, {"location": "https://example.com/loop"}, b"")})
    with pytest.raises(ValueError, match="too many redirects"):
        await parallel.download_image(candidate(), resolve=lambda host: PUBLIC, fetch=get)
    assert len(get.calls) == parallel.MAX_REDIRECTS + 1


@pytest.mark.asyncio
async def test_non_https_credentialed_and_html_targets_are_refused():
    get = fake_fetch({"example.com": (200, {"content-type": "text/html"}, HTML)})
    for url in ("http://example.com/king.jpg", "https://user@example.com/king.jpg",
                "https://example.com:8443/king.jpg"):
        with pytest.raises(ValueError, match="not https|credentials|port"):
            await parallel.download_image(candidate(url), resolve=lambda host: PUBLIC, fetch=get)
    with pytest.raises(ValueError, match="not an image"):
        await parallel.download_image(candidate(), resolve=lambda host: PUBLIC, fetch=get)
    assert len(get.calls) == 1  # only the HTML one connected


@pytest.mark.asyncio
async def test_oversize_and_growing_streams_are_cut_off():
    big = (200, {"content-type": "image/jpeg", "content-length": str(3 * 1024 * 1024)}, JPEG)
    with pytest.raises(ValueError, match="over the"):
        await parallel.download_image(candidate(), resolve=lambda host: PUBLIC,
                                      fetch=fake_fetch({"example.com": big}))
    lying = (200, {"content-type": "image/jpeg"}, JPEG * 40000)  # no length: the body tells the truth
    with pytest.raises(ValueError, match="grew past"):
        await parallel.download_image(candidate(), resolve=lambda host: PUBLIC,
                                      fetch=fake_fetch({"example.com": lying}))


@pytest.mark.asyncio
async def test_fetch_uses_only_validated_addresses():
    """DNS rebinding: resolve answers public once, then loopback.

    The connection must go to the validated set; the loopback answer is
    never consulted because a hop resolves exactly once, up front."""
    get = fake_fetch({"example.com": (200, {"content-type": "image/jpeg"}, JPEG)})
    resolutions = []

    def resolve(host):
        resolutions.append(host)
        return list(PUBLIC) if len(resolutions) == 1 else list(PRIVATE)

    data, mime = await parallel.download_image(candidate(), resolve=resolve, fetch=get)
    assert (data, mime) == (JPEG, "image/jpeg")
    assert resolutions == ["example.com"]  # one validation, no re-resolution
    assert get.calls == [("https://example.com/king.jpg", {"example.com": PUBLIC})]


@pytest.mark.asyncio
async def test_transport_failures_become_parallel_errors():
    import aiohttp

    async def failing(url, pins):
        raise aiohttp.ClientConnectorError(connection_key=None, oserror=OSError("refused"))

    with pytest.raises(parallel.ParallelError, match="Image download failed"):
        await parallel.download_image(candidate(), resolve=lambda host: PUBLIC, fetch=failing)


# ---------------------------------------------------------------------------
# Pinned fetch against a real local TLS listener.
# ---------------------------------------------------------------------------

TEST_HOST = "images.example.test"  # RFC-reserved: no system DNS can know it.
needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None,
                                   reason="openssl CLI needed for test certificates")


def make_certificates(directory: Path):
    """A throwaway CA plus a server certificate for TEST_HOST."""
    ca_key, ca_crt = directory / "ca.key", directory / "ca.crt"
    srv_key, srv_csr, srv_crt = directory / "srv.key", directory / "srv.csr", directory / "srv.crt"
    srv_ext = directory / "srv_ext.cnf"
    srv_ext.write_text(f"[srv]\nsubjectAltName=DNS:{TEST_HOST}\n"
                       "keyUsage=critical,digitalSignature,keyEncipherment\n"
                       "extendedKeyUsage=serverAuth\n")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", str(ca_key),
                    "-out", str(ca_crt), "-days", "2", "-nodes", "-subj", "/CN=open-tutor-test-ca",
                    "-addext", "basicConstraints=critical,CA:TRUE",
                    "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                    "-addext", "subjectKeyIdentifier=hash"],
                   check=True, capture_output=True)
    subprocess.run(["openssl", "req", "-newkey", "rsa:2048", "-keyout", str(srv_key),
                    "-out", str(srv_csr), "-nodes", "-subj", f"/CN={TEST_HOST}"],
                   check=True, capture_output=True)
    subprocess.run(["openssl", "x509", "-req", "-in", str(srv_csr), "-CA", str(ca_crt),
                    "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(srv_crt),
                    "-days", "2", "-extensions", "srv", "-extfile", str(srv_ext)],
                   check=True, capture_output=True)
    return ca_crt, srv_crt, srv_key


async def start_tls_server(srv_crt: Path, srv_key: Path, body: bytes):
    async def handle(reader, writer):
        try:
            await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        except (asyncio.LimitOverrunError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: "
                     + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
        await writer.drain()
        writer.close()

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(srv_crt), str(srv_key))
    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=context)
    return server, server.sockets[0].getsockname()[1]


@needs_openssl
@pytest.mark.asyncio
async def test_fetch_connects_to_the_pinned_ip_with_hostname_tls(tmp_path):
    """The TCP connection goes to the validated IP while TLS verifies the name."""
    ca_crt, srv_crt, srv_key = make_certificates(tmp_path)
    server, port = await start_tls_server(srv_crt, srv_key, JPEG)
    try:
        trust = ssl.create_default_context(cafile=str(ca_crt))
        url = f"https://{TEST_HOST}:{port}/pic.jpg"
        status, headers, body = await parallel._fetch(url, {TEST_HOST: ["127.0.0.1"]}, ssl=trust)
        assert status == 200 and body == JPEG
        assert headers["content-type"] == "image/jpeg"
    finally:
        server.close()
        await server.wait_closed()


@needs_openssl
@pytest.mark.asyncio
async def test_fetch_refuses_an_untrusted_certificate(tmp_path):
    """Pinning never downgrades verification: a wrong CA must fail."""
    _, srv_crt, srv_key = make_certificates(tmp_path)
    server, port = await start_tls_server(srv_crt, srv_key, JPEG)
    try:
        url = f"https://{TEST_HOST}:{port}/pic.jpg"
        with pytest.raises(parallel.ParallelError, match="Image download failed"):
            await parallel._fetch(url, {TEST_HOST: ["127.0.0.1"]},
                                  ssl=ssl.create_default_context())  # system CAs: not our test CA
    finally:
        server.close()
        await server.wait_closed()


@needs_openssl
@pytest.mark.asyncio
async def test_fetch_never_resolves_an_unpinned_host(tmp_path):
    """A redirect target outside the pin table raises instead of using DNS."""
    ca_crt, srv_crt, srv_key = make_certificates(tmp_path)
    server, port = await start_tls_server(srv_crt, srv_key, JPEG)
    try:
        trust = ssl.create_default_context(cafile=str(ca_crt))
        url = f"https://{TEST_HOST}:{port}/pic.jpg"
        with pytest.raises(parallel.ParallelError, match="Image download failed"):
            await parallel._fetch(url, {}, ssl=trust)
    finally:
        server.close()
        await server.wait_closed()


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


@pytest.fixture
def local_parallel(monkeypatch, tmp_path):
    """Parallel downloads stay local: validated pins, fake bytes, a real image store."""
    monkeypatch.setattr(parallel, "_default_resolve", lambda host: PUBLIC)

    async def get(url, pins):
        return 200, {"content-type": "image/jpeg"}, JPEG

    monkeypatch.setattr(parallel, "_fetch", get)
    return ReviewedImageStore(tmp_path / "images")


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
async def test_combined_falls_back_to_parallel_when_commons_fails(local_parallel):
    http, _ = combined_transport(commons={"query": {"pages": {}}})
    review = AsyncMock(return_value=ACCEPT)
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Årskurs 4", review, time.monotonic() + 10,
                            client=client, image_mode="commons+parallel", image_store=local_parallel)
        body = await images.prepare('<ot-image query="Gustav II Adolf" alt="Kungen"></ot-image>')
    attrs = image_slots(body)[0].attrs
    expected = hashlib.sha256(JPEG).hexdigest() + ".jpg"
    assert attrs["src"] == f"/api/images/{expected}"  # approved bytes, served by us
    assert attrs["credit"] == "Källa: example.com"
    accepted = [e for e in images.events if e["decision"] == "accepted"][-1]
    assert accepted["image_source"] == "parallel" and accepted["served_as"] == attrs["src"]


@pytest.mark.asyncio
async def test_parallel_only_never_touches_commons(local_parallel):
    http, requests = combined_transport()
    review = AsyncMock(return_value=ACCEPT)
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Årskurs 4", review, time.monotonic() + 10,
                            client=client, image_mode="parallel", image_store=local_parallel)
        body = await images.prepare('<ot-image query="Colosseum" alt="Amfiteatern"></ot-image>')
    assert not any(r.url.host == "commons.wikimedia.org" for r in requests)
    expected = hashlib.sha256(JPEG).hexdigest() + ".jpg"
    assert image_slots(body)[0].attrs["src"] == f"/api/images/{expected}"


@pytest.mark.asyncio
async def test_parallel_cooldown_falls_back_to_commons_silently(local_parallel):
    """A fresh slot exercises the search (not a cached approval) while cooling down."""
    http, requests = combined_transport(parallel_status=402)
    review = AsyncMock(return_value=ACCEPT)
    async with httpx.AsyncClient(transport=http) as client:
        # A parallel-mode slot trips the 402 and cools Parallel down.
        failed = PageImages("Årskurs 4", review, time.monotonic() + 10,
                            client=client, image_mode="parallel", image_store=local_parallel)
        fallback = await failed.prepare('<ot-image query="King" alt="Kungen"></ot-image>')
        assert not image_slots(fallback)  # text fallback: no Parallel without credits
        parallel_calls = [r for r in requests if r.url.host == "api.parallel.ai"]
        assert len(parallel_calls) == 1
        # A fresh slot in combined mode searches Commons only while cooling down.
        images = PageImages("Årskurs 4", review, time.monotonic() + 10,
                            client=client, image_mode="commons+parallel", image_store=local_parallel)
        body = await images.prepare('<ot-image query="Drottning" alt="Drottningen"></ot-image>')
        parallel_calls = [r for r in requests if r.url.host == "api.parallel.ai"]
    assert len(parallel_calls) == 1  # the cooled-down call made no new request
    assert "upload.wikimedia.org" in body
    assert images.parallel_state["available"] is False
    assert any(e.get("image_source") == "parallel" and "cooling down" in e.get("reason", "")
               for e in images.events)


@pytest.mark.asyncio
async def test_commons_is_reviewed_before_parallel_answers(local_parallel, monkeypatch):
    """The Commons review does not wait for a slow Parallel search; the sibling is cancelled."""
    gate, entered, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    real_search = parallel.search_images

    async def gated(objective, queries, **kwargs):
        entered.set()
        try:
            await gate.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return await real_search(objective, queries, **kwargs)

    monkeypatch.setattr(parallel, "search_images", gated)
    parallel_downloads = []

    async def no_parallel_download(candidate, **kwargs):
        parallel_downloads.append(candidate.image_url)
        raise AssertionError("Parallel bytes must not download when Commons accepts")

    monkeypatch.setattr(parallel, "download_image", no_parallel_download)
    http, requests = combined_transport()
    review = AsyncMock(return_value=ACCEPT)
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Årskurs 4", review, time.monotonic() + 10,
                            client=client, image_mode="commons+parallel", image_store=local_parallel)
        body = await images.prepare('<ot-image query="King" alt="Kungen"></ot-image>')
    assert entered.is_set()  # the Parallel search started concurrently...
    assert not gate.is_set()  # ...and never answered before the page resolved
    assert cancelled.is_set()  # its still-running search was cancelled, not orphaned
    assert not parallel_downloads
    leftover = [t for t in asyncio.all_tasks()
                if t.get_name() == "page-images-parallel" and not t.done()]
    assert not leftover  # cancelled and drained, not orphaned
    attrs = image_slots(body)[0].attrs
    assert attrs["src"].startswith("https://upload.wikimedia.org/")
    accepted = [e for e in images.events if e["decision"] == "accepted"]
    assert accepted and all(e["image_source"] == "commons" for e in accepted)


@pytest.mark.asyncio
async def test_parallel_search_timeout_falls_back_to_text(local_parallel, monkeypatch):
    """A Parallel search outliving the image budget fails the slot, not the page."""
    entered = asyncio.Event()

    async def hanging(objective, queries, **kwargs):
        entered.set()
        await asyncio.sleep(30)
        raise AssertionError("must be cancelled before this")

    monkeypatch.setattr(parallel, "search_images", hanging)
    http, _ = combined_transport()
    review = AsyncMock(return_value=REJECT)
    started = time.monotonic()
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Årskurs 4", review, time.monotonic() + 0.5,
                            client=client, image_mode="commons+parallel", image_store=local_parallel)
        body = await images.prepare('<ot-image query="King" alt="Kungen"></ot-image>')
    assert entered.is_set()
    assert time.monotonic() - started < 5  # the budget cut the wait, not the 30 s hang
    assert not image_slots(body)
    assert any(e.get("image_source") == "parallel" and "budget" in e.get("reason", "")
               for e in images.events)
    assert not [t for t in asyncio.all_tasks()
                if t.get_name() == "page-images-parallel" and not t.done()]


@pytest.mark.parametrize("failure", ["remote", "proxy"])
@pytest.mark.asyncio
async def test_parallel_transport_errors_cool_down_transiently(local_parallel, monkeypatch, failure):
    """RemoteProtocolError/ProxyError at the Parallel boundary: brief cool-down, Commons kept."""
    real_search = parallel.search_images

    def handle(request):
        if failure == "remote":
            raise httpx.RemoteProtocolError("peer closed connection", request=request)
        raise httpx.ProxyError("proxy refused", request=request)

    async def raising(objective, queries, **kwargs):
        bad = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        async with bad as client:
            return await real_search(objective, queries, client=client)

    monkeypatch.setattr(parallel, "search_images", raising)
    http, _ = combined_transport()
    review = AsyncMock(return_value=ACCEPT)
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Årskurs 4", review, time.monotonic() + 10,
                            client=client, image_mode="commons+parallel", image_store=local_parallel)
        body = await images.prepare('<ot-image query="King" alt="Kungen"></ot-image>')
    assert "upload.wikimedia.org" in body
    state = parallel.state()
    assert state["available"] is False
    assert state["retry_in_s"] <= parallel.COOLDOWN_TRANSIENT_S
    assert any(e.get("image_source") == "parallel" and "unreachable" in e.get("reason", "")
               for e in images.events)
    assert not [t for t in asyncio.all_tasks()
                if t.get_name() == "page-images-parallel" and not t.done()]  # no orphaned sibling


@pytest.mark.asyncio
async def test_commons_search_failure_still_tries_parallel(local_parallel, monkeypatch):
    """One source's transport failure never sinks the other."""
    from screen.tools import commons_images

    async def boom(*args, **kwargs):
        raise RuntimeError("tracker down")

    monkeypatch.setattr(commons_images, "search_images", boom)
    http, _ = combined_transport()
    review = AsyncMock(return_value=ACCEPT)
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Årskurs 4", review, time.monotonic() + 10,
                            client=client, image_mode="commons+parallel", image_store=local_parallel)
        body = await images.prepare('<ot-image query="King" alt="Kungen"></ot-image>')
    assert image_slots(body)[0].attrs["src"].startswith("/api/images/")
    assert any(e.get("image_source") == "commons" and "RuntimeError" in e.get("reason", "")
               for e in images.events)


@pytest.mark.parametrize("payload", [{}, {"results": None}, {"results": "oops"},
                                     [1, 2], {"search_id": "s", "session_id": "s"}])
@pytest.mark.asyncio
async def test_malformed_200_json_cools_down_transiently(payload):
    """A 2xx without a results list is a broken endpoint, not an empty result."""
    http, _ = search_transport(payload=payload)
    async with httpx.AsyncClient(transport=http) as client:
        with pytest.raises(parallel.ParallelError, match="no results list"):
            await parallel.search_images("objective", ["query"], client=client)
    state = parallel.state()
    assert state["available"] is False
    assert state["retry_in_s"] <= parallel.COOLDOWN_TRANSIENT_S


@pytest.mark.asyncio
async def test_empty_results_list_is_not_an_error():
    """A legitimate empty ``results: []`` stays a normal empty result."""
    http, _ = search_transport(payload={"search_id": "s", "session_id": "s", "results": []})
    async with httpx.AsyncClient(transport=http) as client:
        result = await parallel.search_images("objective", ["query"], client=client)
    assert not result.candidates and not result.rejected
    assert parallel.state()["available"] is True


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
