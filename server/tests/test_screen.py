"""Smart Screen server half: classifier, job flow, queueing, tool surface."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from livekit.agents.llm.tool_context import find_function_tools

from open_tutor.agent import SmartTutor
from open_tutor.board import PageItem, board_item
from open_tutor.prompt import instructions
from open_tutor.screen import (
    PatchResult,
    PageResult,
    Screen,
    classify_answer,
    page_title,
    session_pages_dir,
    strip_fences,
)


def tool_names(cls):
    return {t.info.name for t in find_function_tools(cls)}


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


# ---- classifier ------------------------------------------------------------


def test_patch_answers_hold_ot_patch_elements():
    assert classify_answer('<ot-patch target="vag">x</ot-patch>') == "patch"
    assert classify_answer('  <ot-patch target="graf" do="append"><ot-fn>x</ot-fn></ot-patch>\n') == "patch"


def test_page_answers_are_plain_bodies():
    assert classify_answer("<h1>Klockan</h1><p>Text.</p>") == "page"
    assert classify_answer("") == "page"


def test_fences_come_off_before_classifying():
    assert strip_fences("```html\n<h1>Hej</h1>\n```").strip() == "<h1>Hej</h1>"
    assert classify_answer(strip_fences("```html\n<h1>Hej</h1>\n```")) == "page"


def test_page_title_comes_from_the_first_heading():
    assert page_title("<h1>Klockan halv sju</h1><p>x</p>", "p9") == "Klockan halv sju"
    assert page_title("<p>no heading</p>", "p9") == "p9"


# ---- page job flow ---------------------------------------------------------


async def test_page_job_saves_everything_and_stays_invisible(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    seen = {}

    async def model(system, user, images, look_png):
        seen.update(system=system, user=user, look=look_png)
        return "<h1>Klockan</h1><p>Halv sju.</p>"

    delivered = {}

    async def render(body, patch, history, w, h):
        seen.update(body=body, patch=patch, size=(w, h))
        return b"PNG", []

    screen = make_screen(tmp_path, model_call=model, render_page=render)
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.add_turn("child", "Vad är klockan?")
    screen.add_turn("tutor", "Vi tittar på klockan.")
    screen.add_homework("foto av klockan", ["data:image/jpeg;base64,AAA"])
    job = screen.ask("En sida om klockan halv sju")
    assert job.startswith("s")
    await screen.wait_idle()

    assert "page" in delivered and isinstance(delivered["page"].page_id, str)
    page = delivered["page"]
    assert page.page_id == "p1" and page.title == "Klockan"
    assert screen.visible_id is None  # invisible until show_page
    assert "Räven" in seen["system"] and len(seen["system"]) > 4000  # static prefix
    assert "Vad är klockan?" in seen["user"] and "klockan halv sju" in seen["user"]
    assert "foto av klockan" in seen["user"] and seen["look"] is None
    assert seen["body"] == "<h1>Klockan</h1><p>Halv sju.</p>" and seen["patch"] is None
    assert seen["size"] == (1366, 768)
    job_dir = tmp_path / "pages" / job
    assert (job_dir / "ask.txt").read_text() == "En sida om klockan halv sju"
    assert (job_dir / "page.html").read_text() == "<h1>Klockan</h1><p>Halv sju.</p>"
    assert (job_dir / "shot.png").read_bytes() == b"PNG"
    assert json.loads((job_dir / "meta.json").read_text())["kind"] == "page"
    await screen.aclose()


async def test_look_pass_repairs_a_new_page(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    bodies = []

    async def render(body, patch, history, w, h):
        bodies.append(body)
        return b"PNG%d" % len(bodies), []

    async def model(system, user, images, look_png):
        if look_png is None:
            return "<h1>Klockan</h1>"
        assert look_png == b"PNG1"  # the model sees its own render
        return "<h1>Klockan</h1><p>Halv sju.</p>"

    delivered = {}
    screen = make_screen(tmp_path, model_call=model, render_page=render)
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om klockan")
    await screen.wait_idle()

    assert bodies == ["<h1>Klockan</h1>", "<h1>Klockan</h1><p>Halv sju.</p>"]
    assert delivered["page"].body == "<h1>Klockan</h1><p>Halv sju.</p>"
    assert delivered["page"].look_s > 0
    await screen.aclose()


async def test_look_pass_ok_keeps_the_first_render(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    calls = []

    async def model(system, user, images, look_png):
        calls.append(look_png)
        return "<h1>Klockan</h1>" if look_png is None else "OK"

    rendered = []

    async def render(body, patch, history, w, h):
        rendered.append(body)
        return b"PNG", []

    delivered = {}
    screen = make_screen(tmp_path, model_call=model, render_page=render)
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om klockan")
    await screen.wait_idle()

    assert rendered == ["<h1>Klockan</h1>"] and calls[1] is not None
    await screen.aclose()


# ---- patch job flow --------------------------------------------------------


async def ready_page(tmp_path, monkeypatch):
    """One finished page job; returns the screen with p1 visible."""
    monkeypatch.setenv("SCREEN_LOOK", "0")
    screen = make_screen(tmp_path)
    pages = {}
    screen.on_page = lambda p: pages.setdefault("page", p)
    screen.ask("En sida om klockan")
    await screen.wait_idle()
    screen.mark_visible(pages["page"].page_id)
    return screen


async def test_patch_applies_to_the_visible_page(tmp_path, monkeypatch):
    screen = await ready_page(tmp_path, monkeypatch)
    patched = {}

    async def model(system, user, images, look_png):
        return '<ot-patch target="klocka"><ot-clock time="7:30"></ot-clock></ot-patch>'

    rendered = {}

    async def render(body, patch, history, w, h):
        rendered.update(body=body, patch=patch)
        return b"PATCHED", ["crowded"]

    screen._model_call = model
    screen._render_page = render
    screen.on_patch = lambda p: patched.setdefault("patch", p)
    screen.ask("Visa halv sju istället")
    await screen.wait_idle()

    assert patched["patch"].page_id == "p1"
    assert patched["patch"].png == b"PATCHED"
    assert 'target="klocka"' in rendered["patch"]
    assert (tmp_path / "pages" / "s2" / "patch.html").read_text() == rendered["patch"]
    assert (tmp_path / "pages" / "s2" / "patched.png").read_bytes() == b"PATCHED"
    assert screen.visible_patches == {"p1": [rendered["patch"]]}
    await screen.aclose()


async def test_patch_with_no_visible_page_fails_quietly(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    failures = []
    screen = make_screen(
        tmp_path,
        model_call=AsyncMock(return_value='<ot-patch target="x">y</ot-patch>'),
    )
    screen.on_failure = failures.append
    screen.ask("Ändra sidan")
    await screen.wait_idle()

    assert len(failures) == 1 and "Explain in words" in failures[0]
    assert screen.pages == {}
    await screen.aclose()


# ---- failures --------------------------------------------------------------


async def test_model_failure_reaches_the_tutor_quietly(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")

    async def boom(system, user, images, look_png):
        raise TimeoutError("screen model silent")

    failures, pages = [], {}
    screen = make_screen(tmp_path, model_call=boom)
    screen.on_page = lambda p: pages.setdefault("page", p)
    screen.on_failure = failures.append
    screen.ask("En sida om klockan")
    await screen.wait_idle()

    assert pages == {} and len(failures) == 1 and "Explain in words" in failures[0]
    await screen.aclose()


async def test_empty_answer_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    failures = []
    screen = make_screen(tmp_path, model_call=AsyncMock(return_value="  \n "))
    screen.on_failure = failures.append
    screen.ask("En sida om klockan")
    await screen.wait_idle()

    assert len(failures) == 1
    await screen.aclose()


async def test_slow_job_times_out(tmp_path):
    async def slow(system, user, images, look_png):
        await asyncio.sleep(5)
        return "<h1>Sent</h1>"

    failures = []
    screen = make_screen(tmp_path, model_call=slow, timeout=0.05)
    screen.on_failure = failures.append
    screen.ask("En sida om klockan")
    await screen.wait_idle()

    assert len(failures) == 1 and "too long" in failures[0]
    await screen.aclose()


# ---- queueing --------------------------------------------------------------


async def test_latest_ask_wins_while_a_job_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def model(system, user, images, look_png):
        calls.append(user.split("Tutor: ")[1].split("\n")[0])
        if len(calls) == 1:
            entered.set()
            await release.wait()
        return "<h1>Sida</h1>"

    screen = make_screen(tmp_path, model_call=model,
                         render_page=AsyncMock(return_value=(b"PNG", [])))
    done = []
    screen.on_page = lambda page: done.append(page)
    screen.ask("första")
    await entered.wait()
    screen.ask("mellan")
    screen.ask("sista")
    release.set()
    await screen.wait_idle()

    assert calls == ["första", "sista"]  # the waiting ask was replaced
    assert [p.job_id for p in done] == ["s1", "s3"]
    await screen.aclose()


# ---- pane, look and lint repair --------------------------------------------

DENSE = {"kind": "dense", "msg": "text is only 14.75px on this screen (minimum 16px). "
                                 "Keep one teaching step and one main visual; cut text or split the page."}
HEADING = {"kind": "heading", "where": "<h1>",
           "msg": "title takes more than two lines. Use a short title of two to four words; "
                  "put the question below it."}


def job_meta(tmp_path, job="s1"):
    return json.loads((tmp_path / "pages" / job / "meta.json").read_text())


async def test_page_request_states_the_narrow_pane_and_the_layout_rule(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    users = []

    async def model(system, user, images, look_png):
        users.append(user)
        return "<h1>Delar</h1>"

    screen = make_screen(tmp_path, model_call=model, get_pane_size=lambda: (370, 610))
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert "Pane: 370×610 px" in users[0] and "narrow" in users[0]
    assert "one reading column" in users[0] and "short title" in users[0]
    assert "no side panel" in users[0]
    await screen.aclose()


async def test_wide_pane_gets_the_size_without_the_narrow_rule(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    users = []

    async def model(system, user, images, look_png):
        users.append(user)
        return "<h1>Delar</h1>"

    screen = make_screen(tmp_path, model_call=model, get_pane_size=lambda: (1000, 700))
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert "Pane: 1000×700 px" in users[0]
    assert "one reading column" not in users[0] and "narrow" not in users[0]
    await screen.aclose()


async def test_look_sees_the_source_the_pane_and_the_childs_question(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    looks = []
    source = "<h1>Delar</h1><p>Hur många åttondelar är 3/4?</p>"

    async def model(system, user, images, look_png):
        if look_png is None:
            return source
        looks.append(user)
        return "OK"

    screen = make_screen(tmp_path, model_call=model, get_pane_size=lambda: (370, 558))
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    look = looks[0]
    assert source in look  # the look pass finally gets the page it is repairing
    assert "Pane: 370×558 px" in look and "En sida om bråk" in look
    assert "number, mark, label" in look
    assert "child's question" in look
    assert "Lint does not detect answer leaks" in look
    await screen.aclose()


ACTIONABLE = [
    DENSE,
    HEADING,
    {"kind": "overflow", "msg": "page does not fit even at 14px text; it was shrunk to 88%. "
                                 "Cut content or split the page."},
    {"kind": "crowded", "msg": "does not fit", "where": '<ot-graph id="graf">'},
    {"kind": "math", "msg": "KaTeX error: \\frac"},
    {"kind": "tag", "msg": "unknown tag <ot-bla>", "where": "<ot-bla>"},
    {"kind": "id", "msg": 'duplicate id "svar"', "where": '<ot-answer id="svar">'},
    "patch failed: Error",
]


@pytest.mark.parametrize("lint", ACTIONABLE)
async def test_actionable_lint_buys_exactly_one_retry(tmp_path, monkeypatch, lint):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    writes, renders = [], []

    async def render(body, patch, history, w, h):
        renders.append(body)
        return (b"PNG1", [lint]) if len(renders) == 1 else (b"PNG2", [])

    async def model(system, user, images, look_png):
        writes.append((look_png, user))
        if look_png is not None:
            return "OK"
        if "still reports these problems" in user:
            return "<h1>Delar</h1><p>En fråga.</p>"
        return "<h1>Delar</h1><p>Lång text.</p>"

    delivered = {}
    screen = make_screen(tmp_path, model_call=model, render_page=render,
                         get_pane_size=lambda: (370, 610))
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert [w[0] for w in writes] == [None, None]  # page, one direct lint correction
    assert delivered["page"].body == "<h1>Delar</h1><p>En fråga.</p>"
    assert delivered["page"].png == b"PNG2" and delivered["page"].residual_issues == []
    meta = job_meta(tmp_path)
    assert meta["repair"]["retry"] is True and meta["repair"]["retry_applied"] is True
    assert meta["residual_lint"] == [] and "retry_s" in meta
    await screen.aclose()


async def test_retry_carries_the_source_the_pane_and_the_exact_lint(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    writes = []
    source = "<h1>Delar</h1><p>Lång text.</p>"

    async def model(system, user, images, look_png):
        writes.append((look_png, user))
        if look_png is not None:
            return "OK"
        if "still reports these problems" in user:
            return "<h1>Delar</h1>"
        return source

    screen = make_screen(tmp_path, model_call=model,
                         render_page=AsyncMock(return_value=(b"PNG", [DENSE])),
                         get_pane_size=lambda: (370, 558))
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    retry = writes[1][1]
    assert source in retry and "En sida om bråk" in retry and "Pane: 370×558 px" in retry
    assert DENSE["msg"] in retry  # exact shell text, not a paraphrase
    await screen.aclose()


async def test_a_valid_page_gets_no_extra_look_or_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    calls, renders = [], []

    async def model(system, user, images, look_png):
        calls.append(look_png)
        return "<h1>Delar</h1>" if look_png is None else "OK"

    async def render(body, patch, history, w, h):
        renders.append(body)
        return b"PNG", []

    delivered = {}
    screen = make_screen(tmp_path, model_call=model, render_page=render)
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert len(calls) == 2 and len(renders) == 1  # page, one look, no retry
    meta = job_meta(tmp_path)
    assert meta["repair"]["retry"] is False and meta["residual_lint"] == []
    await screen.aclose()


async def test_clean_page_skips_look_when_the_soft_budget_is_used(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    monkeypatch.setattr("open_tutor.screen.PAGE_TARGET_S", 0.05, raising=False)
    monkeypatch.setattr("open_tutor.screen.VISUAL_LOOK_TARGET_S", 0.05, raising=False)
    monkeypatch.setattr("open_tutor.screen.FINAL_RENDER_RESERVE_S", 0.01)
    monkeypatch.setattr("open_tutor.screen.MIN_OPTIONAL_STEP_S", 0.005)
    calls, delivered = [], []

    async def model(system, user, images, look_png):
        calls.append(look_png)
        if look_png is None:
            await asyncio.sleep(0.04)
            return "<h1>Delar</h1>"
        return "OK"

    screen = make_screen(tmp_path, model_call=model, timeout=1.0)
    screen.on_page = delivered.append
    screen.ask("En sida om bråk")
    await screen.wait_idle()
    assert len(calls) == 1 and delivered[0].body == "<h1>Delar</h1>"
    assert any("target" in note for note in job_meta(tmp_path)["repair"]["notes"])
    await screen.aclose()


async def test_a_slow_look_is_capped_independently_of_the_job_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    monkeypatch.setattr("open_tutor.screen.OPTIONAL_STEP_LIMIT_S", 0.02, raising=False)
    monkeypatch.setattr("open_tutor.screen.MIN_OPTIONAL_STEP_S", 0)
    monkeypatch.setattr("open_tutor.screen.FINAL_RENDER_RESERVE_S", 0.01)
    delivered = []

    async def model(system, user, images, look_png):
        if look_png is not None:
            await asyncio.sleep(0.2)
            return "OK"
        return "<h1>Delar</h1>"

    screen = make_screen(tmp_path, model_call=model, timeout=1.0)
    screen.on_page = delivered.append
    screen.ask("En sida om bråk")
    await screen.wait_idle()
    assert delivered[0].total_s < 0.1
    assert "look pass timed out" in job_meta(tmp_path)["repair"]["notes"]
    await screen.aclose()


async def test_a_look_fix_does_not_start_a_second_correction(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    calls, delivered = [], []

    async def model(system, user, images, look_png):
        calls.append(look_png)
        return "<h1>Ändrad</h1>" if look_png else "<h1>Först</h1>"

    async def render(body, patch, history, w, h):
        return b"PNG", [DENSE] if "Ändrad" in body else []

    screen = make_screen(tmp_path, model_call=model, render_page=render)
    screen.on_page = delivered.append
    screen.ask("En sida om bråk")
    await screen.wait_idle()
    assert calls == [None, b"PNG"]
    assert delivered[0].residual_issues
    assert not job_meta(tmp_path)["repair"]["retry"]
    await screen.aclose()


async def test_advisory_lint_never_buys_a_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    calls = []
    advisory = [{"kind": "slow", "msg": "still loading libraries, map data and fonts"},
                {"kind": "image", "msg": "image has no credit (källa)"}]

    async def model(system, user, images, look_png):
        calls.append(look_png)
        return "<h1>Delar</h1>" if look_png is None else "OK"

    screen = make_screen(tmp_path, model_call=model,
                         render_page=AsyncMock(return_value=(b"PNG", advisory)))
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert len(calls) == 2  # no retry for slow loading or a missing image credit
    assert job_meta(tmp_path)["residual_lint"] == []
    await screen.aclose()


async def test_a_short_job_delivers_with_residual_lint(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    calls = []

    async def model(system, user, images, look_png):
        calls.append(look_png)
        return "<h1>Delar</h1>"

    delivered = {}
    screen = make_screen(tmp_path, model_call=model,
                         render_page=AsyncMock(return_value=(b"PNG", [DENSE])),
                         get_pane_size=lambda: (370, 610), timeout=4.0)
    screen.on_page = lambda p: delivered.setdefault("page", p)
    caplog.set_level("WARNING", logger="open-tutor")
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert len(calls) == 1  # no time for look or retry, so the page still ships
    assert delivered["page"].body == "<h1>Delar</h1>"
    assert delivered["page"].residual_issues == [f"dense: {DENSE['msg']}"]
    meta = job_meta(tmp_path)
    assert meta["residual_lint"] == [f"dense: {DENSE['msg']}"]
    assert any("skipped: no time left" in note for note in meta["repair"]["notes"])
    assert "delivered with residual lint" in caplog.text
    await screen.aclose()


async def test_a_failed_look_pass_still_delivers_the_page(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    delivered = {}

    async def model(system, user, images, look_png):
        if look_png is None:
            return "<h1>Delar</h1>"
        raise RuntimeError("look broke")

    screen = make_screen(tmp_path, model_call=model)
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert delivered["page"].body == "<h1>Delar</h1>"
    assert "look pass failed: RuntimeError" in job_meta(tmp_path)["repair"]["notes"]
    await screen.aclose()


async def test_a_slow_repair_render_keeps_the_page_before_the_job_deadline(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    monkeypatch.setattr("open_tutor.screen.MIN_OPTIONAL_STEP_S", 0)
    monkeypatch.setattr("open_tutor.screen.FINAL_RENDER_RESERVE_S", 0.01)
    delivered, failures = [], []

    async def model(system, user, images, look_png):
        return "<h1>Förbättrad</h1>" if look_png is not None else "<h1>Första sidan</h1>"

    async def render(body, patch, history, w, h):
        if "Förbättrad" in body:
            await asyncio.sleep(30)
        return b"PNG", []

    screen = make_screen(tmp_path, model_call=model, render_page=render, timeout=0.5)
    screen.on_page = delivered.append
    screen.on_failure = failures.append
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert not failures
    assert delivered[0].body == "<h1>Första sidan</h1>"
    assert any("render timed out" in note for note in job_meta(tmp_path)["repair"]["notes"])
    assert delivered[0].total_s < 0.5
    await screen.aclose()


async def test_a_timed_out_retry_still_delivers_the_page(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    delivered = {}

    async def model(system, user, images, look_png):
        if "still reports these problems" in user:
            await asyncio.sleep(30)
            return "<h1>För sent</h1>"
        return "<h1>Delar</h1>" if look_png is None else "OK"

    screen = make_screen(tmp_path, model_call=model,
                         render_page=AsyncMock(return_value=(b"PNG", [HEADING])),
                         timeout=7.0)
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    page = delivered["page"]
    assert page.body == "<h1>Delar</h1>" and page.png == b"PNG"
    assert page.residual_issues == [f"heading: {HEADING['msg']} ({HEADING['where']})"]
    meta = job_meta(tmp_path)
    assert "lint retry timed out" in meta["repair"]["notes"]
    assert meta["repair"]["retry"] is True and meta["repair"]["retry_applied"] is False
    await screen.aclose()


async def test_a_retry_that_makes_lint_worse_is_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    renders = []

    async def render(body, patch, history, w, h):
        renders.append(body)
        return (b"PNG1", [DENSE]) if len(renders) == 1 else (b"PNG2", [DENSE, HEADING])

    async def model(system, user, images, look_png):
        if look_png is not None:
            return "OK"
        return "<h1>Delar</h1>" if "still reports" not in user else "<h1>Mycket längre rubrik</h1>"

    delivered = {}
    screen = make_screen(tmp_path, model_call=model, render_page=render)
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert delivered["page"].body == "<h1>Delar</h1>" and delivered["page"].png == b"PNG1"
    assert any("made lint worse" in note for note in job_meta(tmp_path)["repair"]["notes"])
    await screen.aclose()


@pytest.mark.parametrize("reply", ["OK", '<ot-patch target="steg">x</ot-patch>'])
async def test_retry_does_not_replace_a_page_with_an_acknowledgement_or_patch(tmp_path, reply):
    screen = make_screen(tmp_path, model_call=AsyncMock(return_value=reply))
    assert await screen._retry_with_lint("En sida", "<h1>Bråk</h1>", ["dense: small"], 370, 610) is None
    await screen.aclose()


async def test_patch_jobs_never_use_the_lint_retry(tmp_path, monkeypatch):
    screen = await ready_page(tmp_path, monkeypatch)
    calls = []

    async def model(system, user, images, look_png):
        calls.append(user)
        return '<ot-patch target="klocka">x</ot-patch>'

    screen._model_call = model
    screen._render_page = AsyncMock(return_value=(b"PATCHED", [DENSE]))
    screen.ask("Visa halv sju")
    await screen.wait_idle()

    assert len(calls) == 1 and "still reports these problems" not in calls[0]
    await screen.aclose()


# ---- tool surface ----------------------------------------------------------


def test_a_leftover_screen_switch_is_silent_or_reported():
    """2026-11-18: TUTOR_SCREEN is gone; prod/dev env files were not edited."""
    from open_tutor.agent import screen_mode_notice

    assert screen_mode_notice({}) is None
    assert screen_mode_notice({"TUTOR_SCREEN": "smart"}) is None
    assert screen_mode_notice({"TUTOR_SCREEN": "  smart  "}) is None
    notice = screen_mode_notice({"TUTOR_SCREEN": "board"})
    assert notice and "board" in notice and "only mode" in notice


def test_the_smart_tutor_is_the_only_tutor_and_the_only_tool_surface():
    # 2026-11-18: the legacy board path is gone; the worker always runs SmartTutor.
    assert tool_names(SmartTutor) == {"ask_screen", "show_page", "reveal", "point",
                                      "screen_loading", "screen_status",
                                      "find_resources", "share_resource", "start_quiet_work",
                                      "stay_quiet", "save_note",
                                      "set_learner_name", "set_learner_grade", "switch_student"}


def test_the_single_prompt_teaches_the_six_screen_tools():
    text = instructions({"name": "Leo", "grade": 3})
    for word in ("ask_screen", "show_page", "reveal", "point",
                 "screen_loading", "screen_status"):
        assert word in text
    assert "commission_board" not in text and "edit_board" not in text
    assert "search_materials" not in text and "show_material" not in text
    assert "Never read out a hidden answer" in text
    assert "appears on the screen by itself" in text


class FakeParticipant:
    def __init__(self, reply='{"ok":true}'):
        self.calls, self.reply = [], reply

    async def perform_rpc(self, *, destination_identity, method, payload, response_timeout):
        import json as jsonlib

        self.calls.append((method, jsonlib.loads(payload)))
        return self.reply

    async def set_attributes(self, attributes):
        pass


class FakeRoom:
    def __init__(self, **kwargs):
        self.local_participant = FakeParticipant(**kwargs)


def smart_tutor(room, screen):
    tutor = SmartTutor({"name": "Leo", "grade": 7}, room, screen=screen)
    tutor.child_identity = "learner-1"
    return tutor


async def test_show_reveal_point_send_page_rpcs(tmp_path, monkeypatch):
    screen = await ready_page(tmp_path, monkeypatch)
    room = FakeRoom()
    tutor = smart_tutor(room, screen)

    result = await tutor.show_page(AsyncMock(), page_id="p1")
    assert "now visible" in result and screen.visible_id == "p1"
    method, payload = room.local_participant.calls[0]
    assert method == "board.show"
    assert payload == {"kind": "page", "id": "p1", "title": "Hej", "body": "<h1>Hej</h1>"}

    assert "visible" in await tutor.reveal(AsyncMock(), part_id="facit")
    assert "highlighted" in await tutor.point(AsyncMock(), part_id="steg-2")
    methods = [c[0] for c in room.local_participant.calls]
    assert methods == ["board.show", "board.reveal", "board.point"]
    assert room.local_participant.calls[1] == ("board.reveal", {"id": "p1", "part": "facit"})
    assert room.local_participant.calls[2] == ("board.point", {"id": "p1", "part": "steg-2"})
    await screen.aclose()


async def test_show_unknown_page_explains_in_words(tmp_path, monkeypatch):
    screen = await ready_page(tmp_path, monkeypatch)
    tutor = smart_tutor(FakeRoom(), screen)
    result = await tutor.show_page(AsyncMock(), page_id="p9")
    assert "Unknown page id" in result and "Explain in words" in result
    await screen.aclose()


async def test_reveal_without_a_visible_page_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    screen = make_screen(tmp_path)  # nothing finished, nothing shown
    tutor = smart_tutor(FakeRoom(), screen)
    assert "No page is on screen" in await tutor.reveal(AsyncMock(), part_id="facit")
    await screen.aclose()


async def test_ask_screen_returns_at_once(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    release = asyncio.Event()

    async def model(system, user, images, look_png):
        await release.wait()
        return "<h1>Sent</h1>"

    screen = make_screen(tmp_path, model_call=model)
    tutor = smart_tutor(FakeRoom(), screen)
    result = await asyncio.wait_for(
        tutor.ask_screen(AsyncMock(), ask="En sida om klockan"), timeout=2)
    assert "working on it" in result and "Do not announce a wait" in result
    release.set()
    await screen.wait_idle()
    await screen.aclose()


# ---- schema and lesson -----------------------------------------------------


def test_page_item_travels_as_a_board_item():
    item = board_item.validate_python({"kind": "page", "id": "p1",
                                       "title": "Klockan", "body": "<h1>Hej</h1>"})
    assert isinstance(item, PageItem) and item.body == "<h1>Hej</h1>"


def test_page_body_respects_the_rpc_limit():
    with pytest.raises(Exception):
        board_item.validate_python({"kind": "page", "id": "p1",
                                    "title": "t", "body": "x" * 16000})


def test_screen_records_the_lesson():
    import tempfile

    screen = Screen({"name": "Test"}, tempfile.mkdtemp())
    screen.add_turn("child", "Hej")
    screen.add_turn("tutor", "Hej hej")
    screen.add_turn("fox", "ignored")
    screen.add_homework("foto", ["data:1", "data:2"])
    screen.record_answer("p1", "svar", "42", "answer")
    assert screen.turns == [("child", "Hej"), ("tutor", "Hej hej")]
    assert screen.homework == [("foto", ["data:1", "data:2"])]
    assert screen.answers == [{"page": "p1", "part": "svar", "value": "42", "kind": "answer"}]


def test_pages_land_under_the_session_folder(tmp_path):
    pages = session_pages_dir("room-1", tmp_path / "sessions" / "room-1")
    assert pages == tmp_path / "sessions" / "room-1" / "pages" and pages.is_dir()


# ---- timing cheap wins -----------------------------------------------------


def test_system_prompt_is_byte_identical_across_calls(tmp_path):
    screen = make_screen(tmp_path)
    first = screen.system_prompt()
    second = screen.system_prompt()
    assert first == second and len(first) > 4000
    assert "Räven" in first


def test_model_spec_defaults_to_minimal_reasoning(tmp_path, monkeypatch):
    monkeypatch.delenv("SCREEN_MODEL", raising=False)
    monkeypatch.delenv("SCREEN_REASONING", raising=False)
    monkeypatch.delenv("SCREEN_API", raising=False)
    monkeypatch.delenv("SCREEN_THINKING", raising=False)
    screen = make_screen(tmp_path)
    assert screen.model_spec() == {"model": "muse-spark-1.3-contributor",
                                   "api": "responses", "reasoning": "minimal"}


def _streaming_openai(monkeypatch, handle):
    """An AsyncOpenAI on a recorded SSE transport, bypassing the shared cache."""
    import httpx
    from openai import AsyncOpenAI

    from open_tutor import http_clients

    requests = []

    def recording(request):
        requests.append(request)
        return handle(request)

    transport = httpx.MockTransport(recording)
    monkeypatch.setattr(http_clients, "shared_async_openai",
                        lambda base_url, api_key, user_agent: AsyncOpenAI(
                            api_key=api_key, base_url=base_url,
                            default_headers={"User-Agent": user_agent},
                            http_client=httpx.AsyncClient(transport=transport)))
    return requests


def _responses_sse(text, model):
    """Minimal Responses SSE: one text delta, then a completed response."""
    import httpx

    def handle(request):
        events = [
            {"type": "response.output_text.delta", "sequence_number": 3,
             "output_index": 0, "content_index": 0, "item_id": "msg_1", "delta": text},
            {"type": "response.completed", "sequence_number": 4,
             "response": {"id": "resp_test", "object": "response", "created_at": 0,
                            "model": model, "status": "completed", "output": [],
                            "tools": [], "tool_choice": "auto", "parallel_tool_calls": True,
                            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                                       "input_tokens_details": {"cached_tokens": 0},
                                       "output_tokens_details": {"reasoning_tokens": 0}}}},
        ]
        body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=body.encode())

    return handle


def _chat_sse(text, model):
    """Minimal Chat Completions SSE: one content chunk, then done."""
    import httpx

    def handle(request):
        event = {"id": "chat_1", "object": "chat.completion.chunk", "created": 0,
                 "model": model, "choices": [{"index": 0,
                     "delta": {"role": "assistant", "content": text}, "finish_reason": None}]}
        body = f"data: {json.dumps(event)}\n\n" + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=body.encode())

    return handle


@pytest.mark.parametrize("model,effort,thinking,host,path", [
    ("deepseek-v4.1-flash", "low", "", "opencode.ai", "/inference/go/openai/v1/chat/completions"),
    ("deepseek-v4.1-flash", "low", "disabled", "opencode.ai", "/inference/go/openai/v1/chat/completions"),
    ("deepseek-v4.1-flash", "low", "enabled", "opencode.ai", "/inference/go/openai/v1/chat/completions"),
    ("gemini-4-hydrogen", "low", "", "generativelanguage.googleapis.com", "/v1beta/openai/chat/completions"),
    ("gemini-4-hydrogen", "medium", "", "generativelanguage.googleapis.com", "/v1beta/openai/chat/completions"),
    ("muse-spark-1.3-contributor", "minimal", "", "opencode.ai", "/inference/go/openai/v1/responses"),
])
async def test_page_model_wire_request(tmp_path, monkeypatch, model, effort, thinking, host, path):
    """Exercise the real SDK serializer over streaming; the transport answers SSE."""

    for name, value in {"SCREEN_MODEL": model, "SCREEN_REASONING": effort,
                        "SCREEN_THINKING": thinking, "SCREEN_API": "",
                        "GEMINI_API_KEY": "test-google", "OPENCODE_GO_API_KEY": "test-go"}.items():
        monkeypatch.setenv(name, value)
    handle = _responses_sse("<h1>Hej</h1>", model) if path.endswith("responses") else _chat_sse("<h1>Hej</h1>", model)
    requests = _streaming_openai(monkeypatch, handle)
    screen = make_screen(tmp_path)
    assert await screen._default_model_call("System", "Lesson", ["data:image/png;base64,AAA"], b"PNG") == "<h1>Hej</h1>"
    assert len(requests) == 1
    request = requests[0]
    body = json.loads(request.content)
    assert request.url.host == host and request.url.path == path
    assert request.headers["authorization"] == ("Bearer test-google" if host.startswith("generative") else "Bearer test-go")
    assert ("x-opencode-session" in request.headers) == (host == "opencode.ai")
    assert body["model"] == model and body["stream"] is True
    if path.endswith("responses"):
        assert body["reasoning"] == {"effort": "minimal"}
        parts = body["input"][0]["content"]
        assert [p["type"] for p in parts] == ["input_text", "input_image", "input_image"]
    else:
        assert body.get("thinking") == ({"type": thinking} if thinking else None)
        assert body.get("reasoning_effort") == (None if thinking == "disabled" else effort)
        parts = body["messages"][1]["content"]
        assert [p["type"] for p in parts] == ["text", "image_url", "image_url"]


@pytest.mark.parametrize("settings,error", [
    ({"SCREEN_MODEL": "gemini-4-hydrogen", "SCREEN_REASONING": "minimal"}, "Gemini pages require"),
    ({"SCREEN_MODEL": "gemini-4-hydrogen", "SCREEN_API": "responses"}, "Gemini pages require"),
    ({"SCREEN_MODEL": "gemini-4-hydrogen", "SCREEN_THINKING": "disabled"}, "requires a DeepSeek"),
    ({"SCREEN_MODEL": "deepseek-v4.1-flash", "SCREEN_THINKING": "off"}, "requires a DeepSeek"),
])
def test_page_model_rejects_incompatible_settings(tmp_path, monkeypatch, settings, error):
    for name in ("SCREEN_MODEL", "SCREEN_REASONING", "SCREEN_API", "SCREEN_THINKING"):
        monkeypatch.delenv(name, raising=False)
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=error):
        make_screen(tmp_path).model_spec()


async def test_gemini_page_never_uses_go_key_as_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_MODEL", "gemini-4-hydrogen")
    monkeypatch.setenv("SCREEN_REASONING", "low")
    monkeypatch.setenv("SCREEN_API", "")
    monkeypatch.setenv("SCREEN_THINKING", "")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-go")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY is empty"):
        await make_screen(tmp_path)._default_model_call("system", "user", [], None)


async def test_patch_delivery_sends_only_latest_change_and_retains_history(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    first = '<ot-patch target="svar" do="before"><p id="mellansteg">Nästa steg</p></ot-patch>'
    second = '<ot-patch target="mellansteg"><p>Nu visar vi steget.</p></ot-patch>'
    screen = make_screen(tmp_path, model_call=AsyncMock(side_effect=['<h1>Bråk</h1><ot-answer id="svar"></ot-answer>', first, second]))
    delivered = []
    screen.on_patch = delivered.append
    screen.ask("Visa ett bråk")
    await screen.wait_idle()
    screen.mark_visible("p1")
    for ask in ("Lägg till ett steg", "Ändra steget"):
        screen.ask(ask)
        await screen.wait_idle()
    assert delivered[-1].patch == second
    assert screen.visible_patches == {"p1": [first, second]}


@pytest.mark.parametrize("issues", [
    [{"kind": "patch", "msg": 'no element with id "missing"'}],
    ["patch failed: TypeError"],
])
async def test_invalid_patch_is_saved_and_reported_to_tutor_without_partial_delivery(tmp_path, monkeypatch, issues):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    patch = '<ot-patch target="missing"><p>Fel mål</p></ot-patch><ot-patch target="svar" do="remove"></ot-patch>'
    screen = make_screen(tmp_path, model_call=AsyncMock(side_effect=['<h1>Bråk</h1><ot-answer id="svar"></ot-answer>', patch]),
                         render_page=AsyncMock(side_effect=[(b"PNG", []), (b"PNG", issues)]))
    delivered, failures = [], []
    screen.on_patch, screen.on_failure = delivered.append, failures.append
    screen.ask("Visa ett bråk")
    await screen.wait_idle()
    screen.mark_visible("p1")
    screen.ask("Visa svaret")
    await screen.wait_idle()
    assert not delivered and screen.visible_patches == {"p1": []}
    assert len(failures) == 1 and "not applied" in failures[0]
    meta = json.loads((tmp_path / "pages" / "s2" / "meta.json").read_text())
    assert meta["delivered"] is False
    assert (tmp_path / "pages" / "s2" / "patch.html").read_text() == patch


@pytest.fixture
def commons_picture(monkeypatch):
    from pathlib import Path
    from screen.tools import commons_images as commons

    fixtures = Path(__file__).resolve().parents[2] / "screen/tests/fixtures/commons-images"
    candidate = commons._result(json.loads((fixtures / "search.json").read_text())).candidates[0]
    photo = (fixtures / "colosseum.jpg").read_bytes()
    search = AsyncMock(return_value=commons.SearchResult([candidate]))
    monkeypatch.setattr(commons, "search_images", search)
    monkeypatch.setattr(commons, "download_image", AsyncMock(return_value=photo))
    return candidate, photo, search


async def test_images_are_reviewed_before_page_or_patch_reaches_renderer_or_child(tmp_path, monkeypatch, commons_picture):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    candidate, photo, search = commons_picture
    body = '<h1>Rom</h1><ot-image id="bild" query="Colosseum" alt="Valv"></ot-image>'
    patch = '<ot-patch target="bild"><ot-image query="Colosseum" alt="Byggnaden"></ot-image></ot-patch>'
    verdict = '{"accept":true,"reason":"Relevant architecture."}'
    model = AsyncMock(side_effect=[body, verdict, patch, verdict])
    screen = make_screen(tmp_path, model_call=model)
    pages, patches = [], []
    screen.on_page, screen.on_patch = pages.append, patches.append
    screen.ask("Visa valv i Rom")
    await screen.wait_idle()
    screen.mark_visible("p1")
    screen.ask("Byt bilden")
    await screen.wait_idle()
    assert len(pages) == len(patches) == 1
    for source in (pages[0].body, patches[0].patch):
        assert "query=" not in source and candidate.image_url.replace("&", "&amp;") in source
        assert "Diliff" in source and "CC BY-SA 2.5" in source
    for call in (model.call_args_list[1], model.call_args_list[3]):
        assert call.args[3] == photo and "Lesson context:" in call.args[1]
    assert search.call_count == 2
    for result in (pages[0], patches[0]):
        meta = json.loads((result.directory / "meta.json").read_text())
        assert meta["image_reviews"][0]["decision"] == "accepted" and "image_s" in meta
        assert meta["images"]["review_concurrency"] == 3  # the default, recorded
        assert (result.directory / "images.json").exists()


async def test_lint_correction_reuses_an_image_approved_in_the_same_job(tmp_path, monkeypatch, commons_picture):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    _, _, search = commons_picture
    body = '<h1>Rom</h1><ot-image id="bild" query="Colosseum" alt="Valv"></ot-image>'
    model = AsyncMock(side_effect=[body, '{"accept":true,"reason":"Relevant."}', body.replace("Rom</h1>", "Valv</h1>")])
    render = AsyncMock(side_effect=[(b"PNG", [{"kind": "dense", "msg": "shorten text"}]), (b"PNG", [])])
    screen = make_screen(tmp_path, model_call=model, render_page=render)
    pages = []
    screen.on_page = pages.append
    screen.ask("Visa valv")
    await screen.wait_idle()
    assert len(pages) == 1 and pages[0].title == "Valv"
    assert model.call_count == 3 and search.call_count == 1


async def test_image_review_timeout_delivers_text_page_and_logs_the_rejected_candidate(tmp_path, monkeypatch, commons_picture):
    import time

    monkeypatch.setenv("SCREEN_LOOK", "0")
    _, photo, _ = commons_picture

    async def model(system, user, images, picture):
        if picture == photo:
            await asyncio.Future()
        return '<h1>Rom</h1><ot-image id="bild" later query="Colosseum" alt="Valv"></ot-image>'

    screen = make_screen(tmp_path, model_call=model)
    original = screen._image_job

    def short_budget(ask, t0):
        job = original(ask, t0)
        job.deadline = time.monotonic() + 0.03
        return job

    monkeypatch.setattr(screen, "_image_job", short_budget)
    pages, failures = [], []
    screen.on_page, screen.on_failure = pages.append, failures.append
    screen.ask("Visa valv")
    await screen.wait_idle()
    assert len(pages) == 1 and not failures
    assert '<section id="bild" later="">' in pages[0].body and "ot-image" not in pages[0].body
    events = json.loads((pages[0].directory / "images.json").read_text())
    assert any(e.get("title") and "budget" in e["reason"] for e in events)


async def test_a_parallel_only_slot_keeps_its_failover_to_the_backup(tmp_path, monkeypatch, commons_picture):
    """The slot's first review hedges whichever source serves it.

    Every Parallel review was called with ``hedge=False``, so with
    ``SCREEN_IMAGES=parallel`` (or a Commons search that found nothing) the
    slot's first and only review ran without the failover: a failing primary
    left the slot with text while a healthy backup was armed."""
    import time
    from dataclasses import replace

    from screen.tools import commons_images as commons
    from screen.tools import parallel_images as parallel

    monkeypatch.setenv("SCREEN_LOOK", "0")
    monkeypatch.setenv("SCREEN_IMAGES", "parallel")
    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    monkeypatch.setenv("SCREEN_HEDGE_AFTER_S", "5")  # the primary fails before it
    candidate, photo, _ = commons_picture
    found = replace(candidate, source="parallel", image_url="https://example.com/map.jpg",
                    title="Historical map")
    monkeypatch.setattr(parallel, "search_images",
                        AsyncMock(return_value=commons.SearchResult([found])))
    monkeypatch.setattr(parallel, "download_image",
                        AsyncMock(return_value=(photo, "image/jpeg")))
    calls = []

    async def primary(system, user, images, picture):
        calls.append("go")
        raise RuntimeError("go is down")

    async def backup(system, user, images, picture):
        calls.append("cc")
        return '{"accept":true,"reason":"Relevant historical map."}'

    screen = make_screen(tmp_path, model_call=primary, fallback_call=backup)
    try:
        job = screen._image_job("En karta över Rom", time.monotonic())
        body = await job.prepare('<ot-image query="Romarrikets karta" alt="Karta"></ot-image>')
    finally:
        await screen.aclose()
    assert calls == ["go", "cc"]  # the backup was asked, not skipped
    assert body.count("/api/images/") == 1 and "Utan bild" not in body


async def test_a_review_holds_its_gate_slot_until_its_cancelled_request_is_gone(
        tmp_path, monkeypatch, commons_picture):
    """The page-wide review gate counts real provider work, not callbacks.

    A review whose provider call lost (a hedge loser, a timeout) is cancelled and
    handed to the reaper, which keeps cancelling and closing it in the background.
    Releasing the gate when the review callback returned let one page run more
    provider requests at once than SCREEN_IMAGE_REVIEWS allows."""
    import time

    monkeypatch.setenv("SCREEN_LOOK", "0")
    monkeypatch.setenv("SCREEN_IMAGE_REVIEWS", "1")  # one review at a time, page-wide
    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    monkeypatch.setenv("SCREEN_HEDGE_AFTER_S", "0.05")
    _, photo, _ = commons_picture
    live = {"now": 0, "peak": 0}

    async def primary(system, user, images, picture):
        if picture is not photo:
            return "<h1>Rom</h1>"
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        try:
            await asyncio.Future()  # never answers: the hedge takes the call over
        finally:
            await asyncio.sleep(0.15)  # a cancel that takes a while to unwind
            live["now"] -= 1

    async def backup(system, user, images, picture):
        return '{"accept":true,"reason":"Relevant architecture."}'

    screen = make_screen(tmp_path, model_call=primary, fallback_call=backup)
    try:
        job = screen._image_job("En sida om Rom", time.monotonic())
        body = await job.prepare('<ot-image query="Colosseum" alt="Valv"></ot-image>'
                                 '<ot-image query="Colosseum" alt="Bågar"></ot-image>')
    finally:
        await screen.aclose()
    assert body.count("Diliff") == 2  # both slots got their reviewed picture
    assert live["peak"] == 1  # the second review waited for the first's request to die


# ---- patch images are loaded before the preview screenshot ------------------

class _FakeFrame:
    """A stub for the srcdoc frame: records the wait/evaluate order."""

    def __init__(self, calls, late_issues=None, fail_image_wait=False, initial_issues=None):
        self.calls = calls
        self.late_issues = late_issues or []
        self.fail_image_wait = fail_image_wait
        self.initial_issues = initial_issues or []
        self.image_waited = False

    async def wait_for_function(self, script, timeout=None):
        self.calls.append(("wait", script, timeout))
        if "ot-image img" in script:
            self.image_waited = True
            if self.fail_image_wait:
                raise TimeoutError("still loading")

    async def evaluate(self, script, arg=None):
        self.calls.append(("eval", script, arg))
        if "otReady" in script:
            return None
        if "ot.fontPx" in script:
            return {"fontPx": 18, "issues": list(self.late_issues if self.image_waited else self.initial_issues)}
        if "ot.patch" in script:
            return []
        if "getAnimations" in script:
            return None
        if "ot.issues.slice" in script:
            return list(self.late_issues)
        raise AssertionError(f"unexpected script: {script!r}")


class _FakePreviewPage:
    def __init__(self, calls, frame):
        self.calls = calls
        self.frames = [object(), frame]

    async def set_content(self, html):
        self.calls.append(("set_content", len(html)))

    async def wait_for_timeout(self, ms):
        self.calls.append(("timeout", ms))

    async def screenshot(self):
        self.calls.append(("screenshot",))
        return b"PNG"

    async def close(self):
        self.calls.append(("close",))


class _FakeBrowser:
    def __init__(self, calls, frame):
        self.calls = calls
        self.frame = frame

    def is_connected(self):
        return True

    async def new_page(self, **kwargs):
        return _FakePreviewPage(self.calls, self.frame)


class _FakeStarter:
    def __init__(self, calls, frame):
        self.calls = calls
        self.frame = frame
        self.chromium = self

    async def start(self):
        return self

    async def launch(self):
        return _FakeBrowser(self.calls, self.frame)


def _stub_browser(monkeypatch, calls, **frame_kwargs):
    import playwright.async_api

    frame = _FakeFrame(calls, **frame_kwargs)
    monkeypatch.setattr(playwright.async_api, "async_playwright",
                        lambda: _FakeStarter(calls, frame))
    return frame


async def test_patch_preview_waits_for_new_images_before_screenshot(tmp_path, monkeypatch):
    screen = make_screen(tmp_path)
    calls: list = []
    late = [{"kind": "image", "msg": "image failed to load: https://example.invalid/x.jpg",
             "where": "ot-image"}]
    stale = {"kind": "crowded", "msg": "label crosses its line"}
    _stub_browser(monkeypatch, calls, late_issues=late, initial_issues=[stale])
    png, issues = await screen._default_render_page(
        "<h1>Rom</h1>", '<ot-patch target="x"><ot-image src="https://example.invalid/x.jpg"></ot-image></ot-patch>',
        [], 370, 610)
    assert png == b"PNG"
    kinds = [call[0] for call in calls]
    assert kinds.index("screenshot") > kinds.index("wait")
    image_waits = [call for call in calls if call[0] == "wait" and "ot-image img" in call[1]]
    assert len(image_waits) == 1 and image_waits[0][2] == 5000
    assert kinds.index("screenshot") > calls.index(image_waits[0])
    assert late[0] in issues
    assert stale not in issues


# ---- Command Code fallback ----------------------------------------------------


@pytest.fixture
def debug_events(monkeypatch):
    import open_tutor.debug_log as debug_log

    events = []
    monkeypatch.setattr(debug_log, "record_active",
                        lambda event, data=None: events.append((event, data or {})))
    return events


def failover_screen(tmp_path, monkeypatch, **kwargs):
    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    monkeypatch.setenv("SCREEN_LOOK", "0")
    kwargs.setdefault("render_page", AsyncMock(return_value=(b"PNG", [])))
    return make_screen(tmp_path, **kwargs)


def test_fallback_spec_defaults_to_none(tmp_path, monkeypatch):
    monkeypatch.delenv("SCREEN_FALLBACK", raising=False)
    assert make_screen(tmp_path).fallback_spec() is None


def test_fallback_spec_cc_mirrors_the_muse_model(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    assert make_screen(tmp_path).fallback_spec() == {
        "model": "meta/muse-spark-1.3-contributor", "api": "responses",
        "reasoning": "minimal"}


def test_fallback_spec_cc_keeps_a_raised_reasoning_level(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    monkeypatch.setenv("SCREEN_REASONING", "low")
    assert make_screen(tmp_path).fallback_spec()["reasoning"] == "low"


@pytest.mark.parametrize("env", [
    {"SCREEN_FALLBACK": "go"},
    {"SCREEN_FALLBACK": "gemini"},
    {"SCREEN_FALLBACK": "cc", "SCREEN_MODEL": "gemini-4-hydrogen"},
    {"SCREEN_FALLBACK": "cc", "SCREEN_MODEL": "deepseek-v4.1-flash"},
])
def test_fallback_spec_rejects_anything_but_cc_for_muse(tmp_path, monkeypatch, env):
    for name in ("SCREEN_FALLBACK", "SCREEN_MODEL", "SCREEN_API",
                 "SCREEN_REASONING", "SCREEN_THINKING"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="SCREEN_FALLBACK"):
        make_screen(tmp_path).fallback_spec()


def test_spec_provider_labels_go_google_and_cc():
    from open_tutor.screen import _spec_provider

    assert _spec_provider({"model": "muse-spark-1.3-contributor"}) == "go"
    assert _spec_provider({"model": "gemini-4-hydrogen"}) == "google"
    assert _spec_provider({"model": "meta/muse-spark-1.3-contributor"}) == "cc"


async def test_primary_success_never_touches_the_fallback(tmp_path, monkeypatch, debug_events):
    fallback = AsyncMock(return_value="<h1>Backup</h1>")
    screen = failover_screen(tmp_path, monkeypatch,
                             model_call=AsyncMock(return_value="<h1>Först</h1>"),
                             fallback_call=fallback)
    delivered = {}
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert fallback.call_count == 0
    assert delivered["page"].body == "<h1>Först</h1>"
    meta = job_meta(tmp_path)
    assert meta["provider"] == "go" and meta["failover"] is False
    assert "primary_error" not in meta
    page_events = [data for event, data in debug_events if event == "screen_page"]
    assert page_events and page_events[0]["provider"] == "go"
    await screen.aclose()


async def test_primary_error_fails_over_and_records_it(tmp_path, monkeypatch, debug_events):
    screen = failover_screen(
        tmp_path, monkeypatch,
        model_call=AsyncMock(side_effect=RuntimeError("provider down")),
        fallback_call=AsyncMock(return_value="<h1>Backup</h1>"))
    delivered, failures = {}, []
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.on_failure = failures.append
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert not failures
    assert delivered["page"].body == "<h1>Backup</h1>"
    meta = job_meta(tmp_path)
    assert meta["provider"] == "cc" and meta["failover"] is True
    assert meta["primary_error"] == "RuntimeError"
    failovers = [data for event, data in debug_events if event == "screen_failover"]
    assert len(failovers) == 1 and failovers[0]["to"] == "cc"
    assert failovers[0]["error"] == "RuntimeError"
    assert failovers[0]["job"] == "s1"
    await screen.aclose()


async def test_stalled_primary_loses_the_first_text_race(tmp_path, monkeypatch):
    """A primary that trickles nothing loses to the backup after the hedge deadline."""
    monkeypatch.setenv("SCREEN_HEDGE_AFTER_S", "0.05")

    async def slow(system, user, images, look_png):
        await asyncio.sleep(30)
        return "<h1>Sent</h1>"

    screen = failover_screen(tmp_path, monkeypatch, model_call=slow,
                             fallback_call=AsyncMock(return_value="<h1>Backup</h1>"))
    delivered = {}
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert delivered["page"].body == "<h1>Backup</h1>"
    meta = job_meta(tmp_path)
    assert meta["provider"] == "cc" and meta["failover"] is True
    assert meta["hedged"] is True and meta["ttft_s"] is not None
    # Slow, not errored: there is no primary error class to report.
    assert "primary_error" not in meta
    await screen.aclose()


async def test_no_fallback_configured_fails_as_today(tmp_path, monkeypatch, debug_events):
    monkeypatch.delenv("SCREEN_FALLBACK", raising=False)
    monkeypatch.setenv("SCREEN_LOOK", "0")
    fallback = AsyncMock(return_value="<h1>Backup</h1>")
    screen = make_screen(tmp_path,
                         model_call=AsyncMock(side_effect=RuntimeError("provider down")),
                         fallback_call=fallback)
    delivered, failures = {}, []
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.on_failure = failures.append
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert delivered == {} and len(failures) == 1 and "Explain in words" in failures[0]
    assert fallback.call_count == 0
    assert not [event for event, _ in debug_events if event == "screen_failover"]
    await screen.aclose()


async def test_small_budget_skips_the_fallback(tmp_path, monkeypatch):
    fallback = AsyncMock(return_value="<h1>Backup</h1>")
    screen = failover_screen(tmp_path, monkeypatch, timeout=0.5,
                             model_call=AsyncMock(side_effect=RuntimeError("down")),
                             fallback_call=fallback)
    delivered, failures = {}, []
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.on_failure = failures.append
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert delivered == {} and len(failures) == 1
    assert fallback.call_count == 0  # ~0.5 s left is below the fallback floor
    await screen.aclose()


async def test_look_fails_over_while_the_write_stays_primary(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    monkeypatch.setenv("SCREEN_LOOK", "1")
    primary = AsyncMock(side_effect=["<h1>Först</h1>", RuntimeError("look down")])
    screen = make_screen(tmp_path, model_call=primary,
                         fallback_call=AsyncMock(return_value="<h1>Fixad</h1>"))
    delivered = {}
    screen.on_page = lambda p: delivered.setdefault("page", p)
    screen.ask("En sida om bråk")
    await screen.wait_idle()

    assert delivered["page"].body == "<h1>Fixad</h1>"
    meta = job_meta(tmp_path)
    assert meta["provider"] == "go" and meta["failover"] is True
    assert meta["primary_error"] == "RuntimeError"
    await screen.aclose()


async def test_patch_failover_records_cc(tmp_path, monkeypatch):
    screen = await ready_page(tmp_path, monkeypatch)
    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    screen._model_call = AsyncMock(side_effect=RuntimeError("provider down"))
    screen._fallback_call = AsyncMock(
        return_value='<ot-patch target="klocka"><ot-clock time="7:30"></ot-clock></ot-patch>')
    patched, failures = {}, []
    screen.on_patch = lambda p: patched.setdefault("patch", p)
    screen.on_failure = failures.append
    screen.ask("Visa halv sju istället")
    await screen.wait_idle()

    assert not failures and "7:30" in patched["patch"].patch
    meta = json.loads((tmp_path / "pages" / "s2" / "meta.json").read_text())
    assert meta["provider"] == "cc" and meta["failover"] is True
    assert meta["primary_error"] == "RuntimeError"
    await screen.aclose()


async def test_cc_fallback_wire_request(tmp_path, monkeypatch):
    """The backup call streams Command Code with its key, model and session header."""
    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    monkeypatch.setenv("COMMAND_CODE_API_KEY", "test-cc")
    requests = _streaming_openai(
        monkeypatch, _responses_sse("<h1>Hej</h1>", "meta/muse-spark-1.3-contributor"))

    screen = make_screen(tmp_path)
    text, first_s = await screen._stream_spec(screen.fallback_spec(), "System", "Lesson",
                                               [], None)
    assert text == "<h1>Hej</h1>" and first_s is not None
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == "api.commandcode.ai"
    assert request.url.path == "/provider/v1/responses"
    assert request.headers["authorization"] == "Bearer test-cc"
    assert request.headers["x-opencode-session"] == "screen"
    body = json.loads(request.content)
    assert body["model"] == "meta/muse-spark-1.3-contributor"
    assert body["reasoning"] == {"effort": "minimal"}
    assert body["store"] is False and body["stream"] is True
    await screen.aclose()


async def test_slow_patch_image_still_screenshots_instead_of_failing(tmp_path, monkeypatch):
    screen = make_screen(tmp_path)
    calls: list = []
    _stub_browser(monkeypatch, calls, fail_image_wait=True)
    png, issues = await screen._default_render_page(
        "<h1>Rom</h1>", '<ot-patch target="x"><ot-image src="https://example.invalid/x.jpg"></ot-image></ot-patch>',
        [], 370, 610)
    assert png == b"PNG"
    assert any(i["kind"] == "image" and "still loading" in i["msg"] for i in issues)


async def test_plain_page_render_does_not_wait_for_patch_images(tmp_path, monkeypatch):
    screen = make_screen(tmp_path)
    calls: list = []
    _stub_browser(monkeypatch, calls)
    png, issues = await screen._default_render_page("<h1>Rom</h1>", None, [], 370, 610)
    assert png == b"PNG" and issues == []
    assert not [call for call in calls if call[0] == "wait" and "ot-image img" in call[1]]


async def test_patch_preview_retains_renderer_exception_after_final_lint(tmp_path, monkeypatch):
    screen = make_screen(tmp_path)
    calls = []
    frame = _stub_browser(monkeypatch, calls)
    evaluate = frame.evaluate

    async def reject_patch(script, arg=None):
        if "ot.patch" in script:
            raise ValueError("patch rejected")
        return await evaluate(script, arg)

    monkeypatch.setattr(frame, "evaluate", reject_patch)
    png, issues = await screen._default_render_page("<h1>Prov</h1>", "bad patch", [], 370, 610)
    assert png == b"PNG"
    assert issues == ["patch failed: ValueError"]


async def test_failed_responses_stream_raises_instead_of_returning_a_page(tmp_path, monkeypatch):
    """A ``response.failed`` terminal event is an error, not a (partial) page."""
    import httpx

    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    monkeypatch.setenv("COMMAND_CODE_API_KEY", "test-cc")

    def handle(request):
        events = [
            {"type": "response.output_text.delta", "sequence_number": 3,
             "output_index": 0, "content_index": 0, "item_id": "msg_1", "delta": "<h1>Hal"},
            {"type": "response.failed", "sequence_number": 4,
             "response": {"id": "resp_test", "object": "response", "created_at": 0,
                            "model": "m", "status": "failed", "output": [],
                            "tools": [], "tool_choice": "auto", "parallel_tool_calls": True,
                            "error": {"code": "server_error", "message": "boom"}}},
        ]
        body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=body.encode())

    _streaming_openai(monkeypatch, handle)
    screen = make_screen(tmp_path)
    with pytest.raises(RuntimeError, match="response.failed"):
        await screen._stream_spec(screen.fallback_spec(), "System", "Lesson", [], None)
    await screen.aclose()


# ---- reveal mode: show-when-ready is the default ----------------------------

async def test_finished_page_shows_by_default_and_holds_when_asked(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    screen = make_screen(tmp_path, model_call=AsyncMock(return_value="<h1>Hej</h1>"))
    pages = []
    screen.on_page = pages.append
    screen.ask("En sida om klockan")
    await screen.wait_idle()
    assert pages[0].reveal == "show"
    assert json.loads((pages[0].directory / "meta.json").read_text())["reveal"] == "show"

    screen2 = make_screen(tmp_path, model_call=AsyncMock(return_value="<h1>Hej</h1>"))
    held = []
    screen2.on_page = held.append
    screen2.ask("En sida med facit", reveal="hold")
    await screen2.wait_idle()
    assert held[0].reveal == "hold"
    await screen.aclose()
    await screen2.aclose()


def test_ask_rejects_an_unknown_reveal_mode(tmp_path):
    screen = make_screen(tmp_path)
    with pytest.raises(ValueError, match="reveal"):
        screen.ask("En sida", reveal="ladda")


async def test_show_mode_reaches_the_browser_at_once(tmp_path, monkeypatch):
    """The stale-screen fix: a show-when-ready page is delivered by the ready
    callback itself, instead of waiting hidden for the next show_page turn."""
    monkeypatch.setenv("SCREEN_LOOK", "0")
    screen = make_screen(tmp_path, model_call=AsyncMock(return_value="<h1>Hej</h1>"))
    room = FakeRoom()
    tutor = smart_tutor(room, screen)
    pages = []
    screen.on_page = lambda p: pages.append(p)

    from unittest.mock import Mock

    class FakeSession:
        agent_state = "listening"
        user_state = "listening"
        generate_reply = Mock()

    screen.ask("En sida om klockan")
    await screen.wait_idle()
    await tutor.screen_page_ready(FakeSession(), pages[0])
    assert screen.visible_id == "p1"
    method, payload = room.local_participant.calls[0]
    assert method == "board.show" and payload["id"] == "p1"
    await asyncio.sleep(0)  # let the prompt task run
    assert "on screen now" in FakeSession.generate_reply.call_args.kwargs["user_input"]
    await screen.aclose()


async def test_held_page_stays_invisible_until_show_page(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    screen = make_screen(tmp_path, model_call=AsyncMock(return_value="<h1>Facit</h1>"))
    room = FakeRoom()
    tutor = smart_tutor(room, screen)
    pages = []
    screen.on_page = lambda p: pages.append(p)

    from unittest.mock import Mock

    class FakeSession:
        agent_state = "listening"
        user_state = "listening"
        generate_reply = Mock()

    screen.ask("En sida med facit", reveal="hold")
    await screen.wait_idle()
    await tutor.screen_page_ready(FakeSession(), pages[0])
    await asyncio.sleep(0)  # let the prompt task run
    assert screen.visible_id is None
    assert room.local_participant.calls == []
    assert "show_page('p1')" in FakeSession.generate_reply.call_args.kwargs["user_input"]
    assert "now visible" in await tutor.show_page(AsyncMock(), page_id="p1")
    assert screen.visible_id == "p1"
    await screen.aclose()


async def test_ask_screen_tool_offers_show_and_hold(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    screen = make_screen(tmp_path, model_call=AsyncMock(return_value="<h1>Hej</h1>"))
    tutor = smart_tutor(FakeRoom(), screen)
    default = await tutor.ask_screen(AsyncMock(), ask="En sida")
    assert "appears on the screen by itself" in default
    held = await tutor.ask_screen(AsyncMock(), ask="En sida med facit", show="hold")
    assert "stays invisible until you call show_page" in held
    bad = await tutor.ask_screen(AsyncMock(), ask="En sida", show="smyg")
    assert "Unknown show mode" in bad and "Nothing was asked" in bad
    await screen.wait_idle()
    await screen.aclose()


# ---- loading overlay and progress --------------------------------------------

async def test_screen_loading_dims_through_board_loading(tmp_path, monkeypatch):
    screen = await ready_page(tmp_path, monkeypatch)
    room = FakeRoom()
    tutor = smart_tutor(room, screen)
    assert "Laddar historia" in await tutor.screen_loading(AsyncMock(), topic="historia")
    method, payload = room.local_participant.calls[0]
    assert method == "board.loading" and payload == {"id": "p1", "topic": "historia"}
    assert "cleared" in await tutor.screen_loading(AsyncMock(), topic="")
    assert room.local_participant.calls[1] == ("board.loading", {"id": "p1", "topic": ""})
    await screen.aclose()


async def test_screen_loading_without_a_visible_page_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    screen = make_screen(tmp_path)
    tutor = smart_tutor(FakeRoom(), screen)
    assert "No page is on screen" in await tutor.screen_loading(AsyncMock(), topic="historia")
    await screen.aclose()


async def test_screen_failed_clears_the_loading_overlay(tmp_path, monkeypatch):
    screen = await ready_page(tmp_path, monkeypatch)
    room = FakeRoom()
    tutor = smart_tutor(room, screen)

    from unittest.mock import Mock

    class FakeSession:
        agent_state = "listening"
        user_state = "listening"
        generate_reply = Mock()

    await tutor.screen_failed(FakeSession(), "boom")
    assert ("board.loading", {"id": "p1", "topic": ""}) in room.local_participant.calls
    assert "picture did not work" in FakeSession.generate_reply.call_args.kwargs["user_input"]
    await screen.aclose()


async def test_screen_status_reports_phase_and_finish(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    assert "no page has been requested" in make_screen(tmp_path).status_line()
    release = asyncio.Event()

    async def model(system, user, images, look_png):
        await release.wait()
        return "<h1>Hej</h1>"

    screen = make_screen(tmp_path, model_call=model)
    screen.ask("En sida om klockan")
    await asyncio.sleep(0.2)
    assert "writing the page" in screen.status_line()
    release.set()
    await screen.wait_idle()
    line = screen.status_line()
    assert "finished page p1" in line and "waiting for show_page" in line
    screen.mark_visible("p1")
    assert "on screen now" in screen.status_line()
    assert "Unknown screen job" in screen.status_line("s9")
    await screen.aclose()


def test_image_deadline_uses_the_job_limit_not_the_page_target(tmp_path):
    import time as time_mod

    screen = make_screen(tmp_path)
    # The job is created at job start, as _run_job does: the deadline is the
    # job limit minus render reserves (~17 s), not 6 s from an image step
    # that only starts once the page is written.
    t0 = time_mod.monotonic()
    job = screen._image_job("Visa valv", t0)
    assert job.deadline == pytest.approx(t0 + screen.timeout - 3.2, abs=0.5)
    assert job.deadline - t0 > 12.0


# ---- streaming image prefetch ------------------------------------------------

def test_complete_slots_waits_for_the_closing_tag():
    from screen.tools.page_images import complete_slots

    full = ('<h1>Rom</h1><ot-image id="a" query="Colosseum" alt="Valv">etikett</ot-image>'
            '<p>slut</p>')
    assert [s.attrs["id"] for s in complete_slots(full)] == ["a"]
    assert complete_slots(full[: full.index("</ot-image>")]) == []
    assert complete_slots('<h1>Rom</h1><ot-image id="a" query="Colos') == []
    two = full + '<ot-image id="b" query="Forum" alt="F">x'
    assert [s.attrs["id"] for s in complete_slots(two)] == ["a"]


async def test_prefetch_starts_before_the_stream_ends(tmp_path, monkeypatch, commons_picture):
    """The search for a complete slot starts while the page model is still
    writing, not after its full text arrived."""
    from screen.tools import commons_images as commons

    monkeypatch.setenv("SCREEN_LOOK", "0")
    search_started = asyncio.Event()
    base_search = commons.search_images

    async def slow_search(query, client=None):
        search_started.set()
        return await base_search(query, client=client)

    monkeypatch.setattr(commons, "search_images", slow_search)
    head = '<h1>Rom</h1><ot-image id="bild" query="Colosseum" alt="Valv">Valv</ot-image>'

    async def model(system, user, images, look_png, on_text=None):
        if look_png is not None:
            return '{"accept":true,"reason":"Relevant architecture."}'
        assert on_text is not None  # the write call feeds the prefetch pool
        on_text(head)
        await asyncio.wait_for(search_started.wait(), timeout=5)  # still streaming
        on_text("<p>Slutet.</p>")
        return head + "<p>Slutet.</p>"

    screen = make_screen(tmp_path, model_call=model)
    pages, patches = [], []
    screen.on_page = lambda p: (pages.append(p), screen.mark_visible(p.page_id))
    screen.on_patch = patches.append
    screen.ask("Visa valv i Rom")
    await screen.wait_idle()
    # The review overlapped the writing; the delivered page carries the
    # reviewed image, with no raw slot (no query, no model URL) left in it.
    assert len(pages) == 1 and patches == []
    body = pages[0].body
    assert "query=" not in body and "Diliff" in body
    assert body.count("<ot-image") == 1 and 'src="https://' in body
    await screen.aclose()


async def test_slots_resolve_concurrently_while_writing(tmp_path, monkeypatch, commons_picture):
    """Two image slots review at the same time: a sequential pipeline would
    deadlock this test (the first review waits for the second to start)."""
    monkeypatch.setenv("SCREEN_LOOK", "0")
    started: set[str] = set()
    both = asyncio.Event()
    page = ('<h1>Rom</h1>'
            '<ot-image id="a" query="Colosseum" alt="Valv">V</ot-image>'
            '<ot-image id="b" query="Forum Romanum" alt="Forum">F</ot-image>')

    async def model(system, user, images, look_png, on_text=None):
        if look_png is not None:
            which = "a" if "'id': 'a'" in user else "b"
            started.add(which)
            if len(started) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), timeout=5)
            return '{"accept":true,"reason":"Passar."}'
        if on_text is not None:
            on_text(page)
        return page

    screen = make_screen(tmp_path, model_call=model)
    pages, patches = [], []
    screen.on_page = lambda p: (pages.append(p), screen.mark_visible(p.page_id))
    screen.on_patch = patches.append
    screen.ask("Visa valv och forum")
    await screen.wait_idle()
    assert started == {"a", "b"} and len(pages) == 1 and patches == []
    # Both reviews overlapped the writing; both pictures ship in first paint.
    assert pages[0].body.count("commons.wikimedia.org") == 2
    assert "query=" not in pages[0].body
    await screen.aclose()


async def test_loser_prefetch_is_cancelled_and_dropped_slot_unused(tmp_path, monkeypatch, commons_picture):
    """Raced write, loser streams a slot the winner does not have: its vision
    review is cancelled at the decision and never reaches the page."""
    monkeypatch.setenv("SCREEN_LOOK", "0")
    monkeypatch.setenv("SCREEN_FALLBACK", "cc")
    monkeypatch.setenv("SCREEN_RACE", "1")
    started: set[str] = set()
    completed: set[str] = set()
    verdict = '{"accept":true,"reason":"Passar."}'
    slow_page = '<h1>Långsam</h1><ot-image id="slow" query="Colosseum" alt="S">S</ot-image>'
    fast_page = '<h1>Snabb</h1><ot-image id="fast" query="Colosseum" alt="F">F</ot-image>'
    release_slow_review = asyncio.Event()

    async def primary(system, user, images, look_png, on_text=None):
        if look_png is not None:
            which = "slow" if "'id': 'slow'" in user else "fast"
            started.add(which)
            if which == "slow":
                await release_slow_review.wait()  # never released: must be cancelled
            else:
                await asyncio.sleep(0.3)
            completed.add(which)
            return verdict
        if on_text is not None:
            on_text(slow_page)
        await asyncio.sleep(5)
        return slow_page

    async def secondary(system, user, images, look_png, on_text=None):
        assert look_png is None  # reviews always run on the primary seam
        if on_text is not None:
            on_text(fast_page)
        await asyncio.sleep(0.05)
        return fast_page

    screen = make_screen(tmp_path, model_call=primary, fallback_call=secondary)
    pages, patches = [], []
    screen.on_page = lambda p: (pages.append(p), screen.mark_visible(p.page_id))
    screen.on_patch = patches.append
    screen.ask("Visa Colosseum fort")
    await screen.wait_idle()
    # The winner's page ships with its reviewed image; the loser's review is
    # cancelled at the decision and never reaches the page. No fill: images
    # resolve before the page is shown.
    assert len(pages) == 1 and patches == []
    assert "query=" not in pages[0].body and "commons.wikimedia.org" in pages[0].body
    assert "slow" in started and "slow" not in completed  # cancelled mid-review
    assert "fast" in completed
    await screen.aclose()


async def test_dropped_slot_result_is_never_shown(tmp_path, monkeypatch, commons_picture):
    """A slot the lint retry changes away is gone: its review resolves inline
    during the first prepare, and the retry drops the slot. Nothing unreviewed
    ships, and no fill machinery is involved."""
    monkeypatch.setenv("SCREEN_LOOK", "0")
    reviewed: set[str] = set()
    first = ('<h1>Rom</h1><ot-image id="bild" query="Colosseum" alt="Valv">V</ot-image>')
    fixed = "<h1>Rom</h1><p>Utan bild.</p>"

    async def model(system, user, images, look_png, on_text=None):
        if look_png is not None:
            reviewed.add("bild")
            await asyncio.sleep(1)
            return '{"accept":true,"reason":"Sen."}'
        if on_text is not None:
            on_text(first)
        return first if "It still reports" not in user else fixed

    renders = [(b"PNG", [{"kind": "dense", "msg": "shorten text"}]), (b"PNG", [])]

    async def render(body, patch, history, w, h):
        return renders.pop(0)

    screen = make_screen(tmp_path, model_call=model, render_page=render)
    pages, patches = [], []
    screen.on_page = lambda p: (pages.append(p), screen.mark_visible(p.page_id))
    screen.on_patch = patches.append
    screen.ask("Visa valv")
    await screen.wait_idle()
    assert reviewed == {"bild"}  # the review ran, too late
    assert len(pages) == 1 and "ot-image" not in pages[0].body
    assert patches == []  # no target left: nothing filled in
    await screen.aclose()


async def test_prefetch_beats_sequential_write_then_review(tmp_path, monkeypatch, commons_picture):
    """Overlapping search+download+review with the writing, against doing it
    afterwards: the same sleeps, both sides, so the gap is the overlap. Both
    deliver the reviewed image in first paint; the streamed side just gets
    there sooner."""
    import time as time_mod

    monkeypatch.setenv("SCREEN_LOOK", "0")
    body = '<h1>Rom</h1><ot-image id="bild" query="Colosseum" alt="Valv">V</ot-image>'
    verdict = '{"accept":true,"reason":"Relevant."}'

    async def review(system, user, images, look_png):
        await asyncio.sleep(0.6)
        return verdict

    async def sequential(system, user, images, look_png):
        await asyncio.sleep(0.6)  # the writing, all at once, no streaming
        return body

    async def streamed(system, user, images, look_png, on_text=None):
        if on_text is not None:
            on_text(body)
        await asyncio.sleep(0.6)  # the rest of the writing
        return body

    async def run(model):
        screen = make_screen(tmp_path, model_call=model)
        screen._model_call = model  # reviews use the primary seam too
        delivered: list = []
        started = time_mod.monotonic()
        screen.on_page = delivered.append
        screen.ask("Visa valv")
        await screen.wait_idle()
        await screen.aclose()
        assert len(delivered) == 1 and "commons.wikimedia.org" in delivered[0].body
        return time_mod.monotonic() - started

    async def review_model(system, user, images, look_png, on_text=None):
        if look_png is not None:
            return await review(system, user, images, look_png)
        return await sequential(system, user, images, look_png)

    # Sequential: the model fake takes no on_text, so the pool stays empty.
    slow = await run(review_model)

    async def streamed_model(system, user, images, look_png, on_text=None):
        if look_png is not None:
            return await review(system, user, images, look_png)
        return await streamed(system, user, images, look_png, on_text=on_text)

    fast = await run(streamed_model)
    assert fast + 0.3 < slow, f"prefetch {fast:.2f}s should beat sequential {slow:.2f}s"


# ---- review follow-ups: prefetch identity, budget, fills, shutdown, veil ----

async def test_identical_slots_share_one_review(tmp_path, monkeypatch, commons_picture):
    """Same full slot from two attempts: one search+download+review, used twice."""
    from screen.tools.page_images import PageImages

    import time as time_mod

    reviews: list[str] = []

    async def review(user, image):
        reviews.append(user)
        return '{"accept":true,"reason":"ok"}'

    images = PageImages("ctx", review, time_mod.monotonic() + 30)
    body = '<h1>Rom</h1><ot-image id="bild" query="Colosseum" alt="Valv">V</ot-image>'
    assert "Diliff" in await images.prepare(body)
    assert "Diliff" in await images.prepare(body)
    assert len(reviews) == 1


async def test_aclose_cancels_inflight_prefetches(tmp_path, monkeypatch, commons_picture):
    """Shutdown owns the pool too: a pending Commons search leaves no
    `screen-prefetch-*` task alive after close."""
    monkeypatch.setenv("SCREEN_LOOK", "0")
    started = asyncio.Event()

    async def model(system, user, images, look_png, on_text=None):
        if on_text is not None:
            on_text('<h1>Rom</h1><ot-image id="bild" query="Colosseum" alt="V">V</ot-image>')
        await asyncio.Future()  # the write never finishes on its own

    screen = make_screen(tmp_path, model_call=model)
    screen.ask("Visa valv")
    for _ in range(200):
        if screen._pool is not None and screen._pool._tasks:
            break
        await asyncio.sleep(0.05)
    assert screen._pool is not None and screen._pool._tasks
    await screen.aclose()
    assert screen._pool is None
    live = [t for t in asyncio.all_tasks()
            if t.get_name().startswith("screen-prefetch") and not t.done()]
    assert live == []


async def test_held_page_ready_clears_the_loading_veil(tmp_path, monkeypatch):
    """Dim p1, finish a show=hold request, then a show request: the veil is
    cleared at each terminal state, and the new page clears the old frame."""
    monkeypatch.setenv("SCREEN_LOOK", "0")

    from unittest.mock import Mock

    bodies = ["<h1>Hållet</h1>",
              "<h1>Visat</h1><ot-image id=\"bild\" query=\"Colosseum\" alt=\"Valv\">V</ot-image>"]
    writes = 0

    async def model(system, user, images, look_png, on_text=None):
        nonlocal writes
        if look_png is not None:
            return '{"accept":true,"reason":"ok"}'
        text = bodies[min(writes, 1)]
        writes += 1
        if on_text is not None:
            on_text(text)
        return text

    screen = await ready_page(tmp_path, monkeypatch)
    room = FakeRoom()
    tutor = smart_tutor(room, screen)
    screen._model_call = model

    class FakeSession:
        agent_state = "listening"
        user_state = "listening"
        generate_reply = Mock()

    assert "Laddar historia" in await tutor.screen_loading(AsyncMock(), topic="historia")
    assert ("board.loading", {"id": "p1", "topic": "historia"}) in room.local_participant.calls

    held, shown = [], []
    screen.on_page = lambda p: (held if p.reveal == "hold" else shown).append(p)
    screen.ask("En hållen sida", reveal="hold")
    await screen.wait_idle()
    await tutor.screen_page_ready(FakeSession(), held[0])
    await asyncio.sleep(0)  # let the prompt task run
    assert ("board.loading", {"id": "p1", "topic": ""}) in room.local_participant.calls

    screen.ask("En visad sida")
    await screen.wait_idle()
    assert len(shown) == 1
    new_id = shown[0].page_id
    await tutor.screen_page_ready(FakeSession(), shown[0])
    assert screen.visible_id == new_id
    clears = [c for c in room.local_participant.calls
              if c == ("board.loading", {"id": "p1", "topic": ""})]
    assert len(clears) == 2  # held-ready clear + old-frame clear on show
    await screen.aclose()


async def test_canonical_src_reuse_needs_the_exact_reviewed_slot(tmp_path, monkeypatch, commons_picture):
    """Owner rule: an image ships only under the exact slot it was reviewed
    for. Approving a hidden `later` image must not let a lint retry emit its
    canonical URL with the same alt, a different id, no `later` and changed
    labels ship visibly without re-review. Re-preparing our own rendered body
    still reuses without new requests."""
    from screen.tools.page_images import PageImages

    import time as time_mod

    from screen.tools import commons_images as commons

    monkeypatch.setattr(commons, "search_images",
                        AsyncMock(return_value=commons.SearchResult([commons_picture[0]])))
    reviews: list[str] = []

    async def review(user, image):
        reviews.append(user)
        return '{"accept":true,"reason":"Passar."}'

    images = PageImages("ctx", review, time_mod.monotonic() + 30)
    hidden = '<ot-image later id="gömd" query="Colosseum" alt="Valv">hemliga etiketter</ot-image>'
    out = await images.prepare("<h1>Rom</h1>" + hidden)
    assert "later" in out and len(reviews) == 1

    retry = (f'<ot-image id="synlig" src="{commons_picture[0].image_url}" '
             'alt="Valv">andra etiketter</ot-image>')
    out2 = await images.prepare("<h1>Rom</h1>" + retry)
    assert len(reviews) == 2  # reviewed again, not reused without review
    assert any("andra etiketter" in user for user in reviews)
    assert "later" not in out2  # the retry slot was never hidden

    before = len(reviews)
    assert await images.prepare(out) == out  # our own output reuses freely
    assert await images.prepare(out2) == out2
    assert len(reviews) == before




async def test_delivered_html_never_contains_unreviewed_images(tmp_path, monkeypatch, commons_picture):
    """Lead rule: nothing unresolved, no query, no model src, ever reaches the
    browser. A query slot, a model-supplied src and a nested ot-image all
    resolve to reviewed canonical HTML or a text fallback before delivery."""
    from screen.tools import commons_images as commons
    from screen.tools.page_images import PageImages, image_slots

    import time as time_mod

    candidate = commons_picture[0]

    async def lookup(src, client=None):
        return commons.SearchResult([candidate], [])

    monkeypatch.setattr(commons, "lookup_image", lookup)
    reviews: list[str] = []

    async def review(user, image):
        reviews.append(user)
        if "Modellbild" in user:
            return ('{"accept":false,"reason":"Hittar inte bilden.",'
                    '"fallback":"<p>Vi beskriver valven i ord.</p>"}')
        return '{"accept":true,"reason":"Passar."}'

    images = PageImages("ctx", review, time_mod.monotonic() + 30)
    body = ('<h1>Rom</h1>'
            '<ot-image id="a" query="Colosseum" alt="Valv">etiketter</ot-image>'
            '<ot-image id="b" src="https://example.invalid/x.jpg" alt="Modellbild">text</ot-image>'
            '<ot-image id="c" query="Colosseum" alt="W">'
            '<ot-image src="https://example.invalid/nested.jpg"></ot-image>etiketter</ot-image>'
            # An unclosed outer slot must not let the nested src through untouched.
            '<ot-image id="d" query="Colosseum" alt="Ytter">'
            '<ot-image src="https://example.invalid/unreviewed.png" alt="Modellbild"></ot-image>')
    out = await images.prepare(body)
    assert len(reviews) == 5  # every slot judged, none slipped through
    assert "query=" not in out
    assert "example.invalid" not in out
    assert candidate.image_url.split("?")[0] in out  # the reviewed canonical src
    for slot in image_slots(out):
        assert "<ot-image" not in slot.children  # no nested leftovers
        assert "src" in slot.attrs  # every shipped slot resolved


async def test_board_changes_serialize_through_one_lock(tmp_path, monkeypatch):
    """Every board change goes through the delivery lock: a patch RPC in flight
    holds it, so a concurrent show cannot interleave or switch visibility
    mid-send. Order is patch RPC, then show RPC, then the new visible page."""
    from unittest.mock import Mock

    screen = make_screen(tmp_path)
    body = '<h1>Rom</h1><p>Text.</p>'
    screen.pages["p1"] = PageResult(job_id="s1", page_id="p1", title="Rom",
                                    body=body, png=b"PNG")
    screen.mark_visible("p1")
    screen.pages["p2"] = PageResult(job_id="s2", page_id="p2", title="Grekland",
                                    body="<h1>Grekland</h1>", png=b"PNG")
    patch = PatchResult(job_id="s2", page_id="p1",
                        patch='<ot-patch target="t" do="text">Hej</ot-patch>',
                        png=b"PNG")
    room = FakeRoom()
    tutor = smart_tutor(room, screen)
    order: list[str] = []
    entered = asyncio.Event()
    release = asyncio.Event()
    orig = room.local_participant.perform_rpc

    async def gated(*, destination_identity, method, payload, response_timeout):
        order.append(f"{method} start")
        if method == "board.patch":
            entered.set()
            await asyncio.wait_for(release.wait(), timeout=10)
        out = await orig(destination_identity=destination_identity, method=method,
                         payload=payload, response_timeout=response_timeout)
        order.append(f"{method} end")
        return out

    room.local_participant.perform_rpc = gated
    t1 = asyncio.create_task(tutor.screen_patch_ready(Mock(), patch))
    await asyncio.wait_for(entered.wait(), timeout=10)
    t2 = asyncio.create_task(tutor._show_page_object(screen.pages["p2"]))
    await asyncio.sleep(0.2)
    assert screen.visible_id == "p1"  # the show waits for the delivery lock
    release.set()
    assert await t1 is True
    ok, _note = await t2
    assert ok is True and screen.visible_id == "p2"
    assert order == ["board.patch start", "board.patch end",
                     "board.show start", "board.show end"]
    await screen.aclose()




# ---- a page that lands after the tutor asked a question (2026-11-27) --------
# In a real call, 4 of 4 pages landed 0.1-0.3 s after the tutor had asked the
# child a question; the page-ready prompt then made the tutor answer its own
# question before the child could. The page is in the context either way, so
# the prompt is skipped while the tutor's question is unanswered.


def _ctx(*messages):
    from livekit.agents import llm as lk_llm

    ctx = lk_llm.ChatContext.empty()
    for role, text in messages:
        ctx.add_message(role=role, content=[text])
    return ctx


@pytest.mark.parametrize("text", [
    "Vad tror du händer då?", 'Vad tror du?"', "»Varför då?«", "Hur många? ",
    "Okej. Vad är sex gånger sju?)",
])
def test_a_spoken_question_waits_for_the_child(text):
    from open_tutor.agent import tutor_awaits_answer

    assert tutor_awaits_answer(_ctx(("user", "Hjälp mig med bråk."), ("assistant", text)))


@pytest.mark.parametrize("text", ["Titta här.", "Vi ritar den nu", "Bra! Nu kör vi."])
def test_a_bridge_statement_does_not(text):
    from open_tutor.agent import tutor_awaits_answer

    assert not tutor_awaits_answer(_ctx(("user", "Hjälp mig."), ("assistant", text)))


def test_events_and_tool_turns_do_not_count_as_an_answer():
    from livekit.agents import llm as lk_llm

    from open_tutor.agent import tutor_awaits_answer
    from open_tutor.screen_context import screen_tag

    ctx = _ctx(("user", "Hjälp mig."), ("assistant", "Vad vet du om socker?"))
    ctx.items.append(lk_llm.FunctionCall(call_id="c1", name="ask_screen", arguments="{}"))
    ctx.items.append(lk_llm.FunctionCallOutput(call_id="c1", name="ask_screen", output="ok",
                                               is_error=False))
    ctx.add_message(role="assistant", content=[""])
    ctx.add_message(role="user", content=["[Session event, not the child's words: x]"])
    ctx.add_message(role="user", content=["[Screen page p1 ('G') is now ON SCREEN. ...]"],
                    extra=screen_tag("page", "p1"))
    ctx.add_message(role="system", content=["system note"])
    assert tutor_awaits_answer(ctx)


def test_a_learner_reply_after_the_question_releases_it():
    from open_tutor.agent import tutor_awaits_answer

    assert not tutor_awaits_answer(_ctx(("assistant", "Vad tror du?"), ("user", "Sex.")))
    # Even when the reply was flagged as said during quiet work.
    assert not tutor_awaits_answer(_ctx(
        ("assistant", "Vad tror du?"), ("user", "[The child was working quietly] sex")))
    assert not tutor_awaits_answer(_ctx())


def _session():
    from unittest.mock import Mock

    class FakeSession:
        agent_state = "listening"
        user_state = "listening"
        generate_reply = Mock()

    return FakeSession


async def _page_after(tmp_path, monkeypatch, tutor_said, reveal="show"):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    recorded = []
    monkeypatch.setattr("open_tutor.agent.record_active",
                        lambda kind, data: recorded.append((kind, data)))
    screen = make_screen(tmp_path, model_call=AsyncMock(return_value="<h1>Bråk</h1>"))
    tutor = smart_tutor(FakeRoom(), screen)
    await tutor.update_chat_ctx(_ctx(("user", "Kan du rita en tårta i fjärdedelar?"), ("assistant", tutor_said)))
    pages = []
    screen.on_page = pages.append
    screen.ask("Bråk", reveal=reveal)
    await screen.wait_idle()
    session = _session()
    await tutor.screen_page_ready(session(), pages[0])
    for _ in range(3):
        await asyncio.sleep(0)  # let the prompt task run
    await screen.aclose()
    return tutor, session, recorded


async def test_a_page_after_a_question_is_shown_but_not_prompted(tmp_path, monkeypatch):
    tutor, session, recorded = await _page_after(tmp_path, monkeypatch,
                                                 "Hur många bitar tror du det blir?")
    assert tutor.screen.visible_id == "p1"
    session.generate_reply.assert_not_called()
    assert ("screen_prompt_deferred", {"page": "p1", "reason": "tutor_asked_question"}) in recorded
    # The page is in the context, so the tutor teaches from it next turn.
    assert any("is now ON SCREEN" in (item.text_content or "")
               for item in tutor.chat_ctx.items if item.type == "message")


async def test_a_page_after_a_bridge_is_prompted_at_once(tmp_path, monkeypatch):
    _, session, recorded = await _page_after(tmp_path, monkeypatch, "Jag ritar den åt dig.")
    assert "on screen now" in session.generate_reply.call_args.kwargs["user_input"]
    assert not any(kind == "screen_prompt_deferred" for kind, _ in recorded)


async def test_a_held_page_after_a_question_is_not_prompted_either(tmp_path, monkeypatch):
    tutor, session, _ = await _page_after(tmp_path, monkeypatch, "Vad tror du?", reveal="hold")
    assert tutor.screen.visible_id is None
    session.generate_reply.assert_not_called()


async def test_a_screen_failure_is_never_deferred(tmp_path, monkeypatch):
    screen = make_screen(tmp_path)
    tutor = smart_tutor(FakeRoom(), screen)
    await tutor.update_chat_ctx(_ctx(("user", "Rita en tårta."), ("assistant", "Vad tror du?")))
    session = _session()
    await tutor.screen_failed(session(), "timeout.")
    assert "screen failed" in session.generate_reply.call_args.kwargs["user_input"]
    await screen.aclose()


async def test_ask_screen_keeps_the_bridge_short_and_unspoiled(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    screen = make_screen(tmp_path, model_call=AsyncMock(return_value="<h1>Hej</h1>"))
    tutor = smart_tutor(FakeRoom(), screen)
    note = await tutor.ask_screen(AsyncMock(), ask="En sida")
    assert "short bridge" in note
    assert "Do not ask a question the coming page will answer" in note
    assert "say you are making a page" in note
    await screen.wait_idle()
    await screen.aclose()
