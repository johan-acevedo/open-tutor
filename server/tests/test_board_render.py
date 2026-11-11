"""Commissioned board size, CSP parity with the served board, screenshot policy."""

import asyncio
import json
import pathlib

import open_tutor.board_model as board_model
from open_tutor.agent import Tutor
from open_tutor.board_model import HTML_CSP, apply_csp


async def test_failed_restore_does_not_tell_tutor_the_board_was_restored(monkeypatch):
    tutor, _ = await make_tutor_with_board(FakeRoom())
    original = tutor.boards["b1"]

    async def fail_render(*args, **kwargs):
        raise TimeoutError("model unavailable")

    async def no_ack(*args, **kwargs):
        return False

    monkeypatch.setattr(board_model, "render_board", fail_render)
    monkeypatch.setattr(tutor, "_rpc", no_ack)
    result = await tutor.edit_board(None, changes="Make the line orange")
    assert "was restored" not in result
    assert "could not confirm" in result
    assert tutor.boards["b1"] is original


async def test_oversized_edit_restores_original_instead_of_truncating_html(monkeypatch):
    room = FakeRoom()
    tutor, _ = await make_tutor_with_board(room)
    original = tutor.boards["b1"]

    async def oversized(*args, **kwargs):
        return {"html": "<html>" + "x" * 100001 + "</html>", "note": "", "png": None}

    async def no_seen(*args, **kwargs):
        raise AssertionError("An invalid edit must not be described as visible")

    monkeypatch.setattr(board_model, "render_board", oversized)
    monkeypatch.setattr(tutor, "add_board_seen", no_seen)
    result = await tutor.edit_board(None, changes="Make the line orange")
    assert "Invalid revised board" in result
    assert tutor.boards["b1"] is original
    assert room.local_participant.calls[-1][2]["html"] == original.html


async def test_concurrent_changes_to_one_board_use_the_latest_successful_revision(monkeypatch):
    tutor, _ = await make_tutor_with_board(FakeRoom())

    async def revise(need, background, **kwargs):
        html = kwargs["previous_html"]
        await asyncio.sleep(0)
        return {"html": html.replace("</body>", f"<p>{need}</p></body>"), "note": "", "png": None}

    async def no_seen(*args, **kwargs):
        pass

    monkeypatch.setattr(board_model, "render_board", revise)
    monkeypatch.setattr(tutor, "add_board_seen", no_seen)
    await asyncio.gather(
        tutor.edit_board(None, changes="orange"),
        tutor.edit_board(None, changes="thicker"),
    )
    assert "orange" in tutor.boards["b1"].html
    assert "thicker" in tutor.boards["b1"].html


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


async def test_commissioned_dimensions_use_latest_ack_and_freeze_during_render():
    # New handshake: placeholder reserves the initial height, then w/h/device
    # freeze AFTER its ack (settled teaching size), before rendering. Later
    # board-size events during the model await must not change this board.
    class AckParticipant(FakeParticipant):
        async def perform_rpc(self, *, destination_identity, method, payload, response_timeout):
            self.calls.append((destination_identity, method, json.loads(payload)))
            if method == "board.show":
                return json.dumps({"ok": True, "board": {"w": 1200, "h": 900, "device": "desktop"}})
            return '{"ok":true}'

    room = FakeRoom()
    room.local_participant = AckParticipant()
    tutor = Tutor({"name": "Leo", "grade": 7}, room, board={"w": 900, "h": 600, "device": "desktop"})
    tutor.child_identity = "learner-1"
    seen_kw: dict = {}

    async def fake_render(need, background, learner_name="", **kw):
        seen_kw.update(kw)
        # Late arrival: a resize event lands during the model await.
        tutor.update_board_size(500, 500, "desktop")
        return {"html": "<!doctype html><html><body><p>Hej</p></body></html>", "note": "n", "png": None}

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
    # Placeholder used the initial height; renderer and final item use the ack dims.
    by_method = {m: p for _, m, p in room.local_participant.calls}
    assert by_method["board.show"]["height"] == 600
    assert (seen_kw["board_w"], seen_kw["board_h"]) == (1200, 900)
    assert (by_method["board.update"]["width"], by_method["board.update"]["height"]) == (1200, 900)
    # The late 500x500 event did not leak into this board (frozen during render).
    assert seen_kw["board_w"] != 500


async def test_plain_ok_ack_still_works_without_board_dims():
    # Existing fallback peers return {ok:true} with no board key.
    pending, final = await commission({"w": 900, "h": 600, "device": "desktop"})
    assert pending["height"] == 600 and final["height"] == 600
    assert final["width"] == 900


async def make_tutor_with_board(room, html="<p>v1</p>", board=None):
    tutor = Tutor({"name": "Leo", "grade": 7}, room,
                  board=board or {"w": 900, "h": 600, "device": "desktop"})
    tutor.child_identity = "learner-1"
    seen: dict = {}

    async def fake_render(need, background, learner_name="", **kw):
        seen.update(kw)
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
    return tutor, seen


async def test_create_then_edit_keeps_id_and_passes_prior_html():
    room = FakeRoom()
    tutor, _ = await make_tutor_with_board(room, html="<p>v1</p>")
    assert tutor.current_board_id == "b1"
    original = tutor.boards["b1"].html
    assert len(tutor.boards) == 1
    captured: dict = {}

    async def fake_edit(need, background, learner_name="", **kw):
        captured.update(need=need, kw=dict(kw))
        assert kw.get("previous_html") == original
        return {"html": "<!doctype html><html><body><p>v2</p></body></html>",
                "note": "changed", "png": None}

    async def noseen(*a, **k):
        pass

    board_model.render_board, real = fake_edit, board_model.render_board
    tutor.add_board_seen, real_seen = noseen, tutor.add_board_seen
    try:
        result = await tutor.edit_board(None, changes="make it v2")
    finally:
        board_model.render_board = real
        tutor.add_board_seen = real_seen
    assert "revised board is on screen" in result
    assert "b1" in result
    # Same id, no new ids consumed, still one saved board.
    assert tutor.current_board_id == "b1"
    assert len(tutor.boards) == 1
    assert "v2" in tutor.boards["b1"].html
    methods = [m for _, m, _ in room.local_participant.calls]
    assert methods[-2:] == ["board.update", "board.update"]  # pending + revised
    final = room.local_participant.calls[-1][2]
    assert final["id"] == "b1" and final["kind"] == "html"
    assert "v2" in final["html"]


async def test_edit_preserves_baseline_dimensions():
    room = FakeRoom()
    tutor, _ = await make_tutor_with_board(room, html="<p>v1</p>",
                                           board={"w": 900, "h": 600, "device": "desktop"})
    saved = tutor.boards["b1"]
    assert (saved.width, saved.height) == (900, 600)
    # Pane resizes before the edit; the edit must still use the baseline.
    tutor.update_board_size(390, 844, "mobile")
    seen_kw: dict = {}

    async def fake_edit(need, background, learner_name="", **kw):
        seen_kw.update(kw)
        return {"html": "<!doctype html><html><body><p>v2</p></body></html>",
                "note": "n", "png": None}

    async def noseen(*a, **k):
        pass

    board_model.render_board, real = fake_edit, board_model.render_board
    tutor.add_board_seen, real_seen = noseen, tutor.add_board_seen
    try:
        await tutor.edit_board(None, changes="change it")
    finally:
        board_model.render_board = real
        tutor.add_board_seen = real_seen
    assert (seen_kw["board_w"], seen_kw["board_h"]) == (900, 600)
    final = room.local_participant.calls[-1][2]
    assert (final["width"], final["height"]) == (900, 600)


async def test_edit_explicit_and_implicit_target():
    room = FakeRoom()
    tutor = Tutor({"name": "Leo", "grade": 7}, room, board={"w": 900, "h": 600})
    tutor.child_identity = "learner-1"
    bodies = ["<p>one</p>", "<p>two</p>"]

    async def fake_render(need, background, learner_name="", **kw):
        return {"html": f"<!doctype html><html><body>{bodies.pop(0)}</body></html>",
                "note": "n", "png": None}

    async def noseen(*a, **k):
        pass

    board_model.render_board, real = fake_render, board_model.render_board
    tutor.add_board_seen, real_seen = noseen, tutor.add_board_seen
    try:
        await tutor.commission_board(None, need="x", background="y")
        await tutor.commission_board(None, need="x", background="y")
    finally:
        board_model.render_board = real
        tutor.add_board_seen = real_seen
    assert sorted(tutor.boards) == ["b1", "b2"]
    assert tutor.current_board_id == "b2"
    seen_ids: list = []

    async def fake_edit(need, background, learner_name="", **kw):
        prev = kw.get("previous_html") or ""
        seen_ids.append("b1" if "one" in prev or "one-revised" in prev else "b2" if "two" in prev else "?")
        tag = "one-revised" if "one" in prev else "two-revised"
        return {"html": f"<!doctype html><html><body><p>{tag}</p></body></html>",
                "note": "n", "png": None}

    board_model.render_board, real2 = fake_edit, board_model.render_board
    try:
        r1 = await tutor.edit_board(None, changes="fix first", board_id="b1")
        assert "b1" in r1
        assert "one-revised" in tutor.boards["b1"].html
        assert "two" in tutor.boards["b2"].html  # untouched
        r2 = await tutor.edit_board(None, changes="fix again")  # implicit: most recent (b1)
        assert tutor.current_board_id == "b1"
        assert seen_ids == ["b1", "b1"]
        assert "one-revised" in tutor.boards["b1"].html
        assert "two" in tutor.boards["b2"].html
    finally:
        board_model.render_board = real2


async def test_edit_unknown_or_missing_board_renders_nothing():
    room = FakeRoom()
    tutor = Tutor({"name": "Leo", "grade": 7}, room)
    tutor.child_identity = "learner-1"
    called = False

    async def boom(*a, **k):
        nonlocal called
        called = True
        raise AssertionError("must not render")

    board_model.render_board, real = boom, board_model.render_board
    try:
        r = await tutor.edit_board(None, changes="x")
    finally:
        board_model.render_board = real
    assert "no board" in r.lower() and not called
    assert room.local_participant.calls == []
    # Unknown id with existing boards also renders nothing.
    room2 = FakeRoom()
    tutor2, _ = await make_tutor_with_board(room2)
    n_calls = len(room2.local_participant.calls)
    board_model.render_board, real = boom, board_model.render_board
    try:
        r2 = await tutor2.edit_board(None, changes="x", board_id="b99")
    finally:
        board_model.render_board = real
    assert "unknown" in r2.lower() and not called
    assert len(room2.local_participant.calls) == n_calls


async def test_edit_model_failure_restores_original():
    room = FakeRoom()
    tutor, _ = await make_tutor_with_board(room, html="<p>orig</p>")
    original_html = tutor.boards["b1"].html

    async def boom(*a, **k):
        raise TimeoutError("silent")

    async def noseen(*a, **k):
        raise AssertionError("must not feed back a failed edit")

    board_model.render_board, real = boom, board_model.render_board
    tutor.add_board_seen, real_seen = noseen, tutor.add_board_seen
    try:
        r = await tutor.edit_board(None, changes="break it")
    finally:
        board_model.render_board = real
        tutor.add_board_seen = real_seen
    assert "restored" in r.lower()
    assert tutor.boards["b1"].html == original_html
    restored = room.local_participant.calls[-1][2]
    assert restored["id"] == "b1" and "orig" in restored["html"]


async def test_edit_invalid_output_restores_original():
    room = FakeRoom()
    tutor, _ = await make_tutor_with_board(room, html="<p>orig</p>")
    original_html = tutor.boards["b1"].html

    async def empty(*a, **k):
        return {"html": "<p>no doctype</p>", "note": "", "png": None}

    async def noseen(*a, **k):
        raise AssertionError("must not feed back")

    board_model.render_board, real = empty, board_model.render_board
    tutor.add_board_seen, real_seen = noseen, tutor.add_board_seen
    try:
        r = await tutor.edit_board(None, changes="break it")
    finally:
        board_model.render_board = real
        tutor.add_board_seen = real_seen
    assert "invalid" in r.lower() and "restored" in r.lower()
    assert tutor.boards["b1"].html == original_html


async def test_edit_display_failure_restores_original():
    room = FakeRoom()
    tutor, _ = await make_tutor_with_board(room, html="<p>orig</p>")
    original_html = tutor.boards["b1"].html
    orig_rpc = tutor._rpc
    calls = [0]

    async def flaky(method, payload):
        # Pending update ok, revised update fails, restore ok.
        if method == "board.update" and payload.get("kind") == "html" and "revised" in payload.get("html", ""):
            calls[0] += 1
            return False
        return await orig_rpc(method, payload)

    async def fake_edit(need, background, learner_name="", **kw):
        return {"html": "<!doctype html><html><body><p>revised</p></body></html>",
                "note": "n", "png": None}

    async def noseen(*a, **k):
        raise AssertionError("must not feed back")

    board_model.render_board, real = fake_edit, board_model.render_board
    tutor.add_board_seen, real_seen = noseen, tutor.add_board_seen
    tutor._rpc = flaky  # type: ignore[method-assign]
    try:
        r = await tutor.edit_board(None, changes="revise")
    finally:
        board_model.render_board = real
        tutor.add_board_seen = real_seen
        tutor._rpc = orig_rpc  # type: ignore[method-assign]
    assert "failed to appear" in r.lower() and "restored" in r.lower()
    assert calls[0] == 1
    assert tutor.boards["b1"].html == original_html
    restored = room.local_participant.calls[-1][2]
    assert "orig" in restored["html"]


async def test_future_edit_uses_latest_successful_html():
    room = FakeRoom()
    tutor, _ = await make_tutor_with_board(room, html="<p>v1</p>")
    seen_prev: list = []

    async def fake_edit(need, background, learner_name="", **kw):
        seen_prev.append(kw.get("previous_html") or "")
        tag = "v2" if "v1" in seen_prev[-1] else "v3"
        return {"html": f"<!doctype html><html><body><p>{tag}</p></body></html>",
                "note": "n", "png": None}

    async def noseen(*a, **k):
        pass

    board_model.render_board, real = fake_edit, board_model.render_board
    tutor.add_board_seen, real_seen = noseen, tutor.add_board_seen
    try:
        await tutor.edit_board(None, changes="to v2")
        await tutor.edit_board(None, changes="to v3")
    finally:
        board_model.render_board = real
        tutor.add_board_seen = real_seen
    assert "v1" in seen_prev[0] and "v2" in seen_prev[1]
    assert "v3" in tutor.boards["b1"].html


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
