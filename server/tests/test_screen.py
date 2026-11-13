"""Smart Screen server half: classifier, job flow, queueing, tool surface."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from livekit.agents.llm.tool_context import find_function_tools

from open_tutor.agent import SmartTutor, Tutor
from open_tutor.board import PageItem, board_item
from open_tutor.prompt import instructions, smart_instructions
from open_tutor.screen import (
    Screen,
    classify_answer,
    page_title,
    session_pages_dir,
    strip_fences,
)


def tool_names(cls):
    return {t.info.name for t in find_function_tools(cls)}


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

    async def render(body, patch, w, h):
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

    async def render(body, patch, w, h):
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

    async def render(body, patch, w, h):
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

    async def render(body, patch, w, h):
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
    assert screen.visible_patches == [rendered["patch"]]
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

    async def render(body, patch, w, h):
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

    async def render(body, patch, w, h):
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

    async def render(body, patch, w, h):
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

    async def render(body, patch, w, h):
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

    async def render(body, patch, w, h):
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


def test_non_smart_mode_still_exposes_boards():
    assert tool_names(Tutor) == {"commission_board", "edit_board", "find_resources",
                                 "share_resource", "start_quiet_work", "stay_quiet",
                                 "save_note"}
    text = instructions({"name": "Leo"})
    assert "commission_board" in text and "ask_screen" not in text


def test_smart_mode_exposes_screen_tools_instead_of_boards():
    assert tool_names(SmartTutor) == {"ask_screen", "show_page", "reveal", "point",
                                      "find_resources", "share_resource", "start_quiet_work",
                                      "stay_quiet", "save_note"}


def test_smart_prompt_teaches_the_four_tools():
    text = smart_instructions({"name": "Leo", "grade": 3})
    for word in ("ask_screen", "show_page", "reveal", "point"):
        assert word in text
    assert "commission_board" not in text and "edit_board" not in text
    assert "Never read out a hidden answer" in text
    assert "until you call `show_page`" in text


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
    screen = make_screen(tmp_path)
    assert screen.model_spec() == {"model": "muse-spark-1.3-contributor",
                                   "api": "responses", "reasoning": "minimal"}
