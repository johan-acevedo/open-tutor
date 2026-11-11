"""Board tools execute as RPCs to the learner's browser and report what happened."""

import json

import open_tutor.board_model as board_model
from open_tutor.agent import Tutor
from open_tutor.prompt import instructions


class FakeParticipant:
    def __init__(self, reply='{"ok":true}', error=None):
        self.calls, self.reply, self.error = [], reply, error

    async def perform_rpc(self, *, destination_identity, method, payload, response_timeout):
        self.calls.append((destination_identity, method, json.loads(payload)))
        if self.error:
            raise self.error
        return self.reply

    async def set_attributes(self, attributes):
        pass


class FakeRoom:
    def __init__(self, **kwargs):
        self.local_participant = FakeParticipant(**kwargs)


def tutor(room, identity="learner-1", learner=None):
    t = Tutor(learner or {"name": "Leo", "grade": 7}, room)
    t.child_identity = identity
    return t


async def commission(t, monkeypatch, room, **kwargs):
    seen = {}

    async def fake_render(need, background, learner_name="", **kw):
        seen.update(need=need, background=background)
        return {"html": "<!doctype html><html><body> Hej </body></html>",
                "note": "Enkel hälsningstavla.", "png": b"PNG"}

    async def fake_seen(png, note, label):
        seen.update(png=png, note=note, label=label)

    monkeypatch.setattr(board_model, "render_board", fake_render)
    monkeypatch.setattr(t, "add_board_seen", fake_seen)
    params = {"need": "Leo behöver se en hälsning", "background": "Leo, 7, svenska."}
    params.update(kwargs)
    result = await t.commission_board(None, **params)
    return result, seen
async def test_commissioned_board_reaches_the_board_and_feeds_back(monkeypatch):
    room = FakeRoom()
    t = tutor(room)
    result, seen = await commission(t, monkeypatch, room)
    assert "on screen now" in result
    identity, method, payload = room.local_participant.calls[0]
    assert (identity, method, payload["id"], payload["kind"]) == ("learner-1", "board.show", "b1", "html")
    assert seen["png"] == b"PNG" and "hälsning" in seen["note"].lower()
    assert "Leo behöver se" in seen["need"]


async def test_client_board_size_reaches_the_board_model(monkeypatch):
    room = FakeRoom()
    t = Tutor({"name": "Leo"}, room, board={"w": 390, "h": 844, "device": "mobile"})
    assert (t.board_w, t.board_h, t.board_device) == (390, 844, "mobile")
    sizes = {}

    async def fake_render(need, background, learner_name="", **kw):
        sizes.update(kw)
        return {"html": "<!doctype html><html></html>", "note": "n", "png": None}

    async def noseen(*a, **k):
        pass

    monkeypatch.setattr(board_model, "render_board", fake_render)
    monkeypatch.setattr(t, "add_board_seen", noseen)
    await t.commission_board(None, need="x", background="y")
    assert sizes == {"board_w": 390, "board_h": 844, "device": "mobile"}


async def test_a_board_that_does_not_acknowledge_is_reported_to_the_model(monkeypatch):
    t = tutor(FakeRoom(error=TimeoutError("no reply")))
    result, _ = await commission(t, monkeypatch, None)
    assert "could not show" in result
    t = tutor(FakeRoom(reply='{"ok":false}'))
    result, _ = await commission(t, monkeypatch, None)
    assert "could not show" in result


async def test_a_board_model_failure_is_reported_to_the_model(monkeypatch):
    room = FakeRoom()
    t = tutor(room)

    async def boom(*a, **k):
        raise TimeoutError("board model silent")

    async def noseen(*a, **k):
        raise AssertionError("must not feed back a missing board")

    monkeypatch.setattr(board_model, "render_board", boom)
    monkeypatch.setattr(t, "add_board_seen", noseen)
    result = await t.commission_board(None, need="x", background="y")
    assert "could not be made" in result and "Explain in words" in result
    assert room.local_participant.calls == []


async def test_a_new_session_starts_clean(monkeypatch):
    first_room, second_room = FakeRoom(), FakeRoom()
    first = tutor(first_room, "learner-a")
    await commission(first, monkeypatch, first_room)
    await commission(first, monkeypatch, first_room)
    notes = [{"at": "2026-11-04T10:00:00+00:00", "topic": "Ekvationer", "next": "fler ekvationer"}]
    second = tutor(second_room, "learner-b", {"name": "Leo", "grade": 7, "notes": notes})
    await commission(second, monkeypatch, second_room)
    # Ids restart, RPCs go only to the new learner, and nothing reaches the old room.
    assert [c[2]["id"] for c in second_room.local_participant.calls] == ["b1"]
    assert {c[0] for c in second_room.local_participant.calls} == {"learner-b"}
    assert len(first_room.local_participant.calls) == 2
    assert second.mode == "talking" and second.notes_saved == 0
    # The only thing carried over is the saved note, as context in the instructions.
    assert "Ekvationer" in second.instructions and "Ekvationer" not in first.instructions
    assert len(second.chat_ctx.items) == len(Tutor({"name": "Leo"}, None).chat_ctx.items)


def test_prompt_forbids_narrating_tool_calls():
    text = instructions({"name": "Leo"})
    assert "call the tool in the same turn" in text and "Never describe or narrate a tool call" in text


def test_prompt_announces_slow_drawings_before_writing_them():
    text = instructions({"name": "Leo"})
    assert "announce_drawing" in text and "pending_id" in text
    assert "Vänta lite, jag ritar det åt dig" in text


class FlakyParticipant(FakeParticipant):
    """Fails one RPC per queued exception, so a later step can fail after an earlier one worked."""

    def __init__(self, failures):
        super().__init__()
        self.failures = list(failures)

    async def perform_rpc(self, *, destination_identity, method, payload, response_timeout):
        self.calls.append((destination_identity, method, json.loads(payload)))
        outcome = self.failures.pop(0) if self.failures else None
        if isinstance(outcome, Exception):
            raise outcome
        return self.reply


def flaky_room(*failures):
    room = FakeRoom()
    room.local_participant = FlakyParticipant(failures)
    return room


async def test_announce_drawing_shows_a_pending_placeholder():
    room = FakeRoom()
    result = await tutor(room).announce_drawing(None, title="Vattnets kretslopp")
    assert 'pending_id="b1"' in result and "Ritar" in result
    identity, method, payload = room.local_participant.calls[0]
    assert (identity, method) == ("learner-1", "board.show")
    assert payload == {"id": "b1", "kind": "pending", "title": "Vattnets kretslopp", "height": 360}


async def test_announced_board_replaces_the_placeholder_in_place(monkeypatch):
    room = FakeRoom()
    t = tutor(room)
    announced = await t.announce_drawing(None, title="Kretslopp")
    assert 'pending_id="b1"' in announced
    result, seen = await commission(t, monkeypatch, room, pending_id="b1")
    assert "on screen now" in result
    assert [c[1] for c in room.local_participant.calls] == ["board.show", "board.update"]
    _, _, payload = room.local_participant.calls[1]
    assert payload["id"] == "b1" and payload["kind"] == "html"
    assert seen["label"] == "board b1"


async def test_unannounced_board_still_shows_directly(monkeypatch):
    room = FakeRoom()
    result, _ = await commission(tutor(room), monkeypatch, room)
    assert "on screen now" in result
    assert [c[1] for c in room.local_participant.calls] == ["board.show"]


async def test_a_failed_final_board_removes_its_placeholder(monkeypatch):
    room = flaky_room(None, TimeoutError("no reply"))  # announce works, the update times out
    t = tutor(room)
    await t.announce_drawing(None, title="Kretslopp")
    result, _ = await commission(t, monkeypatch, room, pending_id="b1")
    assert "placeholder was removed" in result and "Explain in words" in result
    assert [c[1] for c in room.local_participant.calls] == ["board.show", "board.update", "board.remove"]
    assert room.local_participant.calls[2][2] == {"id": "b1"}


async def test_rejected_board_removes_its_placeholder(monkeypatch):
    room = FakeRoom()
    t = tutor(room)
    await t.announce_drawing(None, title="Kretslopp")

    async def empty(*a, **k):
        return {"html": "<p>no doctype</p>", "note": "", "png": None}

    async def noseen(*a, **k):
        raise AssertionError("must not feed back")

    monkeypatch.setattr(board_model, "render_board", empty)
    monkeypatch.setattr(t, "add_board_seen", noseen)
    result = await t.commission_board(None, need="x", background="y", pending_id="b1")
    assert "Invalid board" in result and "placeholder was removed" in result
    assert [c[1] for c in room.local_participant.calls] == ["board.show", "board.remove"]


async def test_a_failed_announcement_leaves_no_placeholder_behind():
    room = flaky_room(TimeoutError("no reply"))
    result = await tutor(room).announce_drawing(None, title="Kretslopp")
    assert "not visible" in result and "pending_id" not in result
    assert [c[1] for c in room.local_participant.calls] == ["board.show"]
