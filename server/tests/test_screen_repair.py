"""What the look pass and the lint retry actually did, per page and per session.

We keep server-side rendering and the vision ``look`` pass because letting the
model see what it rendered may catch a visual bug or a leaked answer before a
child does. Whether that is still true is a question only months of real
sessions can answer, and the only numbers we had were call counts by kind:
a ``look`` call that timed out, one that said "OK" and one that rewrote the
page all counted the same.

These tests pin the per-page outcome words (``repair.look_outcome`` /
``repair.retry_outcome`` in meta.json and the debug log) and the per-session
counts that reach PostHog, for every branch of the repair flow.
"""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from open_tutor.analytics import summarize_screen_repairs
from open_tutor.screen import Screen

DENSE = {"kind": "dense", "msg": "text is only 14.75px on this screen (minimum 16px). "
                                 "Keep one teaching step and one main visual; cut text or split the page."}
HEADING = {"kind": "heading", "where": "<h1>",
           "msg": "title takes more than two lines. Use a short title of two to four words; "
                  "put the question below it."}


@pytest.fixture(autouse=True)
def every_page_is_visual(monkeypatch):
    """These tests pin what the look pass does once it runs. Since 2026-11-27 a
    clean page with nothing spatial on it skips the look (``skipped_simple``,
    see test_screen_look_gate.py), so the short test pages here count as visual."""
    monkeypatch.setattr("open_tutor.screen.page_needs_visual_look", lambda body: True)


def make_screen(tmp_path, **kwargs):
    kwargs.setdefault("model_call", AsyncMock(return_value="<h1>Hej</h1>"))
    kwargs.setdefault("render_page", AsyncMock(return_value=(b"PNG", [])))
    return Screen({"name": "Test", "grade": 4}, tmp_path / "pages", **kwargs)


def job_meta(tmp_path, job="s1"):
    return json.loads((tmp_path / "pages" / job / "meta.json").read_text())


def outcomes(tmp_path, job="s1"):
    repair = job_meta(tmp_path, job)["repair"]
    return repair["look_outcome"], repair["retry_outcome"]


async def run_page(screen, ask="En sida om bråk"):
    screen.ask(ask)
    await screen.wait_idle()


# ---- look outcomes ---------------------------------------------------------


async def test_a_look_that_changes_nothing_is_recorded_as_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")

    async def model(system, user, images, look_png):
        return "<h1>Delar</h1>" if look_png is None else "OK"

    screen = make_screen(tmp_path, model_call=model)
    await run_page(screen)
    assert outcomes(tmp_path) == ("ok", "not_needed")
    await screen.aclose()


async def test_a_look_that_rewrites_the_page_is_recorded_as_fixed(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")

    async def model(system, user, images, look_png):
        return "<h1>Delar</h1><p>Mer.</p>" if look_png is not None else "<h1>Delar</h1>"

    screen = make_screen(tmp_path, model_call=model)
    await run_page(screen)
    look, retry = outcomes(tmp_path)
    assert look == "fixed" and retry == "not_needed"
    assert job_meta(tmp_path)["repair"]["look_fix"] is True
    assert job_meta(tmp_path)["look_s"] >= 0
    await screen.aclose()


async def test_a_look_pass_switched_off_is_recorded_as_off(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    screen = make_screen(tmp_path)
    await run_page(screen)
    assert outcomes(tmp_path) == ("off", "not_needed")
    await screen.aclose()


async def test_actionable_lint_skips_the_look_and_the_retry_takes_over(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    renders = []

    async def render(body, patch, history, w, h):
        renders.append(body)
        return (b"PNG1", [DENSE]) if len(renders) == 1 else (b"PNG2", [])

    async def model(system, user, images, look_png):
        assert look_png is None, "the look pass must not run on a page with known lint"
        return "<h1>Delar</h1><p>Kort.</p>" if "still reports" in user else "<h1>Delar</h1>"

    screen = make_screen(tmp_path, model_call=model, render_page=render,
                         get_pane_size=lambda: (370, 610))
    await run_page(screen)
    assert outcomes(tmp_path) == ("skipped_lint", "applied")
    await screen.aclose()


async def test_a_look_with_no_room_in_the_page_target_is_recorded_as_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    monkeypatch.setattr("open_tutor.screen.PAGE_TARGET_S", 0.05, raising=False)
    monkeypatch.setattr("open_tutor.screen.VISUAL_LOOK_TARGET_S", 0.05, raising=False)
    monkeypatch.setattr("open_tutor.screen.FINAL_RENDER_RESERVE_S", 0.01)
    monkeypatch.setattr("open_tutor.screen.MIN_OPTIONAL_STEP_S", 0.005)

    async def model(system, user, images, look_png):
        await asyncio.sleep(0.04)
        return "<h1>Delar</h1>"

    screen = make_screen(tmp_path, model_call=model, timeout=1.0)
    await run_page(screen)
    assert outcomes(tmp_path) == ("skipped_budget", "not_needed")
    await screen.aclose()


async def test_a_look_that_times_out_is_told_apart_from_one_that_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    monkeypatch.setattr("open_tutor.screen.OPTIONAL_STEP_LIMIT_S", 0.02, raising=False)
    monkeypatch.setattr("open_tutor.screen.MIN_OPTIONAL_STEP_S", 0)
    monkeypatch.setattr("open_tutor.screen.FINAL_RENDER_RESERVE_S", 0.01)

    async def slow(system, user, images, look_png):
        if look_png is not None:
            await asyncio.sleep(0.2)
            return "OK"
        return "<h1>Delar</h1>"

    screen = make_screen(tmp_path, model_call=slow, timeout=1.0)
    await run_page(screen)
    assert outcomes(tmp_path) == ("timed_out", "not_needed")
    await screen.aclose()


async def test_a_look_that_raises_is_recorded_as_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")

    async def model(system, user, images, look_png):
        if look_png is None:
            return "<h1>Delar</h1>"
        raise RuntimeError("look broke")

    screen = make_screen(tmp_path, model_call=model)
    await run_page(screen)
    assert outcomes(tmp_path) == ("failed", "not_needed")
    await screen.aclose()


async def test_a_look_fix_that_cannot_be_rendered_is_recorded_as_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    monkeypatch.setattr("open_tutor.screen.MIN_OPTIONAL_STEP_S", 0)
    monkeypatch.setattr("open_tutor.screen.FINAL_RENDER_RESERVE_S", 0.01)

    async def model(system, user, images, look_png):
        return "<h1>Förbättrad</h1>" if look_png is not None else "<h1>Första</h1>"

    async def render(body, patch, history, w, h):
        if "Förbättrad" in body:
            await asyncio.sleep(30)
        return b"PNG", []

    screen = make_screen(tmp_path, model_call=model, render_page=render, timeout=0.5)
    delivered = []
    screen.on_page = delivered.append
    await run_page(screen)
    assert delivered[0].body == "<h1>Första</h1>"
    assert outcomes(tmp_path) == ("fix_dropped", "not_needed")
    await screen.aclose()


# ---- retry outcomes --------------------------------------------------------


async def test_lint_left_after_a_look_fix_gets_no_second_correction(tmp_path, monkeypatch):
    """One correction per page: a page the look pass already rewrote does not
    also buy a lint retry, and the record says why."""
    monkeypatch.setenv("SCREEN_LOOK", "1")

    async def model(system, user, images, look_png):
        return "<h1>Ändrad</h1>" if look_png else "<h1>Först</h1>"

    async def render(body, patch, history, w, h):
        return b"PNG", [DENSE] if "Ändrad" in body else []

    screen = make_screen(tmp_path, model_call=model, render_page=render,
                         get_pane_size=lambda: (370, 610))
    await run_page(screen)
    assert outcomes(tmp_path) == ("fixed", "after_look")
    await screen.aclose()


async def test_a_retry_switched_off_is_recorded_as_off(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    monkeypatch.setenv("SCREEN_LINT_RETRY", "0")
    screen = make_screen(tmp_path, render_page=AsyncMock(return_value=(b"PNG", [DENSE])),
                         get_pane_size=lambda: (370, 610))
    delivered = []
    screen.on_page = delivered.append
    await run_page(screen)
    assert outcomes(tmp_path) == ("off", "off")
    assert delivered[0].residual_issues  # the page still ships with its lint
    await screen.aclose()


async def test_a_retry_that_returns_the_same_page_is_recorded_as_no_change(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")

    async def model(system, user, images, look_png):
        return "<h1>Delar</h1>"  # the correction repeats the page it was given

    screen = make_screen(tmp_path, model_call=model,
                         render_page=AsyncMock(return_value=(b"PNG", [DENSE])),
                         get_pane_size=lambda: (370, 610))
    await run_page(screen)
    assert outcomes(tmp_path) == ("off", "no_change")
    assert job_meta(tmp_path)["repair"]["retry"] is True
    await screen.aclose()


async def test_a_retry_that_lints_worse_is_recorded_as_worse(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    renders = []

    async def render(body, patch, history, w, h):
        renders.append(body)
        return (b"PNG1", [DENSE]) if len(renders) == 1 else (b"PNG2", [DENSE, HEADING])

    async def model(system, user, images, look_png):
        return "<h1>Mycket längre rubrik</h1>" if "still reports" in user else "<h1>Delar</h1>"

    screen = make_screen(tmp_path, model_call=model, render_page=render,
                         get_pane_size=lambda: (370, 610))
    delivered = []
    screen.on_page = delivered.append
    await run_page(screen)
    assert delivered[0].png == b"PNG1"
    assert outcomes(tmp_path) == ("off", "worse")
    await screen.aclose()


async def test_a_retry_that_times_out_is_recorded_as_timed_out(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")

    async def model(system, user, images, look_png):
        if "still reports these problems" in user:
            await asyncio.sleep(30)
            return "<h1>För sent</h1>"
        return "<h1>Delar</h1>"

    screen = make_screen(tmp_path, model_call=model,
                         render_page=AsyncMock(return_value=(b"PNG", [HEADING])),
                         timeout=7.0)
    await run_page(screen)
    assert outcomes(tmp_path) == ("off", "timed_out")
    await screen.aclose()


async def test_a_retry_with_no_time_left_is_recorded_as_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")

    async def model(system, user, images, look_png):
        return "<h1>Delar</h1>"

    screen = make_screen(tmp_path, model_call=model,
                         render_page=AsyncMock(return_value=(b"PNG", [DENSE])),
                         get_pane_size=lambda: (370, 610), timeout=4.0)
    await run_page(screen)
    assert outcomes(tmp_path) == ("off", "skipped_budget")
    await screen.aclose()


async def test_advisory_lint_alone_never_counts_as_needing_a_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    advisory = [{"kind": "slow", "msg": "still loading libraries, map data and fonts"},
                {"kind": "image", "msg": "image has no credit (källa)"}]

    async def model(system, user, images, look_png):
        return "<h1>Delar</h1>" if look_png is None else "OK"

    screen = make_screen(tmp_path, model_call=model,
                         render_page=AsyncMock(return_value=(b"PNG", advisory)))
    await run_page(screen)
    assert outcomes(tmp_path) == ("ok", "not_needed")
    await screen.aclose()


async def test_the_outcomes_also_reach_the_debug_trail(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    recorded = []
    monkeypatch.setattr("open_tutor.debug_log.record_active",
                        lambda kind, data: recorded.append((kind, data)))

    async def model(system, user, images, look_png):
        return "<h1>Delar</h1>" if look_png is None else "OK"

    screen = make_screen(tmp_path, model_call=model)
    await run_page(screen)
    page = next(data for kind, data in recorded if kind == "screen_page")
    assert page["look_outcome"] == "ok" and page["retry_outcome"] == "not_needed"
    await screen.aclose()


# ---- the per-session summary ----------------------------------------------


def test_the_repair_summary_counts_outcomes_and_times():
    summary = summarize_screen_repairs([
        {"look": "fixed", "retry": "not_needed", "look_s": 3.0, "retry_s": None,
         "residual_lint": 0},
        {"look": "ok", "retry": "not_needed", "look_s": 2.0, "retry_s": None,
         "residual_lint": 0},
        {"look": "skipped_lint", "retry": "applied", "look_s": None, "retry_s": 4.0,
         "residual_lint": 0},
        {"look": "timed_out", "retry": "not_needed", "look_s": 5.0, "retry_s": None,
         "residual_lint": 2},
    ])
    assert summary["pages"] == 4
    assert summary["look"] == {"fixed": 1, "ok": 1, "skipped_lint": 1, "timed_out": 1}
    assert summary["retry"] == {"applied": 1, "not_needed": 3}
    assert summary["look_s"] == {"median": 3.0, "max": 5.0}
    assert summary["retry_s"] == {"median": 4.0, "max": 4.0}
    assert summary["pages_with_residual_lint"] == 1


def test_an_empty_repair_summary_is_all_zeroes():
    assert summarize_screen_repairs([]) == summarize_screen_repairs(None) == {
        "pages": 0, "look": {}, "retry": {}, "look_s": {}, "retry_s": {},
        "pages_with_residual_lint": 0}


def test_a_record_with_no_outcome_words_is_still_counted():
    """Defensive: a record written by an older worker must not lose the page."""
    summary = summarize_screen_repairs([{"residual_lint": 0}])
    assert summary["pages"] == 1 and summary["look"] == {"?": 1} and summary["retry"] == {"?": 1}


async def test_the_session_summary_carries_the_look_and_retry_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")

    async def model(system, user, images, look_png):
        return "<h1>Delar</h1>" if look_png is None else "OK"

    screen = make_screen(tmp_path, model_call=model)
    assert screen.screen_stats_summary()["screen_pages_total"] == 0
    await run_page(screen)
    await run_page(screen, "En annan sida")

    summary = screen.screen_stats_summary()
    assert summary["screen_pages_total"] == 2
    assert summary["screen_look"] == {"ok": 2}
    assert summary["screen_retry"] == {"not_needed": 2}
    assert summary["screen_look_s"]["max"] >= 0
    assert summary["screen_pages_with_residual_lint"] == 0
    # Still counts and timings only: no page, ask or child's words.
    assert "Delar" not in json.dumps(summary)
    await screen.aclose()


async def test_a_page_the_look_never_judged_contributes_no_look_time(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    screen = make_screen(tmp_path)
    await run_page(screen)
    summary = screen.screen_stats_summary()
    assert summary["screen_look"] == {"off": 1}
    assert summary["screen_look_s"] == {}  # nothing ran, so nothing to average
    await screen.aclose()


@pytest.mark.parametrize("key", ["screen_pages_total", "screen_look", "screen_retry",
                                 "screen_look_s", "screen_retry_s",
                                 "screen_pages_with_residual_lint"])
async def test_every_repair_key_is_in_the_session_summary(tmp_path, key):
    screen = make_screen(tmp_path)
    assert key in screen.screen_stats_summary()
    await screen.aclose()
