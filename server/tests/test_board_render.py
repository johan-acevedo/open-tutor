"""Commissioned board size, CSP parity with the served board, screenshot policy."""

import json
import pathlib

import open_tutor.board_model as board_model
from open_tutor.agent import Tutor
from open_tutor.board_model import HTML_CSP, apply_csp


class FakeParticipant:
    def __init__(self):
        self.calls = []

    async def perform_rpc(self, *, destination_identity, method, payload, response_timeout):
        self.calls.append((destination_identity, method, json.loads(payload)))
        return '{"ok":true}'

    async def set_attributes(self, attributes):
        pass


class FakeRoom:
    def __init__(self):
        self.local_participant = FakeParticipant()


async def commission(board, html="<p>Hej</p>"):
    room = FakeRoom()
    tutor = Tutor({"name": "Leo", "grade": 7}, room, board=board)
    tutor.child_identity = "learner-1"

    async def fake_render(need, background, learner_name="", **kw):
        return {"html": f"<!doctype html><html><body>{html}</body></html>",
                "note": "n", "png": None}

    async def noseen(*a, **k):
        pass

    board_model.render_board, real = fake_render, board_model.render_board
    tutor.add_board_seen, real_seen = noseen, tutor.add_board_seen
    try:
        result = await tutor.commission_board(None, need="x", background="y")
    finally:
        board_model.render_board = real
        tutor.add_board_seen = real_seen
    assert "on screen now" in result
    by_method = {m: p for _, m, p in room.local_participant.calls}
    return by_method["board.show"], by_method["board.update"]


async def test_commissioned_frame_height_matches_the_pane():
    # Desktop pane: the frame fits the commissioned size instead of a fixed 640.
    pending, final = await commission({"w": 1280, "h": 800, "device": "desktop"})
    assert pending["height"] == 800 and final["height"] == 800
    assert final["width"] == 1280
    assert pending["id"] == final["id"] and final["kind"] == "html"


async def test_tall_panes_no_longer_fail_validation():
    # Old height cap (900) would reject this pane with "Invalid board".
    pending, final = await commission({"w": 1920, "h": 1200, "device": "desktop"})
    assert (pending["height"], final["height"]) == (1200, 1200)
    assert final["width"] == 1920


async def test_phone_pane_height_matches():
    pending, final = await commission({"w": 390, "h": 844, "device": "mobile"})
    assert (pending["height"], final["height"]) == (844, 844)
    assert final["width"] == 390


async def test_commissioned_dimensions_frozen_before_awaits():
    # A board-size update landing during the placeholder RPC must not change
    # what the model renders or what the finished frame carries.
    room = FakeRoom()
    tutor = Tutor({"name": "Leo", "grade": 7}, room, board={"w": 900, "h": 600, "device": "desktop"})
    tutor.child_identity = "learner-1"
    seen_kw: dict = {}

    orig_rpc = tutor._rpc

    async def fake_render(need, background, learner_name="", **kw):
        seen_kw.update(kw)
        return {"html": "<!doctype html><html><body><p>Hej</p></body></html>", "note": "n", "png": None}

    async def shifting_rpc(method, payload):
        # Arrival->teaching layout shift reports a new size mid-commission.
        tutor.update_board_size(1200, 900, "desktop")
        return await orig_rpc(method, payload)

    async def noseen(*a, **k):
        pass

    board_model.render_board, real = fake_render, board_model.render_board
    tutor.add_board_seen, real_seen = noseen, tutor.add_board_seen
    tutor._rpc = shifting_rpc  # type: ignore[method-assign]
    try:
        result = await tutor.commission_board(None, need="x", background="y")
    finally:
        board_model.render_board = real
        tutor.add_board_seen = real_seen
    assert "on screen now" in result
    assert (seen_kw["board_w"], seen_kw["board_h"]) == (900, 600)
    by_method = {m: p for _, m, p in room.local_participant.calls}
    assert (by_method["board.update"]["width"], by_method["board.update"]["height"]) == (900, 600)
    assert by_method["board.show"]["height"] == 600


def test_csp_matches_the_served_board():
    cards = pathlib.Path(__file__).resolve().parents[2] / "web/src/components/Cards.tsx"
    assert HTML_CSP in cards.read_text(), "board_model.HTML_CSP drifted from Cards.tsx"
    assert "style-src 'unsafe-inline' https://cdn.jsdelivr.net" in HTML_CSP
    assert "font-src https://cdn.jsdelivr.net" in HTML_CSP
    assert "img-src data: https:" in HTML_CSP


def test_apply_csp_inserts_after_head():
    html = "<!doctype html><html><head><title>x</title></head><body></body></html>"
    out = apply_csp(html)
    assert out.startswith("<!doctype html><html><head><meta http-equiv=\"Content-Security-Policy\"")
    assert HTML_CSP in out and out.count("Content-Security-Policy") == 1


def test_apply_csp_without_head_falls_back_to_start():
    out = apply_csp("<p>no document</p>")
    assert out.startswith("<meta http-equiv=\"Content-Security-Policy\"")
