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
                                 "save_note", "search_materials", "show_material"}
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
    monkeypatch.delenv("SCREEN_THINKING", raising=False)
    screen = make_screen(tmp_path)
    assert screen.model_spec() == {"model": "muse-spark-1.3-contributor",
                                   "api": "responses", "reasoning": "minimal"}


@pytest.mark.parametrize("model,effort,thinking,host,path", [
    ("deepseek-v4.1-flash", "low", "", "opencode.ai", "/inference/go/openai/v1/chat/completions"),
    ("deepseek-v4.1-flash", "low", "disabled", "opencode.ai", "/inference/go/openai/v1/chat/completions"),
    ("deepseek-v4.1-flash", "low", "enabled", "opencode.ai", "/inference/go/openai/v1/chat/completions"),
    ("gemini-4-hydrogen", "low", "", "generativelanguage.googleapis.com", "/v1beta/openai/chat/completions"),
    ("gemini-4-hydrogen", "medium", "", "generativelanguage.googleapis.com", "/v1beta/openai/chat/completions"),
    ("muse-spark-1.3-contributor", "minimal", "", "opencode.ai", "/inference/go/openai/v1/responses"),
])
def test_page_model_wire_request(tmp_path, monkeypatch, model, effort, thinking, host, path):
    """Exercise the real SDK serializer; the transport returns a recorded response shape."""
    import httpx
    import openai

    for name, value in {"SCREEN_MODEL": model, "SCREEN_REASONING": effort,
                        "SCREEN_THINKING": thinking, "SCREEN_API": "",
                        "GEMINI_API_KEY": "test-google", "OPENCODE_GO_API_KEY": "test-go"}.items():
        monkeypatch.setenv(name, value)
    requests = []

    def handle(request):
        requests.append(request)
        if path.endswith("responses"):
            payload = {"id": "resp_test", "object": "response", "created_at": 0, "model": model,
                       "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                                   "status": "completed", "content": [{"type": "output_text",
                                       "text": "<h1>Hej</h1>", "annotations": []}]}]}
        else:
            payload = {"id": "chat_test", "object": "chat.completion", "created": 0, "model": model,
                       "choices": [{"index": 0, "finish_reason": "stop", "message": {
                           "role": "assistant", "content": "<h1>Hej</h1>"}}]}
        return httpx.Response(200, json=payload)

    real_client = openai.OpenAI
    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        monkeypatch.setattr(openai, "OpenAI", lambda **kw: real_client(**kw, http_client=http))
        screen = make_screen(tmp_path)
        assert screen._default_model_call("System", "Lesson", ["data:image/png;base64,AAA"], b"PNG") == "<h1>Hej</h1>"
    assert len(requests) == 1
    request = requests[0]
    body = json.loads(request.content)
    assert request.url.host == host and request.url.path == path
    assert request.headers["authorization"] == ("Bearer test-google" if host.startswith("generative") else "Bearer test-go")
    assert ("x-opencode-session" in request.headers) == (host == "opencode.ai")
    assert body["model"] == model
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


def test_gemini_page_never_uses_go_key_as_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_MODEL", "gemini-4-hydrogen")
    monkeypatch.setenv("SCREEN_REASONING", "low")
    monkeypatch.setenv("SCREEN_API", "")
    monkeypatch.setenv("SCREEN_THINKING", "")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-go")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY is empty"):
        make_screen(tmp_path)._default_model_call("system", "user", [], None)


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
    assert screen.visible_patches == [first, second]


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
    assert not delivered and not screen.visible_patches
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


# ---- patch images are loaded before the preview screenshot ------------------

class _FakeFrame:
    """A stub for the srcdoc frame: records the wait/evaluate order."""

    def __init__(self, calls, late_issues=None, fail_image_wait=False):
        self.calls = calls
        self.late_issues = late_issues or []
        self.fail_image_wait = fail_image_wait

    async def wait_for_function(self, script, timeout=None):
        self.calls.append(("wait", script, timeout))
        if "ot-image img" in script and self.fail_image_wait:
            raise TimeoutError("still loading")

    async def evaluate(self, script, arg=None):
        self.calls.append(("eval", script, arg))
        if "otReady" in script:
            return None
        if "ot.fontPx" in script:
            return {"fontPx": 18, "issues": []}
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
    _stub_browser(monkeypatch, calls, late_issues=late)
    png, issues = await screen._default_render_page(
        "<h1>Rom</h1>", '<ot-patch target="x"><ot-image src="https://example.invalid/x.jpg"></ot-image></ot-patch>',
        370, 610)
    assert png == b"PNG"
    kinds = [call[0] for call in calls]
    assert kinds.index("screenshot") > kinds.index("wait")
    image_waits = [call for call in calls if call[0] == "wait" and "ot-image img" in call[1]]
    assert len(image_waits) == 1 and image_waits[0][2] == 5000
    assert late[0] in issues


async def test_slow_patch_image_still_screenshots_instead_of_failing(tmp_path, monkeypatch):
    screen = make_screen(tmp_path)
    calls: list = []
    _stub_browser(monkeypatch, calls, fail_image_wait=True)
    png, issues = await screen._default_render_page(
        "<h1>Rom</h1>", '<ot-patch target="x"><ot-image src="https://example.invalid/x.jpg"></ot-image></ot-patch>',
        370, 610)
    assert png == b"PNG" and issues == []


async def test_plain_page_render_does_not_wait_for_patch_images(tmp_path, monkeypatch):
    screen = make_screen(tmp_path)
    calls: list = []
    _stub_browser(monkeypatch, calls)
    png, issues = await screen._default_render_page("<h1>Rom</h1>", None, 370, 610)
    assert png == b"PNG" and issues == []
    assert not [call for call in calls if call[0] == "wait" and "ot-image img" in call[1]]
