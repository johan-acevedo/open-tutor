"""PostHog product analytics: config endpoint, device id, worker wrapper.

All material here is synthetic and fictional. The fake client means no network.
"""

import json
from types import SimpleNamespace

import jwt  # provided by livekit-api's dependency (pyjwt)
from fastapi.testclient import TestClient
from livekit.agents import llm
from livekit.agents.voice import events

from open_tutor.analytics import (
    Analytics,
    SessionTracker,
    get_analytics,
    posthog_settings,
    reset_analytics,
    stable_distinct_id,
)
from open_tutor.debug_log import config_snapshot
from open_tutor.web import create_app

ENV = {"LIVEKIT_URL": "wss://example.livekit.cloud", "LIVEKIT_API_KEY": "APIkey", "LIVEKIT_API_SECRET": "s" * 40}
LEARNER = {"learner": {"name": "Leo", "grade": 8, "notes": [{"at": "2026-11-01", "topic": "Ekvationer"}]}}


class FakePostHog:
    """Records captures, then optionally explodes (client failures must never surface)."""

    def __init__(self, fail=False):
        self.captured = []
        self.flushed = 0
        self.fail = fail

    def capture(self, distinct_id, event, properties=None):
        if self.fail:
            raise RuntimeError("posthog is down")
        self.captured.append({"distinct_id": distinct_id, "event": event,
                              "properties": properties or {}})

    def flush(self):
        if self.fail:
            raise RuntimeError("posthog is down")
        self.flushed += 1


def test_posthog_settings_off_by_default():
    assert posthog_settings({}) is None
    assert posthog_settings({"TUTOR_POSTHOG_KEY": "  "}) is None


def test_posthog_settings_key_and_default_host():
    assert posthog_settings({"TUTOR_POSTHOG_KEY": "phc_test"}) == {
        "key": "phc_test", "host": "https://eu.i.posthog.com"}
    assert posthog_settings({"TUTOR_POSTHOG_KEY": "phc_test",
                             "TUTOR_POSTHOG_HOST": "https://else.example"}) == {
        "key": "phc_test", "host": "https://else.example"}


def test_config_null_when_unset():
    assert TestClient(create_app(ENV)).get("/api/config").json() == {"posthog": None}


def test_config_returns_key_and_host_when_set():
    client = TestClient(create_app({**ENV, "TUTOR_POSTHOG_KEY": "phc_test"}))
    assert client.get("/api/config").json() == {
        "posthog": {"key": "phc_test", "host": "https://eu.i.posthog.com"}}
    custom = TestClient(create_app({**ENV, "TUTOR_POSTHOG_KEY": "phc_x",
                                    "TUTOR_POSTHOG_HOST": "https://eu.example"}))
    assert custom.get("/api/config").json() == {
        "posthog": {"key": "phc_x", "host": "https://eu.example"}}


def test_config_passes_through_country_middleware():
    client = TestClient(create_app({**ENV, "TUTOR_ALLOWED_COUNTRIES": "SE"}))
    assert client.get("/api/config", headers={"cf-ipcountry": "SE"}).status_code == 200
    assert client.get("/api/config", headers={"cf-ipcountry": "DE"}).status_code == 403
    assert client.get("/api/config").status_code == 403


def test_config_never_carries_secrets():
    body = TestClient(create_app({**ENV, "TUTOR_POSTHOG_KEY": "phc_test",
                                  "TUTOR_ACCESS_CODE": "fika"})).get("/api/config").json()
    assert "fika" not in json.dumps(body)


def test_config_snapshot_marks_enabled_without_the_key():
    assert config_snapshot({})["posthog_enabled"] == "0"
    snapshot = config_snapshot({"TUTOR_POSTHOG_KEY": "phc_test"})
    assert snapshot["posthog_enabled"] == "1"
    assert "phc_test" not in json.dumps(snapshot)


def test_session_accepts_and_forwards_device_id():
    client = TestClient(create_app(ENV))
    response = client.post("/api/session", json={**LEARNER, "device_id": "dev-123"})
    assert response.status_code == 200
    claims = jwt.decode(response.json()["token"], ENV["LIVEKIT_API_SECRET"], algorithms=["HS256"])
    meta = json.loads(claims["metadata"])
    assert meta["device_id"] == "dev-123"
    assert meta["learner"]["name"] == "Leo"


def test_session_without_device_id_has_none_in_metadata():
    client = TestClient(create_app(ENV))
    response = client.post("/api/session", json=LEARNER)
    assert response.status_code == 200
    claims = jwt.decode(response.json()["token"], ENV["LIVEKIT_API_SECRET"], algorithms=["HS256"])
    assert "device_id" not in json.loads(claims["metadata"])


def test_stable_distinct_id():
    assert stable_distinct_id("dev-1", "Leo", "tutor-x") == "device:dev-1:learner:leo"
    # Browser and worker must derive the same id: case and spacing collapse.
    assert stable_distinct_id("dev-1", "  LEO  ", "tutor-x") == \
        stable_distinct_id("dev-1", "leo", "tutor-x")
    assert stable_distinct_id(None, "Leo", "tutor-x") == "tutor-x"
    assert stable_distinct_id("dev-1", "", "tutor-x") == "device:dev-1"


def test_analytics_disabled_without_key_sends_nothing():
    reset_analytics()
    try:
        analytics = get_analytics({})
        assert not analytics.enabled
        analytics.capture("x", "tutor_session_started", {"room": "tutor-x"})  # must not raise
        analytics.shutdown()  # must not raise
    finally:
        reset_analytics()


def test_session_events_reach_fake_client_with_expected_shapes():
    fake = FakePostHog()
    analytics = Analytics.from_env({"TUTOR_POSTHOG_KEY": "phc_test"}, client=fake)
    assert analytics.enabled
    distinct = stable_distinct_id("dev-1", "Leo", "tutor-x")
    analytics.capture(distinct, "tutor_session_started", {
        "room": "tutor-x", "grade": 8, "returning": True,
        "llm_route": "go", "tts": "elevenlabs eleven_v4_turbo"})
    analytics.capture(distinct, "tutor_session_ended", {
        "room": "tutor-x", "duration_s": 61.5, "outcome": "ended_by_child",
        "close_reason": None, "child_spoken_turns": 2, "child_typed_turns": 1,
        "tutor_replies": 3, "tool_calls": 1, "tool_errors": 0, "provider_errors": 0})
    assert [c["event"] for c in fake.captured] == [
        "tutor_session_started", "tutor_session_ended"]
    started = fake.captured[0]
    assert started["distinct_id"] == "device:dev-1:learner:leo"
    assert started["properties"]["room"] == "tutor-x"
    ended = fake.captured[1]["properties"]
    assert ended["outcome"] == "ended_by_child" and ended["tool_errors"] == 0
    analytics.shutdown()
    assert fake.flushed == 1


def test_analytics_swallows_client_exceptions():
    analytics = Analytics.from_env({"TUTOR_POSTHOG_KEY": "phc_test"}, client=FakePostHog(fail=True))
    assert analytics.enabled  # configured, but the client explodes
    analytics.capture("x", "tutor_session_started", {"room": "tutor-x"})  # must not raise
    analytics.shutdown()  # must not raise


def test_tracker_counts_match_debug_summary_without_storing_text():
    tracker = SessionTracker()
    tracker.record_sdk(events.UserInputTranscribedEvent(transcript="hej hej", is_final=False))
    tracker.record_sdk(events.UserInputTranscribedEvent(transcript="hej, visa ekvationer", is_final=True))
    tracker.record_sdk(events.ConversationItemAddedEvent(
        item=llm.ChatMessage(role="assistant", content=["Jag lägger upp det på tavlan."])))
    tracker.record_sdk(events.ConversationItemAddedEvent(
        item=llm.ChatMessage(role="user", content=["Visa hur man löser 3x + 5 = 20."])))
    tracker.record_sdk(events.ConversationItemAddedEvent(
        item=llm.ChatMessage(role="user", content=["[Session event, not the child's words: greet.]"])))
    tracker.record_sdk(SimpleNamespace(type="speech_created"))
    tracker.record_sdk(events.FunctionToolsExecutedEvent(
        function_calls=[llm.FunctionCall(call_id="c1", name="show_steps", arguments="{}")],
        function_call_outputs=[llm.FunctionCallOutput(call_id="c1", name="show_steps",
                                                     output="Item b1 is now visible.", is_error=False)],
    ))
    tracker.record_sdk(events.ErrorEvent(error=ValueError("boom"), source="probe"))
    tracker.record_sdk(events.CloseEvent(reason=events.CloseReason.TASK_COMPLETED))
    summary = tracker.summary()
    assert summary["child_final_turns"] == 1  # non-final transcript not counted
    assert summary["child_typed_turns"] == 1  # injected prompt not counted
    assert summary["tutor_replies"] == 1
    assert summary["tool_calls"] == 1 and summary["tool_errors"] == 0
    assert summary["provider_errors"] == 1
    assert summary["close_reason"] == "task_completed"
    # No conversation text, arguments or outputs anywhere in the stub events.
    assert "3x" not in json.dumps(tracker.events) and "tavlan" not in json.dumps(tracker.events)


def test_tracker_never_raises_on_unknown_events():
    tracker = SessionTracker()
    tracker.record_sdk(object())
    tracker.record_sdk(SimpleNamespace(type="metrics_collected"))
    assert tracker.summary()["tool_calls"] == 0
