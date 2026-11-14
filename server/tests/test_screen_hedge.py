"""Hedged screen calls: first output text wins, the loser is closed, no leaks.

The write/look/retry model calls stream, so the first output text is observable.
When the primary produced nothing within SCREEN_HEDGE_AFTER_S, the same call
starts on SCREEN_FALLBACK; the first side to produce text serves the whole call
and the other is cancelled with its stream closed. A step's own remaining budget
caps the hedge deadline so both attempts fit inside it.
"""

import asyncio
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from open_tutor import http_clients
from open_tutor.screen import Screen


def make_screen(tmp_path, **kwargs):
    kwargs.setdefault("model_call", AsyncMock(return_value="<h1>Hej</h1>"))
    kwargs.setdefault("render_page", AsyncMock(return_value=(b"PNG", [])))
    return Screen({"name": "Test", "grade": 4}, tmp_path / "pages", **kwargs)


def hedging_screen(tmp_path, monkeypatch, **kwargs):
    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    monkeypatch.setenv("SCREEN_LOOK", "0")
    return make_screen(tmp_path, **kwargs)


def job_meta(tmp_path):
    import json

    return json.loads((tmp_path / "pages" / "s1" / "meta.json").read_text())


@pytest.fixture
def screen_events(monkeypatch):
    import open_tutor.debug_log as debug_log

    events = []
    monkeypatch.setattr(debug_log, "record_active",
                        lambda event, data=None: events.append((event, data or {})))
    return events


# ---- seam-level races (fake model calls, completion is their first text) --------


async def test_fast_primary_never_starts_the_backup(tmp_path, monkeypatch, screen_events):
    screen = hedging_screen(
        tmp_path, monkeypatch,
        model_call=AsyncMock(return_value="<h1>Först</h1>"),
        fallback_call=AsyncMock(return_value="<h1>Backup</h1>"))
    delivered = {}
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert delivered["page"].body == "<h1>Först</h1>"
    meta = job_meta(tmp_path)
    assert meta["provider"] == "go" and meta["failover"] is False
    assert meta["hedged"] is False and meta["ttft_s"] is not None
    assert not [e for e, _ in screen_events if e == "screen_hedge"]
    summary = screen.screen_stats_summary()
    assert summary["screen_calls_total"] == 1 and summary["screen_hedged_calls"] == 0
    assert summary["screen_provider_wins"] == {"go": 1}
    await screen.aclose()


async def test_slow_primary_loses_and_is_cancelled(tmp_path, monkeypatch, screen_events):
    cancelled = []

    async def slow_primary(system, user, images, look_png):
        try:
            await asyncio.sleep(30)
            return "<h1>Sent</h1>"
        except asyncio.CancelledError:
            cancelled.append("primary")
            raise

    async def fast_fallback(system, user, images, look_png):
        return "<h1>Backup</h1>"

    monkeypatch.setenv("SCREEN_HEDGE_AFTER_S", "0.05")
    screen = hedging_screen(tmp_path, monkeypatch, model_call=slow_primary,
                            fallback_call=fast_fallback)
    delivered = {}
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert delivered["page"].body == "<h1>Backup</h1>"
    assert cancelled == ["primary"]  # the loser was cancelled, nothing left running
    meta = job_meta(tmp_path)
    assert meta["provider"] == "cc" and meta["failover"] is True
    assert meta["hedged"] is True and meta["ttft_s"] is not None
    hedges = [data for event, data in screen_events if event == "screen_hedge"]
    assert len(hedges) == 1 and hedges[0]["winner"] == "cc"
    assert hedges[0]["loser"] == "cancelled"
    await screen.aclose()


async def test_primary_error_serves_fallback_and_keeps_the_event(tmp_path, monkeypatch,
                                                                 screen_events):
    screen = hedging_screen(
        tmp_path, monkeypatch,
        model_call=AsyncMock(side_effect=RuntimeError("provider down")),
        fallback_call=AsyncMock(return_value="<h1>Backup</h1>"))
    delivered = {}
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert delivered["page"].body == "<h1>Backup</h1>"
    meta = job_meta(tmp_path)
    assert meta["provider"] == "cc" and meta["failover"] is True
    assert meta["primary_error"] == "RuntimeError"
    failovers = [data for event, data in screen_events if event == "screen_failover"]
    assert len(failovers) == 1 and failovers[0]["error"] == "RuntimeError"
    await screen.aclose()


async def test_too_little_budget_serves_alone_without_threads_or_tasks(tmp_path, monkeypatch):
    threads_before = threading.enumerate()
    tasks_before = {t.get_name() for t in asyncio.all_tasks()}
    screen = hedging_screen(tmp_path, monkeypatch, timeout=0.5,
                            model_call=AsyncMock(side_effect=RuntimeError("down")),
                            fallback_call=AsyncMock(return_value="<h1>Backup</h1>"))
    delivered, failures = {}, []
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.on_failure = failures.append
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert delivered == {} and len(failures) == 1  # the job fails as today
    tasks_after = {t.get_name() for t in asyncio.all_tasks()}
    assert tasks_after == tasks_before  # nothing left running
    assert len(threading.enumerate()) == len(threads_before)
    await screen.aclose()


# ---- async streaming races (the real provider path, stub transport) --------------


class StubStream:
    """An OpenAI SDK async stream double: yields text deltas, then stalls or ends."""

    def __init__(self, deltas=(), stall=False, fail_after=None):
        self._deltas = list(deltas)
        self._stall = stall
        self._fail_after = fail_after
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._deltas:
            return SimpleNamespace(type="response.output_text.delta",
                                   delta=self._deltas.pop(0))
        if self._fail_after is not None:
            raise self._fail_after
        if self._stall:
            await asyncio.sleep(3600)  # trickles nothing; cancellation must end this
        raise StopAsyncIteration

    async def close(self):
        self.closed = True


def stub_openai(monkeypatch, streams):
    """Route the shared AsyncOpenAI factory at a stub transport.

    ``streams`` maps a model-name prefix to a ``() -> StubStream`` factory; every
    request asserts the streaming wire shape (streaming, no server state, session
    header).
    """
    from openai import AsyncOpenAI

    import httpx2 as httpx

    created = []

    class Responses:
        async def create(self, **kwargs):
            assert kwargs.get("stream") is True
            assert kwargs.get("store") is False
            assert kwargs.get("extra_headers", {}).get("x-opencode-session") == "screen"
            model = kwargs.get("model", "")
            for prefix, factory in streams.items():
                if model.startswith(prefix):
                    stream = factory()
                    created.append(stream)
                    return stream
            raise AssertionError(f"unexpected model {model!r}")

    class Client:
        responses = Responses()

    monkeypatch.setattr(http_clients, "shared_async_openai",
                        lambda base_url, api_key, user_agent: Client())
    return created


async def test_trickling_loser_is_closed_and_nothing_is_left(tmp_path, monkeypatch):
    """P1: a provider that trickles bytes forever must not outlive its job.

    The primary's stream never produces text (it would hold a to_thread worker
    forever in the old blocking client); the backup wins, the loser is closed,
    and no task or thread is left behind.
    """
    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    monkeypatch.setenv("SCREEN_LOOK", "0")
    monkeypatch.setenv("SCREEN_HEDGE_AFTER_S", "0.2")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-go")
    monkeypatch.setenv("COMMAND_CODE_API_KEY", "test-cc")
    created = stub_openai(monkeypatch, {
        "muse-": lambda: StubStream(stall=True),
        "meta/": lambda: StubStream(deltas=["<h1>Backup</h1>"]),
    })
    threads_before = threading.enumerate()
    tasks_before = {t.get_name() for t in asyncio.all_tasks()}
    screen = make_screen(tmp_path, model_call=None)  # the real streaming calls, no fakes
    delivered = {}
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert delivered["page"].body == "<h1>Backup</h1>"
    primary = [s for s in created if isinstance(s, StubStream)][0]
    assert primary.closed  # the cancelled stream was closed, its task ended
    lingering = [t.get_name() for t in asyncio.all_tasks()
                 if t.get_name().startswith("screen-hedge-")]
    assert lingering == []
    assert {t.get_name() for t in asyncio.all_tasks()} == tasks_before
    assert len(threading.enumerate()) == len(threads_before)
    await screen.aclose()


async def test_winner_mid_answer_error_fails_over_to_the_other_side(tmp_path, monkeypatch):
    """A winner that dies mid-answer gets one failover-like attempt elsewhere."""
    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    monkeypatch.setenv("SCREEN_LOOK", "0")
    monkeypatch.setenv("SCREEN_HEDGE_AFTER_S", "0.2")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-go")
    monkeypatch.setenv("COMMAND_CODE_API_KEY", "test-cc")
    stub_openai(monkeypatch, {
        "muse-": lambda: StubStream(deltas=["halv "],
                                    fail_after=RuntimeError("connection dropped")),
        "meta/": lambda: StubStream(deltas=["<h1>Backup</h1>"]),
    })
    screen = make_screen(tmp_path, model_call=None)  # the real streaming calls
    delivered = {}
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert delivered["page"].body == "<h1>Backup</h1>"
    meta = job_meta(tmp_path)
    assert meta["provider"] == "cc" and meta["failover"] is True
    assert meta["primary_error"] == "RuntimeError"
    await screen.aclose()


# ---- step budgets ------------------------------------------------------------------


async def test_step_deadline_fits_both_attempts_inside_it(tmp_path, monkeypatch):
    """P2: a look step's own ~6 s deadline caps the hedge, so the backup can start."""
    started: dict[str, float] = {}
    t0 = time.monotonic()

    async def slow_primary(system, user, images, look_png):
        started["primary"] = time.monotonic() - t0
        await asyncio.sleep(30)
        return "<h1>Sent</h1>"

    async def fast_fallback(system, user, images, look_png):
        started["fallback"] = time.monotonic() - t0
        return "<h1>Backup</h1>"

    monkeypatch.delenv("SCREEN_HEDGE_AFTER_S", raising=False)  # the 5 s default
    screen = hedging_screen(tmp_path, monkeypatch, model_call=slow_primary,
                            fallback_call=fast_fallback)
    text, _ = await screen._call_model("System", "Lesson", kind="look", budget_s=6.0)

    assert text == "<h1>Backup</h1>"
    # Half of the 6 s step, not the 5 s default: the backup starts in time.
    assert 2.0 < started["fallback"] < 5.0
    summary = screen.screen_stats_summary()
    assert summary["screen_calls"]["look"]["hedges"] == 1
    await screen.aclose()


async def test_legacy_step_deadline_fits_both_attempts_inside_it(tmp_path, monkeypatch):
    """P2, legacy path: the flat primary timeout is fitted into the step budget."""
    monkeypatch.setenv("SCREEN_HEDGE_AFTER_S", "")  # the #64 flat-timeout failover
    monkeypatch.setenv("SCREEN_PRIMARY_TIMEOUT_S", "10")

    async def slow_primary(system, user, images, look_png):
        await asyncio.sleep(30)
        return "<h1>Sent</h1>"

    screen = hedging_screen(tmp_path, monkeypatch, model_call=slow_primary,
                            fallback_call=AsyncMock(return_value="<h1>Backup</h1>"))
    started = time.monotonic()
    text, _ = await screen._call_model("System", "Lesson", kind="look", budget_s=6.0)

    assert text == "<h1>Backup</h1>"
    assert time.monotonic() - started < 6.0  # not cut by the outer step timeout
    await screen.aclose()


# ---- backup credentials --------------------------------------------------------------


async def test_missing_backup_key_disables_hedge_with_a_warning(tmp_path, monkeypatch, caplog,
                                                           screen_events):
    """P2: without the backup key the primary's error surfaces as itself."""
    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    monkeypatch.delenv("COMMAND_CODE_API_KEY", raising=False)
    monkeypatch.setenv("SCREEN_LOOK", "0")
    with caplog.at_level("WARNING", logger="open-tutor"):
        screen = make_screen(tmp_path,
                             model_call=AsyncMock(side_effect=RuntimeError("primary down")))
    assert "COMMAND_CODE_API_KEY" in caplog.text
    assert screen._fallback_ready() is None

    delivered, failures = {}, []
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.on_failure = failures.append
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert delivered == {} and len(failures) == 1  # the job fails as without a backup
    # No page was delivered, so no backup was ever attempted: the primary's
    # error is the failure, unmasked by any fallback config error.
    assert not (tmp_path / "pages" / "s1" / "meta.json").exists()
    assert "primary down" in failures[0] or "Explain in words" in failures[0]
    summary = screen.screen_stats_summary()
    assert summary["screen_calls_total"] == 1 and summary["screen_hedged_calls"] == 0
    assert not [e for e, _ in screen_events if e == "screen_failover"]
    await screen.aclose()


# ---- analytics ------------------------------------------------------------------------


async def test_screen_stats_cover_kinds_and_provider_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_HEDGE_AFTER_S", "0.05")
    screen = hedging_screen(
        tmp_path, monkeypatch,
        model_call=AsyncMock(return_value="<h1>Först</h1>"),
        fallback_call=AsyncMock(return_value="<h1>Backup</h1>"))
    text, _ = await screen._call_model("System", "Lesson", kind="write")
    assert text == "<h1>Först</h1>"
    text, _ = await screen._call_model("System", "Lesson", kind="look")
    assert text == "<h1>Först</h1>"

    summary = screen.screen_stats_summary()
    assert summary["screen_calls_total"] == 2 and summary["screen_hedged_calls"] == 0
    assert summary["screen_provider_wins"] == {"go": 2}
    assert summary["screen_calls"]["write"]["calls"] == 1
    assert summary["screen_calls"]["look"]["median_ttft_s"] is not None
    await screen.aclose()


def test_empty_call_list_summarizes_to_zero():
    from open_tutor.analytics import summarize_screen_calls

    assert summarize_screen_calls([]) == {"calls_total": 0, "hedged_calls": 0,
                                          "provider_wins": {}, "calls": {}}
    assert summarize_screen_calls(None)["calls_total"] == 0



# ---- review fixes --------------------------------------------------------------


async def test_caller_cancel_during_winner_does_not_start_backup(tmp_path, monkeypatch):
    """P1: a caller cancellation while awaiting the winner propagates at once.

    The old ``except BaseException`` caught the caller's ``CancelledError`` as
    a provider failure and started a backup that outlived the caller's timeout.
    """
    monkeypatch.setenv("SCREEN_HEDGE_AFTER_S", "0.05")

    async def hanging_primary(system, user, images, look_png, on_first_text=None):
        if on_first_text is not None:
            on_first_text()  # first text at once: the primary wins, no hedge
        await asyncio.sleep(30)
        return "<h1>Late</h1>"

    fallback_calls = []

    async def counting_fallback(system, user, images, look_png):
        fallback_calls.append(1)
        return "<h1>Backup</h1>"

    screen = hedging_screen(tmp_path, monkeypatch, model_call=hanging_primary,
                            fallback_call=counting_fallback)
    task = asyncio.create_task(screen._call_model("System", "Lesson", kind="look"))
    await asyncio.sleep(0.2)  # the primary won; the turn hangs mid-answer
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert fallback_calls == []  # no backup was started after the cancel
    lingering = [t.get_name() for t in asyncio.all_tasks()
                 if t.get_name().startswith("screen-hedge-")]
    assert lingering == []
    await screen.aclose()


async def test_step_budget_is_shared_with_the_call(tmp_path, monkeypatch):
    """P2: the optional step's capped budget reaches the call and the timeout.

    The old ``_bounded`` passed the remaining job budget (tens of seconds) into
    a call it cancelled after the 6 s step cap, so the hedge fired at 5 s and
    the backup never finished before the cut.
    """
    received = []
    started: dict[str, float] = {}
    t0 = time.monotonic()

    async def slow_primary(system, user, images, look_png):
        started["primary"] = time.monotonic() - t0
        await asyncio.sleep(30)
        return "<h1>Sent</h1>"

    async def slowish_fallback(system, user, images, look_png):
        started["fallback"] = time.monotonic() - t0
        await asyncio.sleep(1.5)
        return "<h1>Backup</h1>"

    monkeypatch.delenv("SCREEN_HEDGE_AFTER_S", raising=False)  # the 5 s default
    screen = hedging_screen(tmp_path, monkeypatch, timeout=60.0,
                            model_call=slow_primary, fallback_call=slowish_fallback)

    async def make_call(budget):
        received.append(budget)
        return await screen._call_model("System", "Lesson", kind="look",
                                        budget_s=budget)

    (text, _call_s), _elapsed, why = await screen._bounded(t0, 3.0, make_call)
    assert why == "" and text == "<h1>Backup</h1>"
    assert received and max(received) <= 6.05  # the capped, not the ~57 s job, budget
    assert started["fallback"] < 5.0  # the hedge fits inside the 6 s step
    await screen.aclose()


async def test_secondary_win_then_failure_does_not_restart_primary(tmp_path, monkeypatch):
    """P2: when the secondary wins then dies, the cancelled primary is not restarted.

    Both routes were already attempted in the hedged race; a third request on
    the primary is never made. The winner's own error surfaces instead.
    """
    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    monkeypatch.setenv("SCREEN_LOOK", "0")
    monkeypatch.setenv("SCREEN_HEDGE_AFTER_S", "0.2")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-go")
    monkeypatch.setenv("COMMAND_CODE_API_KEY", "test-cc")
    created = {"go": 0, "cc": 0}

    def go_stream():
        created["go"] += 1
        return StubStream(stall=True)  # never any text; loses the race

    def cc_stream():
        created["cc"] += 1
        return StubStream(deltas=["halv "],
                          fail_after=RuntimeError("connection dropped"))

    stub_openai(monkeypatch, {"muse-": go_stream, "meta/": cc_stream})
    screen = make_screen(tmp_path, model_call=None)  # the real streaming calls
    with pytest.raises(RuntimeError, match="connection dropped"):
        await asyncio.wait_for(screen._call_model("System", "Lesson", kind="write"),
                               timeout=10)
    assert created == {"go": 1, "cc": 1}  # no restart of the already tried primary
    summary = screen.screen_stats_summary()
    assert summary["screen_calls_total"] == 1 and summary["screen_hedged_calls"] == 1
    await screen.aclose()


async def test_secondary_first_text_includes_hedge_wait(tmp_path, monkeypatch):
    """P2: every route's first-text time is measured from the call's start.

    The old code timed the backup from its own start, omitting the hedge wait
    (up to 5 s) from the debug trail and analytics.
    """
    monkeypatch.setenv("SCREEN_HEDGE_AFTER_S", "0.3")

    async def slow_primary(system, user, images, look_png):
        await asyncio.sleep(30)
        return "<h1>Sent</h1>"

    async def fast_fallback(system, user, images, look_png):
        return "<h1>Backup</h1>"

    screen = hedging_screen(tmp_path, monkeypatch, model_call=slow_primary,
                            fallback_call=fast_fallback)
    text, _ = await screen._call_model("System", "Lesson", kind="look")
    assert text == "<h1>Backup</h1>"
    ttft = screen.screen_stats_summary()["screen_calls"]["look"]["median_ttft_s"]
    assert ttft is not None and ttft >= 0.25  # includes the ~0.3 s hedge wait
    await screen.aclose()


# ---- third fix round: caller cancel during loser teardown --------------------


async def test_caller_cancel_during_loser_teardown_propagates(tmp_path, monkeypatch):
    """P1: a caller cancellation landing in the loser's teardown propagates.

    Fails on 7bfa963, where ``except BaseException`` around the loser's teardown
    swallowed the caller's cancellation, then the call kept awaiting the
    secondary and returned a page.
    """
    import time as _time

    try:
        from open_tutor.screen import SCREEN_LOSER_CLEANUP_BOUND_S
    except ImportError:  # pragma: no cover - pre-fix code without the bound
        SCREEN_LOSER_CLEANUP_BOUND_S = 2.0

    async def slow_teardown_primary(system, user, images, look_png):
        try:
            await asyncio.sleep(30)
            return "<h1>Sent</h1>"
        except asyncio.CancelledError:
            await asyncio.sleep(0.5)  # slow teardown: the cancel lands here
            raise

    async def fast_fallback(system, user, images, look_png):
        await asyncio.sleep(0.5)
        return "<h1>Backup</h1>"

    monkeypatch.setenv("SCREEN_HEDGE_AFTER_S", "0.05")
    screen = hedging_screen(tmp_path, monkeypatch, model_call=slow_teardown_primary,
                            fallback_call=fast_fallback)
    task = asyncio.create_task(screen._call_model("System", "Lesson", kind="look"))
    await asyncio.sleep(0.3)  # the secondary won; loser teardown in flight
    started = _time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=SCREEN_LOSER_CLEANUP_BOUND_S + 3.0)
    assert _time.monotonic() - started < SCREEN_LOSER_CLEANUP_BOUND_S + 3.0
    await screen.aclose()
    lingering = [t.get_name() for t in asyncio.all_tasks()
                 if t.get_name().startswith("screen-hedge-")]
    assert lingering == []
    # No page was served after the caller went away: the cancelled call counts
    # nothing as a win.
    assert screen.screen_stats_summary()["screen_calls_total"] == 0
    await screen.aclose()
