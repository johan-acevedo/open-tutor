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


def test_non_ascii_wrong_password_is_rejected_without_consuming_session_limit():
    client = TestClient(create_app({**ENV, "TUTOR_ACCESS_CODE": "fika", "TUTOR_MAX_SESSIONS_PER_HOUR": "1"}))
    wrong = {"x-tutor-code": "felå".encode("latin-1")}
    assert client.post("/api/session", json=LEARNER, headers=wrong).status_code == 401
    assert client.post("/api/session", json=LEARNER, headers={"x-tutor-code": "fika"}).status_code == 200


def test_swedish_password_is_accepted():
    client = TestClient(create_app({**ENV, "TUTOR_ACCESS_CODE": "räven"}))
    assert client.post("/api/session", json=LEARNER, headers={"x-tutor-code": "räven".encode("latin-1")}).status_code == 200
