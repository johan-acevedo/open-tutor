import json

import jwt  # provided by livekit-api's dependency (pyjwt)
from fastapi.testclient import TestClient

from open_tutor.web import SessionLimiter, create_app

ENV = {"LIVEKIT_URL": "wss://example.livekit.cloud", "LIVEKIT_API_KEY": "APIkey", "LIVEKIT_API_SECRET": "s" * 40}
LEARNER = {"learner": {"name": "Leo", "grade": 8, "notes": [{"at": "2026-11-01", "topic": "Ekvationer"}]}}


def test_session_token_carries_learner_and_agent_dispatch():
    client = TestClient(create_app(ENV))
    response = client.post("/api/session", json=LEARNER)
    assert response.status_code == 200
    body = response.json()
    assert body["url"] == ENV["LIVEKIT_URL"] and body["room"].startswith("tutor-")
    claims = jwt.decode(body["token"], ENV["LIVEKIT_API_SECRET"], algorithms=["HS256"])
    assert claims["video"]["room"] == body["room"]
    assert json.loads(claims["metadata"])["learner"]["name"] == "Leo"
    assert claims["roomConfig"]["agents"][0]["agentName"] == "open-tutor"


def test_session_carries_band_and_config_advertises_testing_band():
    body = {"learner": {"id": "p9", "name": "Leo", "grade": None, "notes": [], "band": "middle"}}
    client = TestClient(create_app(ENV))
    response = client.post("/api/session", json=body)
    assert response.status_code == 200
    claims = jwt.decode(response.json()["token"], ENV["LIVEKIT_API_SECRET"], algorithms=["HS256"])
    learner_meta = json.loads(claims["metadata"])["learner"]
    assert learner_meta["band"] == "middle"
    assert learner_meta["id"] == "p9"
    # Older pages send no band: still accepted, nothing stored.
    legacy = client.post("/api/session", json=LEARNER)
    assert legacy.status_code == 200
    assert "band" not in json.loads(
        jwt.decode(legacy.json()["token"], ENV["LIVEKIT_API_SECRET"], algorithms=["HS256"])["metadata"])["learner"]
    # Null grade (not known yet) is accepted.
    assert client.post("/api/session", json=body).status_code == 200
    # /api/config names no band by default; TUTOR_BAND sets a testing default.
    assert client.get("/api/config").json()["band"] is None
    assert TestClient(create_app({**ENV, "TUTOR_BAND": "upper"})).get("/api/config").json()["band"] == "upper"
    assert TestClient(create_app({**ENV, "TUTOR_BAND": "nope"})).get("/api/config").json()["band"] is None


def test_rejects_bad_learner_and_missing_config():
    # An empty name is the voice-first start: the tutor learns it by voice.
    assert TestClient(create_app(ENV)).post("/api/session", json={"learner": {"name": ""}}).status_code == 200
    assert TestClient(create_app(ENV)).post("/api/session", json={"learner": {"name": "x" * 41}}).status_code == 422
    assert TestClient(create_app({})).post("/api/session", json=LEARNER).status_code == 503


def test_no_access_code_gate():
    # The public instance is open: no code is asked, and a leftover
    # TUTOR_ACCESS_CODE in the environment no longer gates anything.
    assert TestClient(create_app(ENV)).post("/api/session", json=LEARNER).status_code == 200
    assert TestClient(create_app({**ENV, "TUTOR_ACCESS_CODE": "fika"})).post(
        "/api/session", json=LEARNER).status_code == 200


def test_hourly_session_cap():
    limiter = SessionLimiter(2)
    assert limiter.allow(0) and limiter.allow(1)
    assert not limiter.allow(2)
    assert limiter.allow(3602)
    client = TestClient(create_app({**ENV, "TUTOR_MAX_SESSIONS_PER_HOUR": "1"}))
    assert client.post("/api/session", json=LEARNER).status_code == 200
    assert client.post("/api/session", json=LEARNER).status_code == 429


def test_sweden_public_access_needs_no_password():
    client = TestClient(create_app({**ENV, "TUTOR_ALLOWED_COUNTRIES": "SE"}))
    assert client.post("/api/session", json=LEARNER, headers={"cf-ipcountry": "SE"}).status_code == 200
    assert client.post("/api/session", json=LEARNER, headers={"cf-ipcountry": "DE"}).status_code == 403
    assert client.post("/api/session", json=LEARNER).status_code == 403
    assert client.get("/api/health").status_code == 200


def test_country_restriction_covers_page_and_assets():
    client = TestClient(create_app({**ENV, "TUTOR_ALLOWED_COUNTRIES": "SE"}))
    for path in ("/", "/assets/example.js"):
        assert client.get(path, headers={"cf-ipcountry": "US"}).status_code == 403


def test_rejected_countries_do_not_consume_session_allowance():
    client = TestClient(create_app({**ENV, "TUTOR_ALLOWED_COUNTRIES": "SE", "TUTOR_MAX_SESSIONS_PER_HOUR": "1"}))
    assert client.post("/api/session", json=LEARNER, headers={"cf-ipcountry": "US"}).status_code == 403
    assert client.post("/api/session", json=LEARNER, headers={"cf-ipcountry": "SE"}).status_code == 200


def test_spa_routes_serve_index_for_direct_load_and_refresh(tmp_path, monkeypatch):
    """Single-domain flow: /integritet and band paths load the SPA directly."""
    import open_tutor.web as web

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>Talarum</html>")
    (dist / "assets" / "app.js").write_text("// app")
    monkeypatch.setattr(web, "WEB_DIST", dist)

    client = TestClient(create_app(ENV))
    for path in ("/", "/integritet", "/ak1-6", "/hogstadiet", "/gymnasiet", "/raven"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "Talarum" in response.text, path
    # Static files still serve; unknown /api/* still 404s.
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/api/nope").status_code == 404
