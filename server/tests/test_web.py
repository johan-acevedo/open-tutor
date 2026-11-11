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


def test_session_token_carries_screen_capability_when_present():
    client = TestClient(create_app(ENV))
    response = client.post("/api/session", json={**LEARNER, "screen": {"version": 1, "lessonId": "lesson-123456"}})
    assert response.status_code == 200
    claims = jwt.decode(response.json()["token"], ENV["LIVEKIT_API_SECRET"], algorithms=["HS256"])
    assert json.loads(claims["metadata"])["screen"] == {"version": 1, "lessonId": "lesson-123456"}
    assert client.post("/api/session", json={**LEARNER, "screen": {"version": 2, "lessonId": "lesson-123456"}}).status_code == 422
    assert client.post("/api/session", json={**LEARNER, "screen": {"version": 1}}).status_code == 422


def test_rejects_bad_learner_and_missing_config():
    assert TestClient(create_app(ENV)).post("/api/session", json={"learner": {"name": ""}}).status_code == 422
    assert TestClient(create_app({})).post("/api/session", json=LEARNER).status_code == 503


def test_access_code_when_configured():
    client = TestClient(create_app({**ENV, "TUTOR_ACCESS_CODE": "fika"}))
    assert client.post("/api/session", json=LEARNER).status_code == 401
    assert client.post("/api/session", json=LEARNER, headers={"x-tutor-code": "fika"}).status_code == 200


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
