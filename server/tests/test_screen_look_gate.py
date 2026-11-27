"""Which pages get the vision ``look`` pass (2026-11-27).

In a real family call the look spent 3.6-4.0 s on two clean text/mindmap
pages (no lint, nothing to fix) and then had no budget left for the two
diagram pages that needed it (``skipped_budget``). A clean page with nothing
spatial on it now skips the look at once (``skipped_simple``), and a visual
page gets a slightly larger soft target (``VISUAL_LOOK_TARGET_S``).
"""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from open_tutor.screen import (
    LOOK_SKIPPED_SIMPLE,
    PAGE_TARGET_S,
    VISUAL_LOOK_TARGET_S,
    Screen,
    page_needs_visual_look,
)

TEXT_PAGE = "<h1>Delar</h1><ot-card><p>Ett bråk har täljare och nämnare.</p></ot-card>"
GRAPH_PAGE = '<h1>Linjen</h1><ot-graph x="-5 5" y="-5 5"><ot-line from="0 0" to="2 4"></ot-line></ot-graph>'


def make_screen(tmp_path, **kwargs):
    kwargs.setdefault("render_page", AsyncMock(return_value=(b"PNG", [])))
    return Screen({"name": "Test", "grade": 4}, tmp_path / "pages", **kwargs)


def outcome(tmp_path, job="s1"):
    meta = json.loads((tmp_path / "pages" / job / "meta.json").read_text())
    return meta["repair"]["look_outcome"]


def counting_model(body, looks):
    async def model(system, user, images, look_png):
        if look_png is not None:
            looks.append(user)
            return "OK"
        return body
    return model


@pytest.mark.parametrize("body", [
    GRAPH_PAGE,
    '<ot-map center="59.3 18.1"></ot-map>',
    '<ot-image query="animal cell diagram"></ot-image>',
    '<ot-chart type="bar"></ot-chart>',
    '<ot-clock time="6:30"></ot-clock>',
    '<ot-fraction n="1" d="2"></ot-fraction>',
    '<ot-numberline from="0" to="10"></ot-numberline>',
    '<ot-balance></ot-balance>',
    '<ot-written op="+"></ot-written>',
    '<ot-cycle></ot-cycle>',
    '<svg viewBox="0 0 10 10"></svg>',
    '<OT-GRAPH></OT-GRAPH>',
    # An answer still to be given: the look's answer-leak check is worth it.
    '<p>3x = 15</p><ot-answer id="svar" label="x ="></ot-answer>',
    '<p lang="en">How <ot-gap id="g1" answer="much"></ot-gap> is it?</p>',
    '<ot-hidden id="facit">x = 5</ot-hidden>',
    '<ot-choice id="val"></ot-choice>',
    '<ot-steps><ot-step note="÷3" later>x = 5</ot-step></ot-steps>',
])
def test_spatial_pages_need_a_look(body):
    assert page_needs_visual_look(body)


@pytest.mark.parametrize("body", [
    "",
    TEXT_PAGE,
    "<ot-steps><ot-step>Ett</ot-step></ot-steps>",
    "<ot-mindmap><ot-node>Fotosyntes</ot-node></ot-mindmap>",
    "<table><tr><td>1</td></tr></table>",
    "<ot-quiz><ot-option>A</ot-option></ot-quiz>",
    "<p>Rita en graf i häftet.</p>",  # the word, not the tag
    '<p class="later-note">Vi tar det sen.</p>',  # not a later attribute
])
def test_text_pages_do_not(body):
    assert not page_needs_visual_look(body)


def test_the_visual_target_is_more_generous_than_the_page_target():
    assert VISUAL_LOOK_TARGET_S > PAGE_TARGET_S


async def test_a_clean_text_page_skips_the_look(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    looks = []
    screen = make_screen(tmp_path, model_call=counting_model(TEXT_PAGE, looks))
    screen.ask("En sida om bråk")
    await screen.wait_idle()
    assert outcome(tmp_path) == LOOK_SKIPPED_SIMPLE == "skipped_simple"
    assert looks == []
    await screen.aclose()


async def test_a_clean_visual_page_is_looked_at(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "1")
    looks = []
    screen = make_screen(tmp_path, model_call=counting_model(GRAPH_PAGE, looks))
    screen.ask("En graf")
    await screen.wait_idle()
    assert outcome(tmp_path) == "ok"
    assert len(looks) == 1
    await screen.aclose()


async def test_always_still_looks_at_a_text_page(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "always")
    looks = []
    screen = make_screen(tmp_path, model_call=counting_model(TEXT_PAGE, looks))
    screen.ask("En sida om bråk")
    await screen.wait_idle()
    assert outcome(tmp_path) == "ok"
    assert len(looks) == 1
    await screen.aclose()


async def test_off_stays_off_for_a_visual_page(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    looks = []
    screen = make_screen(tmp_path, model_call=counting_model(GRAPH_PAGE, looks))
    screen.ask("En graf")
    await screen.wait_idle()
    assert outcome(tmp_path) == "off"
    assert looks == []
    await screen.aclose()


async def test_a_text_page_with_lint_still_goes_to_the_retry(tmp_path, monkeypatch):
    """The gate only skips the look; known lint is corrected as before."""
    monkeypatch.setenv("SCREEN_LOOK", "1")
    dense = {"kind": "dense", "msg": "text is only 14.75px on this screen (minimum 16px)."}
    renders = []

    async def render(body, patch, history, w, h):
        renders.append(body)
        return (b"PNG1", [dense]) if len(renders) == 1 else (b"PNG2", [])

    async def model(system, user, images, look_png):
        assert look_png is None
        return "<h1>Delar</h1><p>Kort.</p>" if "still reports" in user else TEXT_PAGE

    screen = make_screen(tmp_path, model_call=model, render_page=render,
                         get_pane_size=lambda: (370, 610))
    screen.ask("En sida om bråk")
    await screen.wait_idle()
    assert outcome(tmp_path) == "skipped_lint"
    await screen.aclose()


async def test_a_visual_page_uses_the_visual_target(tmp_path, monkeypatch):
    """A look that would not fit PAGE_TARGET_S still runs on a visual page
    when it fits VISUAL_LOOK_TARGET_S."""
    monkeypatch.setenv("SCREEN_LOOK", "1")
    monkeypatch.setattr("open_tutor.screen.FINAL_RENDER_RESERVE_S", 0.01)
    monkeypatch.setattr("open_tutor.screen.MIN_OPTIONAL_STEP_S", 0.05)
    monkeypatch.setattr("open_tutor.screen.PAGE_TARGET_S", 0.07)
    monkeypatch.setattr("open_tutor.screen.VISUAL_LOOK_TARGET_S", 5.0)

    async def slow_write(body, looks):
        async def model(system, user, images, look_png):
            if look_png is not None:
                looks.append(user)
                return "OK"
            await asyncio.sleep(0.04)
            return body
        return model

    looks: list[str] = []
    screen = make_screen(tmp_path, model_call=await slow_write(GRAPH_PAGE, looks), timeout=8.0)
    screen.ask("En graf")
    await screen.wait_idle()
    assert outcome(tmp_path) == "ok" and len(looks) == 1
    await screen.aclose()
