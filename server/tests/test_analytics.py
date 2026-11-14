"""PostHog product analytics: config endpoint, device id, worker wrapper.

All material here is synthetic and fictional. The fake client means no network.
"""

import ast
import asyncio
import json
import time
from pathlib import Path
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
    sanitize_outcome,
    stable_distinct_id,
)
from open_tutor.debug_log import config_snapshot
from open_tutor.web import create_app

ENV = {"LIVEKIT_URL": "wss://example.livekit.cloud", "LIVEKIT_API_KEY": "APIkey", "LIVEKIT_API_SECRET": "s" * 40}
LEARNER = {"learner": {"name": "Leo", "grade": 8, "notes": [{"at": "2026-11-01", "topic": "Ekvationer"}]}}


class FakePostHog:
    """Records captures, then optionally explodes (client failures must never surface).

    The ``capture`` signature mirrors the real posthog 7.x client — the
    event name first, the id and properties as KEYWORDS. It is keyword-only
    on purpose: the old positional call ``capture(distinct_id, event, props)``
    raises TypeError here, so a regression fails loudly instead of
    silently sending nothing (Analytics.capture swallows client errors).
    """

    def __init__(self, fail=False, block_on=None):
        self.captured = []
        self.flushed = 0
        self.fail = fail
        self.block_on = block_on

    def capture(self, event, *, distinct_id=None, properties=None, **kwargs):
        if self.fail:
            raise RuntimeError("posthog is down")
        self.captured.append({"distinct_id": distinct_id, "event": event,
                              "properties": properties or {}})

    def flush(self):
        if self.fail:
            raise RuntimeError("posthog is down")
        if self.block_on is not None:
            # Simulates a hung analytics backend: blocks until the test
            # releases it. asyncio.run() joins executor threads on loop
            # close, so the test must set this event before returning.
            self.block_on.wait(30)
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
    # Spoken transcripts arrive as user conversation items too: spoken, never typed.
    tracker.record_sdk(events.ConversationItemAddedEvent(
        item=llm.ChatMessage(role="user", content=["hej, visa ekvationer"])))
    tracker.record_sdk(events.ConversationItemAddedEvent(
        item=llm.ChatMessage(role="user", content=["[Session event, not the child's words: greet.]"])))
    # Typed turns arrive at the typed-input boundary, not as chat items.
    tracker.record_typed_turn()
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
    assert summary["child_typed_turns"] == 1  # the boundary turn, not the echoes above
    assert summary["tutor_replies"] == 1
    assert summary["tool_calls"] == 1 and summary["tool_errors"] == 0
    assert summary["provider_errors"] == 1
    assert summary["close_reason"] == "task_completed"
    # No conversation text, arguments or outputs anywhere in the stub events.
    assert "ekvationer" not in json.dumps(tracker.events) and "tavlan" not in json.dumps(tracker.events)


def test_tracker_never_raises_on_unknown_events():
    tracker = SessionTracker()
    tracker.record_sdk(object())
    tracker.record_sdk(SimpleNamespace(type="metrics_collected"))
    assert tracker.summary()["tool_calls"] == 0


def test_capture_uses_keyword_arguments_like_posthog_7x():
    """The locked posthog package (7.x) requires
    ``capture(event, distinct_id=..., properties=...)``; the old positional
    call raises TypeError and the fake's keyword-only signature would catch it."""
    fake = FakePostHog()
    analytics = Analytics.from_env({"TUTOR_POSTHOG_KEY": "phc_test"}, client=fake)
    analytics.capture("device:dev-1:learner:leo", "tutor_session_started", {"room": "tutor-x"})
    assert fake.captured == [{"distinct_id": "device:dev-1:learner:leo",
                              "event": "tutor_session_started",
                              "properties": {"room": "tutor-x"}}]


def test_capture_against_the_real_client_disabled():
    """The real ``posthog.Posthog`` client with ``disabled=True`` sends
    nothing and raises nothing: the wrapper call below must survive the real
    signature (a positional call would raise TypeError here too)."""
    from posthog import Posthog

    real = Posthog("phc_test", host="https://eu.i.posthog.com", disabled=True)
    try:
        analytics = Analytics.from_env({"TUTOR_POSTHOG_KEY": "phc_test"}, client=real)
        assert analytics.enabled
        analytics.capture("device:dev-1", "tutor_session_started", {"room": "tutor-x"})
    finally:
        try:
            real.flush()
        except Exception:
            pass


def test_outcome_sanitized_to_fixed_categories():
    assert sanitize_outcome("ended_by_child") == ("ended_by_child", None)
    assert sanitize_outcome("child_left") == ("child_left", None)
    assert sanitize_outcome("provider_error") == ("provider_error", None)
    assert sanitize_outcome("sdk_closed_early") == ("sdk_closed_early", None)
    assert sanitize_outcome("unknown") == ("unknown", None)
    # The worker's f"error: {Class}: {message}" keeps the class, drops the text.
    hostile = "error: ValueError: hemlig läxtext som aldrig får lämna servern 98765"
    assert sanitize_outcome(hostile) == ("error", "ValueError")
    category, error_type = sanitize_outcome(hostile)
    props = {"outcome": category, "room": "tutor-x"}
    if error_type is not None:
        props["error_type"] = error_type
    assert "hemlig" not in json.dumps(props) and "98765" not in json.dumps(props)
    assert sanitize_outcome("error: RuntimeError") == ("error", "RuntimeError")
    assert sanitize_outcome("something unexpected") == ("unknown", None)
    assert sanitize_outcome("") == ("unknown", None)
    assert sanitize_outcome(None) == ("unknown", None)


def test_aclose_flushes_off_the_loop_with_timeout():
    """A slow analytics backend must not park the event loop: aclose
    returns after ~timeout, never raises, even when flush explodes."""
    import threading

    release = threading.Event()
    analytics = Analytics.from_env(
        {"TUTOR_POSTHOG_KEY": "phc_test"}, client=FakePostHog(block_on=release))

    async def hung_backend() -> None:
        started = time.monotonic()
        await analytics.aclose(timeout=0.2)
        assert time.monotonic() - started < 10
        release.set()  # let the thread die before the loop closes

    asyncio.run(hung_backend())
    # Exploding flush is swallowed too.
    asyncio.run(Analytics.from_env(
        {"TUTOR_POSTHOG_KEY": "phc_test"}, client=FakePostHog(fail=True)
    ).aclose(timeout=1.0))
    # Disabled analytics: no-op.
    asyncio.run(Analytics.from_env({}).aclose(timeout=1.0))
    # A fast flush still goes through on the worker thread.
    fake = FakePostHog()
    asyncio.run(Analytics.from_env(
        {"TUTOR_POSTHOG_KEY": "phc_test"}, client=fake
    ).aclose(timeout=5.0))
    assert fake.flushed == 1


def _entrypoint(tree: ast.Module) -> ast.AsyncFunctionDef:
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "entrypoint":
            return node
    raise AssertionError("entrypoint not found in agent.py")


def _direct_loads(body: list[ast.stmt], names: set[str]) -> list[tuple[str, int]]:
    """(name, lineno) for every Name Load in ``body``, NOT descending into
    nested def/lambda bodies (those run later, on events) — but INTO their
    decorators and defaults, which run at registration time."""
    found: list[tuple[str, int]] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in child.decorator_list:
                    visit(dec)
                args = child.args
                for default in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
                    visit(default)
                continue
            if isinstance(child, ast.Lambda):
                continue  # bodies run later, on events
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and child.id in names:
                found.append((child.id, child.lineno))
            visit(child)

    for stmt in body:
        visit(stmt)
    return found


def test_entrypoint_binds_analytics_before_use():
    """Regression test for the P0 UnboundLocalError: ``tracker`` (and
    ``analytics``/``distinct_id``) are entrypoint locals assigned AFTER the
    handler registrations that closed over them, so every session crashed
    even with analytics off.

    Why a static test: the crash is a name-binding order bug, not a runtime
    value bug — no unit test with mocks could observe it short of running a
    full LiveKit session. ``ruff check --select F821,F823`` would flag the
    use-before-assignment too, but ruff is not a project dependency and the
    ambiguous-closure shape (nested handlers) is exactly what linters hedge
    on; an AST assertion on the binding order names the invariant directly
    and runs in the existing suite with no new tooling.
    """
    tree = ast.parse((Path(__file__).parent.parent / "open_tutor" / "agent.py").read_text())
    fn = _entrypoint(tree)
    watched = {"tracker", "analytics", "distinct_id"}
    assigned: set[str] = set()
    for stmt in fn.body:
        for name, lineno in _direct_loads([stmt], watched):
            assert name in assigned, (
                f"{name!r} used at agent.py:{lineno} before it is assigned "
                "in entrypoint (UnboundLocalError in every session)"
            )
        for target in ast.walk(stmt):
            if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store):
                assigned.update({target.id} & watched)


def test_entrypoint_wires_tracker_to_tool_and_close_events():
    """The tracker must see function_tools_executed and close: without
    those subscriptions tool counts stay 0 and close_reason stays null. The
    tracker's own unit test covers the event shapes; this test covers the
    wiring in entrypoint that was missing."""
    tree = ast.parse((Path(__file__).parent.parent / "open_tutor" / "agent.py").read_text())
    fn = _entrypoint(tree)

    subscribed: set[str] = set()
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "on"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Attribute)
            and isinstance(node.args[1].value, ast.Name)
            and node.args[1].value.id == "tracker"
        ):
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                subscribed.add(first.value)
    assert "close" in subscribed, "tracker is not subscribed to the close event"

    tools_handler = next(
        (n for n in ast.walk(fn)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "tools_executed"),
        None,
    )
    assert tools_handler is not None, "tools_executed handler is gone"
    assert any(
        isinstance(n, ast.Name) and n.id == "tracker" and isinstance(n.ctx, ast.Load)
        for n in ast.walk(tools_handler)
    ), "tools_executed handler does not record to the tracker"


def test_spoken_turn_is_not_counted_as_typed():
    """One spoken turn -> spoken=1, typed=0; one typed turn -> typed=1, spoken=0.

    LiveKit adds spoken transcripts as user conversation_item_added, so a
    typed count derived from chat items double-counts every spoken turn.
    """
    tracker = SessionTracker()
    tracker.record_sdk(events.UserInputTranscribedEvent(transcript="hej", is_final=True))
    tracker.record_sdk(events.ConversationItemAddedEvent(
        item=llm.ChatMessage(role="user", content=["hej"])))
    assert tracker.summary()["child_final_turns"] == 1
    assert tracker.summary()["child_typed_turns"] == 0
    tracker.record_typed_turn()
    assert tracker.summary()["child_typed_turns"] == 1
    assert tracker.summary()["child_final_turns"] == 1  # unchanged


def test_entrypoint_counts_typed_turns_at_the_typed_boundary():
    """The tracker must count typed turns from TypedChat, not from SDK
    conversation_item_added user messages: spoken transcripts also arrive
    there, and one spoken turn would count as spoken=1 and typed=1."""
    tree = ast.parse((Path(__file__).parent.parent / "open_tutor" / "agent.py").read_text())
    fn = _entrypoint(tree)
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "attach_typed_listener"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "typed"
        and any(
            isinstance(arg, ast.Attribute)
            and isinstance(arg.value, ast.Name)
            and arg.value.id == "tracker"
            for arg in node.args
        )
        for node in ast.walk(fn)
    ), "entrypoint does not attach the tracker to the typed boundary"


def test_from_env_builds_a_bounded_real_client():
    """The worker-owned client carries a short request timeout and no retries:
    a hung analytics backend must fail fast instead of parking teardown."""
    analytics = Analytics.from_env({"TUTOR_POSTHOG_KEY": "phc_test"})
    try:
        assert analytics.enabled
        assert analytics._client.timeout == 2.0
        assert analytics._client.max_retries == 0
    finally:
        reset_analytics()
        try:
            analytics._client.shutdown()
        except Exception:
            pass


def test_aclose_with_real_client_and_hung_transport_completes_within_budget(monkeypatch):
    """The real posthog.Posthog client whose transport never answers.

    Teardown must finish within ~2-3 s, and must not leave a non-daemon
    thread behind for loop/process shutdown to join (the old asyncio.to_thread
    flush returned on cancellation but kept the executor thread running).
    """
    import threading as thread_mod

    import posthog.consumer as posthog_consumer
    from posthog import Posthog

    hung = thread_mod.Event()
    transport_hit = thread_mod.Event()

    def hanging_batch_post(*args, **kwargs):
        transport_hit.set()
        hung.wait(30)
        raise AssertionError("the hung transport answered")

    monkeypatch.setattr(posthog_consumer, "batch_post", hanging_batch_post)
    bystanders = set(thread_mod.enumerate())
    real = Posthog("phc_test", host="https://eu.i.posthog.com",
                   timeout=0.2, max_retries=0)
    try:
        analytics = Analytics.from_env({"TUTOR_POSTHOG_KEY": "phc_test"}, client=real)
        assert analytics.enabled
        analytics.capture("device:dev-1", "tutor_session_started", {"room": "tutor-x"})
        started = time.monotonic()
        asyncio.run(analytics.aclose(timeout=1.0))
        assert time.monotonic() - started < 5
        assert transport_hit.is_set(), "the hung transport was never hit"
        # Nothing the flush started may still hold the process open: the old
        # non-daemon executor thread survived cancellation and delayed exit.
        lingering = [t for t in thread_mod.enumerate()
                     if t.is_alive() and not t.daemon and t not in bystanders
                     and t is not thread_mod.main_thread()]
        assert lingering == []
    finally:
        hung.set()
