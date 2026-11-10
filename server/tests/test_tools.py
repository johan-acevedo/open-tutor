"""Board tools execute as RPCs to the learner's browser and report what happened."""

import json

from open_tutor.agent import Tutor
from open_tutor.board import Step
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


async def test_show_steps_reaches_the_board_and_is_acknowledged():
    room = FakeRoom()
    t = tutor(room)
    result = await t.show_steps(None, title="Ekvation", steps=[Step(tex="3x + 5 = 20"), Step(tex="3x = 15", op="-5")])
    assert "b1 is now visible" in result
    identity, method, payload = room.local_participant.calls[0]
    assert (identity, method, payload["id"], payload["kind"]) == ("learner-1", "board.show", "b1", "steps")
    assert payload["steps"][1] == {"tex": "3x = 15", "op": "-5"}
    assert await t.focus_step(None, item_id="b1", step=1) == "Highlighted."
    assert room.local_participant.calls[1][1:] == ("board.focus", {"id": "b1", "step": 1})


async def test_a_board_that_does_not_acknowledge_is_reported_to_the_model():
    t = tutor(FakeRoom(error=TimeoutError("no reply")))
    assert "could not show" in await t.show_text(None, title="Ord", markdown="fotosyntes")
    t = tutor(FakeRoom(reply='{"ok":false}'))
    assert "could not show" in await t.show_text(None, title="Ord", markdown="fotosyntes")


async def test_invalid_tool_payload_is_rejected_before_the_board():
    room = FakeRoom()
    result = await tutor(room).show_steps(None, title="Tom", steps=[])
    assert result.startswith("Invalid steps") and room.local_participant.calls == []


async def test_a_new_session_starts_clean():
    first_room, second_room = FakeRoom(), FakeRoom()
    first = tutor(first_room, "learner-a")
    await first.show_text(None, title="Ett", markdown="1")
    await first.show_text(None, title="Två", markdown="2")
    notes = [{"at": "2026-11-04T10:00:00+00:00", "topic": "Ekvationer", "next": "fler ekvationer"}]
    second = tutor(second_room, "learner-b", {"name": "Leo", "grade": 7, "notes": notes})
    await second.show_text(None, title="Nytt", markdown="3")
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
    assert "only when you call a board tool" in text and "Never describe or narrate a tool call" in text


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


async def test_announced_html_replaces_the_placeholder_in_place():
    room = FakeRoom()
    t = tutor(room)
    announced = await t.announce_drawing(None, title="Kretslopp")
    assert 'pending_id="b1"' in announced
    result = await t.show_html(None, title="Kretslopp", html="<p>hej</p>", pending_id="b1")
    assert "b1 is now visible" in result
    assert [c[1] for c in room.local_participant.calls] == ["board.show", "board.update"]
    _, _, payload = room.local_participant.calls[1]
    assert payload["id"] == "b1" and payload["kind"] == "html"


async def test_unannounced_svg_still_shows_directly():
    room = FakeRoom()
    result = await tutor(room).show_svg(None, title="Triangel", svg='<svg viewBox="0 0 10 10"></svg>')
    assert "b1 is now visible" in result
    assert [c[1] for c in room.local_participant.calls] == ["board.show"]


async def test_a_failed_final_board_removes_its_placeholder():
    room = flaky_room(None, TimeoutError("no reply"))  # announce works, the update times out
    t = tutor(room)
    await t.announce_drawing(None, title="Kretslopp")
    result = await t.show_html(None, title="Kretslopp", html="<p>hej</p>", pending_id="b1")
    assert "placeholder was removed" in result and "Explain in words" in result
    assert [c[1] for c in room.local_participant.calls] == ["board.show", "board.update", "board.remove"]
    assert room.local_participant.calls[2][2] == {"id": "b1"}


async def test_rejected_drawing_removes_its_placeholder():
    room = FakeRoom()
    t = tutor(room)
    await t.announce_drawing(None, title="Kretslopp")
    result = await t.show_svg(None, title="Kretslopp", svg="x" * 70000, pending_id="b1")
    assert result.startswith("Invalid svg") and "placeholder was removed" in result
    assert [c[1] for c in room.local_participant.calls] == ["board.show", "board.remove"]


async def test_a_failed_announcement_leaves_no_placeholder_behind():
    room = flaky_room(TimeoutError("no reply"))
    result = await tutor(room).announce_drawing(None, title="Kretslopp")
    assert "not visible" in result and "pending_id" not in result
    assert [c[1] for c in room.local_participant.calls] == ["board.show"]
