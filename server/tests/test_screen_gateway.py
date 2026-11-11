"""Bounded Screen gateways: mocked auth/bounds/clamp/SSRF/shaping tests.

No live external calls. Upstream Go and Nominatim/Commons are faked via
monkeypatched aiohttp helpers; DNS guards are tested with stubbed getaddrinfo.
"""

from __future__ import annotations

import base64
import json
import socket

import pytest
from fastapi.testclient import TestClient

from open_tutor import screen_gateway
from open_tutor.screen_gateway import (
    BodyTooLarge,
    GEO_TOTAL_MAX_BYTES,
    MAX_TOKENS,
    _shape_commons_candidates,
    _shape_place,
    ensure_safe_geo_url,
    read_body_limited,
    reset_rate_limits,
    validate_chat_body,
)

ENV = {
    "LIVEKIT_URL": "wss://example.livekit.cloud",
    "LIVEKIT_API_KEY": "APIkey",
    "LIVEKIT_API_SECRET": "s" * 40,
    "TUTOR_ACCESS_CODE": "fika",
    "OPENCODE_GO_API_KEY": "test-go-key",
}
ROOM = "tutor-AbC123_-xyz9"


@pytest.fixture(autouse=True)
def _clean():
    reset_rate_limits()
    yield
    reset_rate_limits()


def client(**overrides):
    env = dict(ENV)
    env.update(overrides)
    return TestClient(screen_gateway_app(env))


def screen_gateway_app(env):
    from open_tutor.web import create_app

    return create_app(env)


def chat_body(**overrides):
    body: dict = {"model": "deepseek-v4.1-flash",
                  "messages": [{"role": "user", "content": "hej"}],
                  "stream": True}
    body.update(overrides)
    return body


# ---- fakes ----
class FakeContent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_chunked(self, _n):
        for chunk in self._chunks:
            yield chunk


class FakeUpstreamResp:
    def __init__(self, status=200, headers=None, chunks=None):
        self.status = status
        self.headers = headers or {"Content-Type": "text/event-stream"}
        self.content = FakeContent(chunks or [b"data: {\"ok\":1}\n\n", b"data: [DONE]\n\n"])
        self.released = False

    def release(self):
        self.released = True


class FakeSession:
    handler = None
    last_post: dict | None = None

    def __init__(self, *args, **kwargs):
        pass

    async def post(self, url, json=None, headers=None):  # noqa: A002 - mirrors aiohttp
        FakeSession.last_post = {"url": url, "json": json, "headers": headers}
        if FakeSession.handler is not None:
            return FakeSession.handler(url, json, headers)
        return FakeUpstreamResp()

    async def get(self, *args, **kwargs):  # pragma: no cover - chat never GETs
        raise AssertionError("unexpected GET")

    async def close(self):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@pytest.fixture
def fake_upstream(monkeypatch):
    FakeSession.handler = None
    FakeSession.last_post = None
    monkeypatch.setattr(screen_gateway.aiohttp, "ClientSession", FakeSession)
    return FakeSession


def auth_headers(**extra):
    headers = {"x-tutor-code": "fika"}
    headers.update(extra)
    return headers


# ---- chat auth / room / origin ----
def test_chat_needs_family_code():
    c = client()
    assert c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body()).status_code == 401
    assert c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                  headers={"x-tutor-code": "wrong"}).status_code == 401


def test_chat_accepts_bearer_or_code_header(fake_upstream):
    c = client()
    ok_code = c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                     headers=auth_headers())
    assert ok_code.status_code == 200
    ok_bearer = c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                       headers={"Authorization": "Bearer fika"})
    assert ok_bearer.status_code == 200
    assert ok_bearer.headers["cache-control"] == "no-store"


def test_chat_rejects_bad_room():
    c = client()
    for bad in ("nope", "tutor-short", "tutor-!!!", "tutor-" + "x" * 65, "room-tutor-abc12345"):
        response = c.post(f"/api/screen/openai/{bad}/chat/completions", json=chat_body(),
                          headers=auth_headers())
        assert response.status_code == 400


def test_chat_same_origin_checks(fake_upstream):
    c = client()
    evil = c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                  headers={**auth_headers(), "origin": "http://evil.example"})
    assert evil.status_code == 403
    different_port = c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                            headers={**auth_headers(), "origin": "http://testserver:9999"})
    assert different_port.status_code == 403
    same = c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                  headers={**auth_headers(), "origin": "http://testserver"})
    assert same.status_code == 200
    # No Origin (worker-style fetch) is allowed, mirroring the proof proxy.
    assert c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                  headers=auth_headers()).status_code == 200


def test_chat_country_middleware_covers_gateway(fake_upstream):
    c = client(TUTOR_ALLOWED_COUNTRIES="SE")
    assert c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                  headers={**auth_headers(), "cf-ipcountry": "DE"}).status_code == 403
    assert c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                  headers={**auth_headers(), "cf-ipcountry": "SE"}).status_code == 200


def test_chat_needs_provider_key():
    c = client(OPENCODE_GO_API_KEY="")
    response = c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                      headers=auth_headers())
    assert response.status_code == 503


async def test_streamed_body_cap_stops_before_buffering_remaining_chunks():
    consumed = []

    class Request:
        async def stream(self):
            for chunk in (b"12345", b"67890", b"unread"):
                consumed.append(chunk)
                yield chunk

    request = Request()
    try:
        await read_body_limited(request, 8)
        raise AssertionError("expected BodyTooLarge")
    except BodyTooLarge:
        pass
    assert consumed == [b"12345", b"67890"]


# ---- chat validation ----
def test_chat_model_allowlist():
    assert validate_chat_body(chat_body()) is None
    assert validate_chat_body(chat_body(model="muse-spark-1.3-contributor")) is not None
    c = client()
    response = c.post(f"/api/screen/openai/{ROOM}/chat/completions",
                      json=chat_body(model="gpt-6.1-sol"), headers=auth_headers())
    assert response.status_code == 400


def test_chat_message_bounds():
    assert validate_chat_body({"model": "deepseek-v4.1-flash", "messages": []}) is not None
    big = [{"role": "user", "content": "x"} for _ in range(41)]
    assert validate_chat_body(chat_body(messages=big)) is not None
    huge = "y" * 120_001
    assert validate_chat_body(chat_body(messages=[{"role": "user", "content": huge}])) is not None
    assert validate_chat_body(chat_body(messages=[{"role": "user", "content": "x" * 120_000}])) is None


def test_chat_image_bounds():
    small = "data:image/png;base64," + "A" * 100
    assert validate_chat_body(chat_body(messages=[{"role": "user", "content": [
        {"type": "text", "text": "se"}, {"type": "image_url", "image_url": {"url": small}}]}])) is None
    many = [{"type": "image_url", "image_url": {"url": small}} for _ in range(4)]
    assert validate_chat_body(chat_body(messages=[{"role": "user", "content": many}])) is not None
    remote = [{"type": "image_url", "image_url": {"url": "https://example.com/a.png"}}]
    assert "inline" in (validate_chat_body(chat_body(messages=[{"role": "user", "content": remote}])) or "")
    # ~1.2 MB binary -> b64 length ~1.6 M chars; over that must reject.
    over = "data:image/png;base64," + "A" * 1_700_000
    assert validate_chat_body(chat_body(messages=[{"role": "user",
                                                   "content": [{"type": "image_url",
                                                                "image_url": {"url": over}}]}])) is not None
    unknown = [{"type": "input_audio", "input_audio": {"data": "x"}}]
    assert validate_chat_body(chat_body(messages=[{"role": "user", "content": unknown}])) is not None


def test_chat_tools_bound():
    assert validate_chat_body(chat_body(tools=[{"type": "function"} for _ in range(8)])) is None
    assert validate_chat_body(chat_body(tools=[{"type": "function"} for _ in range(9)])) is not None


def test_chat_null_content_only_for_tools():
    assistant_call = {"role": "assistant", "content": None,
                      "tool_calls": [{"id": "1", "type": "function",
                                      "function": {"name": "f", "arguments": "{}"}}]}
    assert validate_chat_body(chat_body(messages=[assistant_call])) is None
    tool_result = {"role": "tool", "content": None, "tool_call_id": "1"}
    assert validate_chat_body(chat_body(messages=[assistant_call, tool_result])) is None
    bare_null = {"role": "assistant", "content": None}
    assert validate_chat_body(chat_body(messages=[bare_null])) is not None


def test_chat_clamps_output_tokens(fake_upstream):
    c = client()
    body = chat_body(max_tokens=100_000)
    response = c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=body,
                      headers=auth_headers())
    assert response.status_code == 200
    assert FakeSession.last_post is not None
    assert FakeSession.last_post["json"]["max_tokens"] == MAX_TOKENS
    body2 = chat_body(max_completion_tokens=50_000)
    assert c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=body2,
                  headers=auth_headers()).status_code == 200
    assert FakeSession.last_post["json"]["max_completion_tokens"] == MAX_TOKENS
    # Out-of-range small values still reject.
    bad = c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(max_tokens=0),
                 headers=auth_headers())
    assert bad.status_code == 400


def test_chat_body_cap_is_413():
    c = client()
    big_text = "z" * (2_500_001)
    response = c.post(f"/api/screen/openai/{ROOM}/chat/completions",
                      content=json.dumps(chat_body(messages=[{"role": "user", "content": big_text}])),
                      headers={**auth_headers(), "content-type": "application/json"})
    assert response.status_code in (400, 413)
    # Declared length over the cap is rejected without reading the body.
    response = c.post(f"/api/screen/openai/{ROOM}/chat/completions", content=b"{}",
                      headers={**auth_headers(), "content-type": "application/json",
                               "content-length": str(2_500_001)})
    assert response.status_code == 413


# ---- chat upstream behaviour (mocked) ----
def test_chat_forwards_room_session_and_streams(fake_upstream):
    c = client()
    response = c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                      headers=auth_headers())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert b"ok" in response.content or b"DONE" in response.content
    post = FakeSession.last_post
    assert post is not None
    assert post["url"] == "https://opencode.ai/inference/go/openai/v1/chat/completions"
    assert post["headers"]["authorization"] == "Bearer test-go-key"
    assert post["headers"]["x-opencode-session"] == ROOM
    assert post["headers"]["User-Agent"].startswith("open-tutor/")
    assert post["json"]["model"] == "deepseek-v4.1-flash"


def test_chat_upstream_errors_are_generic(fake_upstream):
    c = client()
    FakeSession.handler = staticmethod(lambda url, body, headers: FakeUpstreamResp(status=500))
    response = c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                      headers=auth_headers())
    assert response.status_code == 502
    assert "error" in response.json()

    def _boom(url, body, headers):
        raise TimeoutError("slow upstream")

    FakeSession.handler = staticmethod(_boom)
    response = c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                      headers=auth_headers())
    assert response.status_code == 502
    assert response.json() == {"error": "upstream unavailable"}


def test_chat_rate_limit_per_ip_room(fake_upstream):
    c = client()
    headers = {**auth_headers(), "x-forwarded-for": "10.9.9.9"}
    for _ in range(30):
        assert c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                      headers=headers).status_code == 200
    assert c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                  headers=headers).status_code == 429
    # Another room gets its own bucket.
    assert c.post("/api/screen/openai/tutor-AAAAAAAAAAAAAAAA/chat/completions", json=chat_body(),
                  headers=headers).status_code == 200


def test_chat_does_not_consume_session_allowance(fake_upstream, monkeypatch):
    async def _fake_geo(query):
        return {"query": query, "place": None, "maps": [], "retrievedAt": "2026-01-01T00:00:00+00:00"}

    monkeypatch.setattr(screen_gateway, "geography_lookup", _fake_geo)
    c = client(TUTOR_MAX_SESSIONS_PER_HOUR="1")
    learner = {"learner": {"name": "Leo"}}
    # Screen traffic first: model + research calls must not spend the hourly session budget.
    assert c.post(f"/api/screen/openai/{ROOM}/chat/completions", json=chat_body(),
                  headers=auth_headers()).status_code == 200
    assert c.post("/api/screen/research/geography", json={"query": "Nilen"},
                  headers=auth_headers()).status_code == 200
    assert c.post("/api/session", json=learner, headers=auth_headers()).status_code == 200
    assert c.post("/api/session", json=learner, headers=auth_headers()).status_code == 429


# ---- geography validation/auth ----
def test_geo_validation(monkeypatch):
    async def _fake_geo(query):
        return {"query": query, "place": None, "maps": [], "retrievedAt": "now"}

    monkeypatch.setattr(screen_gateway, "geography_lookup", _fake_geo)
    c = client()
    assert c.post("/api/screen/research/geography", json={},
                  headers=auth_headers()).status_code == 422
    assert c.post("/api/screen/research/geography", json={"query": "x"},
                  headers=auth_headers()).status_code == 422
    assert c.post("/api/screen/research/geography", json={"query": "y" * 201},
                  headers=auth_headers()).status_code == 422
    assert c.post("/api/screen/research/geography", json={"query": "  Nilen  "},
                  headers=auth_headers()).status_code == 200
    assert c.post("/api/screen/research/geography", json={"query": "Nilen"}).status_code == 401
    evil = c.post("/api/screen/research/geography", json={"query": "Nilen"},
                  headers={**auth_headers(), "origin": "http://evil.example"})
    assert evil.status_code == 403


def test_geo_rate_limit(monkeypatch):
    async def _fake_geo(query):
        return {"query": query, "place": None, "maps": [], "retrievedAt": "now"}

    monkeypatch.setattr(screen_gateway, "geography_lookup", _fake_geo)
    c = client()
    headers = {**auth_headers(), "x-forwarded-for": "10.8.8.8"}
    for _ in range(30):
        assert c.post("/api/screen/research/geography", json={"query": "Nilen"},
                      headers=headers).status_code == 200
    assert c.post("/api/screen/research/geography", json={"query": "Nilen"},
                  headers=headers).status_code == 429


def test_geo_generic_failure(monkeypatch):
    async def _boom(query):
        raise RuntimeError("nominatim down")

    monkeypatch.setattr(screen_gateway, "geography_lookup", _boom)
    c = client()
    response = c.post("/api/screen/research/geography", json={"query": "Nilen"},
                      headers=auth_headers())
    assert response.status_code == 502
    assert response.json() == {"error": "research unavailable"}


# ---- geography SSRF guards ----
def public_dns(monkeypatch, ip="93.184.216.34"):
    def _fake(host, port, type=socket.SOCK_STREAM):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake)


def test_geo_url_allowlist(monkeypatch):
    public_dns(monkeypatch)
    ensure_safe_geo_url("https://nominatim.openstreetmap.org/search?format=jsonv2&q=x")
    ensure_safe_geo_url("https://commons.wikimedia.org/w/api.php?action=query")
    ensure_safe_geo_url("https://upload.wikimedia.org/wikipedia/commons/a/ab/Map.png")
    for bad in ("http://nominatim.openstreetmap.org/search?q=x",
                "https://evil.example/map.png",
                "https://tile.openstreetmap.org/0/0/0.png",
                "https://nominatim.openstreetmap.org:8080/search?q=x",
                "https://user:pass@nominatim.openstreetmap.org/search?q=x"):
        with pytest.raises(ValueError):
            ensure_safe_geo_url(bad)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.1.2", "169.254.169.254",
                                "::1", "fc00::1", "224.0.0.1", "0.0.0.0"])
def test_geo_blocks_non_global_dns(monkeypatch, ip):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port, type=socket.SOCK_STREAM: [(family, socket.SOCK_STREAM, 6, "", (ip, port))])
    with pytest.raises(ValueError):
        ensure_safe_geo_url("https://nominatim.openstreetmap.org/search?format=jsonv2&q=x")


def test_geo_redirect_to_evil_is_blocked(monkeypatch):
    public_dns(monkeypatch)
    with pytest.raises(ValueError):
        ensure_safe_geo_url("https://upload.wikimedia.org.evil.example/x.png")


# ---- geography shaping (mocked fetchers) ----
def test_shape_place_and_commons_filter():
    place = _shape_place({"lat": "59.3", "lon": "18.0", "display_name": "Stockholm",
                          "boundingbox": ["59.0", "59.6", "17.7", "18.5"],
                          "address": {"city": "Stockholm"}, "category": "place", "type": "city"})
    assert place is not None and place["lat"] == pytest.approx(59.3)
    assert place["boundingBox"] == [59.0, 59.6, 17.7, 18.5]
    assert _shape_place({"lat": "bad", "lon": "0"}) is None

    payload = {"query": {"pages": [
        {"title": "File:Stockholm map.png",
         "imageinfo": [{"url": "https://upload.wikimedia.org/wikipedia/commons/a/map.png",
                        "mime": "image/png",
                        "extmetadata": {"Artist": {"value": "<b>Anna</b>"},
                                        "LicenseShortName": {"value": "CC-BY"}}} ]},
        {"title": "File:Evil.svg",
         "imageinfo": [{"url": "https://upload.wikimedia.org/wikipedia/commons/a/evil.svg",
                        "mime": "image/svg+xml"}]},
        {"title": "NotAFile", "imageinfo": [{"url": "https://upload.wikimedia.org/x.png",
                                             "mime": "image/png"}]},
    ]}}
    candidates = _shape_commons_candidates(payload)
    assert len(candidates) == 1
    assert candidates[0]["attribution"] == "Anna"
    assert candidates[0]["license"] == "CC-BY"
    assert candidates[0]["sourceUrl"].startswith("https://commons.wikimedia.org/wiki/File")


def test_geography_lookup_shapes_bounded_response(monkeypatch):
    nominatim = [{"lat": "29.9", "lon": "31.1", "display_name": "Nile, Egypt",
                  "boundingbox": ["29.0", "30.5", "30.5", "31.8"],
                  "address": {"river": "Nile"}, "category": "waterway", "type": "river"}]
    commons = {"query": {"pages": [
        {"title": "File:Nile map.png",
         "imageinfo": [{"url": "https://upload.wikimedia.org/wikipedia/commons/nile.png",
                        "mime": "image/png",
                        "extmetadata": {"Artist": {"value": "Karta"},
                                        "LicenseShortName": {"value": "CC0"}}} ]},
        {"title": "File:Nile photo.jpg",
         "imageinfo": [{"url": "https://upload.wikimedia.org/wikipedia/commons/nile.jpg",
                        "mime": "image/jpeg", "extmetadata": {}}]},
    ]}}

    async def _fake_json(url, **kwargs):
        if "nominatim" in url:
            return nominatim
        return commons

    async def _fake_image(url):
        return (b"\x89PNG" + b"x" * 1000, "image/png" if url.endswith(".png") else "image/jpeg")

    monkeypatch.setattr(screen_gateway, "_fetch_json", _fake_json)
    monkeypatch.setattr(screen_gateway, "_fetch_image_bytes", _fake_image)
    public_dns(monkeypatch)

    import asyncio

    result = asyncio.run(screen_gateway.geography_lookup("Nilen"))
    assert result["query"] == "Nilen"
    assert result["place"]["displayName"].startswith("Nile")
    assert len(result["maps"]) == 2
    for entry in result["maps"]:
        assert entry["dataUrl"].startswith("data:image/")
        assert entry["sourceUrl"].startswith("https://commons.wikimedia.org/wiki/File")
        assert "retrievedAt" in entry and entry["bytes"] > 0
    assert result["maps"][0]["attribution"] == "Karta"
    assert len(json.dumps(result).encode()) <= GEO_TOTAL_MAX_BYTES


def test_geography_lookup_skips_bad_images_and_caps_total(monkeypatch):
    nominatim = [{"lat": "0", "lon": "0", "display_name": "Nowhere"}]
    pages = []
    for i in range(10):
        pages.append({"title": f"File:Map{i}.png",
                      "imageinfo": [{"url": f"https://upload.wikimedia.org/wikipedia/commons/{i}.png",
                                     "mime": "image/png", "extmetadata": {}}]})
    commons = {"query": {"pages": pages}}

    async def _fake_json(url, **kwargs):
        return nominatim if "nominatim" in url else commons

    async def _fake_image(url):
        if url.endswith("0.png"):
            raise RuntimeError("fetch failed")
        if url.endswith("1.png"):
            return (b"x" * 10, "image/svg+xml")  # unsafe type slips past search; must not be stored
        return (b"y" * 400_000, "image/png")

    monkeypatch.setattr(screen_gateway, "_fetch_json", _fake_json)
    monkeypatch.setattr(screen_gateway, "_fetch_image_bytes", _fake_image)

    import asyncio

    result = asyncio.run(screen_gateway.geography_lookup("Vart som helst"))
    assert len(result["maps"]) <= 3
    assert all(entry["mime"] in ("image/png", "image/jpeg", "image/webp") for entry in result["maps"])
    assert len(json.dumps(result).encode()) <= GEO_TOTAL_MAX_BYTES


def test_geography_lookup_empty_place_still_returns_maps(monkeypatch):
    async def _fake_json(url, **kwargs):
        return [] if "nominatim" in url else {"query": {"pages": []}}

    monkeypatch.setattr(screen_gateway, "_fetch_json", _fake_json)

    async def _no_image(url):  # pragma: no cover - no candidates, never called
        raise AssertionError("no download expected")

    monkeypatch.setattr(screen_gateway, "_fetch_image_bytes", _no_image)
    import asyncio

    result = asyncio.run(screen_gateway.geography_lookup("Qsdfghjk"))
    assert result["place"] is None
    assert result["maps"] == []


def test_geo_endpoint_returns_shaped_maps(monkeypatch):
    image_bytes = base64.b64encode(b"fakepng" * 100).decode()
    payload = {"query": "Nilen",
               "place": {"displayName": "Nile", "lat": 29.9, "lon": 31.1,
                         "boundingBox": [29.0, 30.5, 30.5, 31.8],
                         "address": {}, "category": "waterway", "type": "river"},
               "maps": [{"dataUrl": f"data:image/png;base64,{image_bytes}", "mime": "image/png",
                         "bytes": 700, "sourceUrl": "https://commons.wikimedia.org/wiki/File:Nile.png",
                         "retrievedAt": "2026-11-11T00:00:00+00:00",
                         "attribution": "Karta", "license": "CC0"}],
               "retrievedAt": "2026-11-11T00:00:00+00:00"}

    async def _fake_geo(query):
        assert query == "Nilen"
        return payload

    monkeypatch.setattr(screen_gateway, "geography_lookup", _fake_geo)
    c = client()
    response = c.post("/api/screen/research/geography", json={"query": "Nilen"},
                      headers=auth_headers())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["place"]["lat"] == pytest.approx(29.9)
    assert body["maps"][0]["dataUrl"].startswith("data:image/png;base64,")
    assert body["maps"][0]["sourceUrl"].startswith("https://commons.wikimedia.org/wiki/")
