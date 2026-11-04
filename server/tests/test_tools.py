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


# ---- diagrams: the worker owns the model, the browser acknowledges what it drew ----------------

import asyncio  # noqa: E402

from open_tutor.diagram import LinkSpec, NodeSpec  # noqa: E402


class SlowParticipant(FakeParticipant):
    """Acknowledges after a delay that shrinks, so an unordered sender would finish out of order."""

    def __init__(self):
        super().__init__()
        self.delay = 0.05

    async def perform_rpc(self, **kwargs):
        await asyncio.sleep(self.delay)
        self.delay = max(0.0, self.delay - 0.02)
        return await super().perform_rpc(**kwargs)


def nodes(*pairs):
    return [NodeSpec(id=i, text=t) for i, t in pairs]


async def test_diagram_grows_through_show_then_update_and_each_call_waits_for_the_board():
    room = FakeRoom()
    t = tutor(room)
    first = await t.show_diagram(None, title="Klimat", nodes=nodes(("klimat", "Klimatförändring")), layout=None)
    assert "Diagram b1 is now visible (revision 1)" in first
    added = await t.add_to_diagram(
        None, "b1", nodes(("vaxt", "Växthusgaser")), [LinkSpec(source="klimat", target="vaxt", label="orsakas av")]
    )
    assert "revision 2" in added and "l1=klimat->vaxt" in added
    focused = await t.focus_diagram(None, "b1", ["vaxt"])
    assert "revision 3" in focused
    calls = room.local_participant.calls
    assert [c[1] for c in calls] == ["board.show", "board.update", "board.update"]
    assert [c[2]["rev"] for c in calls] == [1, 2, 3]
    assert calls[2][2]["focus"] == ["vaxt"] and calls[2][2]["layout"] == "radial"
    assert [n["id"] for n in calls[2][2]["nodes"]] == ["klimat", "vaxt"]
    assert calls[1][2]["links"] == [{"id": "l1", "source": "klimat", "target": "vaxt", "label": "orsakas av"}]


async def test_edit_remove_and_clear_focus_send_the_whole_current_state():
    room = FakeRoom()
    t = tutor(room)
    await t.show_diagram(None, title="Karta", nodes=nodes(("a", "A"), ("b", "B"), ("c", "C")),
                         links=[LinkSpec(source="a", target="b"), LinkSpec(source="a", target="c")])
    await t.edit_diagram(None, "b1", "b", text="Bättre B", role="result")
    await t.remove_from_diagram(None, "b1", ["c"])
    await t.focus_diagram(None, "b1", None)
    last = room.local_participant.calls[-1][2]
    assert [(n["id"], n["text"], n["role"]) for n in last["nodes"]] == [("a", "A", "center"), ("b", "Bättre B", "result")]
    assert [l["id"] for l in last["links"]] == ["l1"] and last["focus"] == [] and last["rev"] == 4


async def test_a_refused_change_never_reaches_the_board_and_tells_the_model_why():
    room = FakeRoom()
    t = tutor(room)
    await t.show_diagram(None, title="Karta", nodes=nodes(("a", "A")))
    sent = len(room.local_participant.calls)
    assert "already used" in await t.add_to_diagram(None, "b1", nodes(("a", "Igen")))
    assert "no node 'z'" in await t.add_to_diagram(None, "b1", links=[LinkSpec(source="a", target="z")])
    assert "no node or link" in await t.focus_diagram(None, "b1", ["z"])
    assert "There is no diagram b9" in await t.add_to_diagram(None, "b9", nodes(("x", "X")))
    assert "No diagram was started" in await t.show_diagram(None, title="Tom", nodes=nodes(("a", "A"), ("a", "B")))
    assert len(room.local_participant.calls) == sent


async def test_an_unacknowledged_diagram_is_never_reported_as_shown_and_is_resent_whole():
    room = FakeRoom(error=TimeoutError("browser did not answer"))
    t = tutor(room)
    result = await t.show_diagram(None, title="Karta", nodes=nodes(("a", "A")))
    assert "did not confirm" in result and "is now visible" not in result
    room.local_participant.error = None  # the connection is back
    healed = await t.add_to_diagram(None, "b1", nodes(("b", "B")), [LinkSpec(source="a", target="b")])
    assert "is now visible (revision 2)" in healed
    calls = room.local_participant.calls
    # The failed first show is followed by a full show (not a bare update) holding both nodes.
    assert [c[1] for c in calls] == ["board.show", "board.show"]
    assert [n["id"] for n in calls[1][2]["nodes"]] == ["a", "b"]
    room.local_participant.reply = '{"ok":false}'
    assert "did not confirm" in await t.focus_diagram(None, "b1", ["a"])


async def test_concurrent_diagram_tools_are_applied_and_sent_in_order():
    room = FakeRoom()
    room.local_participant = SlowParticipant()
    t = tutor(room)
    await t.show_diagram(None, title="Karta", nodes=nodes(("a", "A")))
    await asyncio.gather(
        *(t.add_to_diagram(None, "b1", nodes((f"n{i}", f"Nod {i}")), [LinkSpec(source="a", target=f"n{i}")])
          for i in range(4))
    )
    revs = [c[2]["rev"] for c in room.local_participant.calls]
    assert revs == sorted(revs) == [1, 2, 3, 4, 5]
    assert [n["id"] for n in room.local_participant.calls[-1][2]["nodes"]] == ["a", "n0", "n1", "n2", "n3"]


async def test_the_diagram_rpc_waits_longer_than_other_board_items():
    seen = []

    class Recording(FakeParticipant):
        async def perform_rpc(self, **kwargs):
            seen.append((kwargs["method"], kwargs["response_timeout"]))
            return await super().perform_rpc(**kwargs)

    room = FakeRoom()
    room.local_participant = Recording()
    t = tutor(room)
    await t.show_text(None, title="Ord", markdown="x")
    await t.show_diagram(None, title="Karta", nodes=nodes(("a", "A")))
    assert [timeout for _, timeout in seen] == [6.0, 12.0]


def test_the_tutor_knows_the_diagram_tools_and_the_prompt_keeps_equations_out_of_them():
    names = {tool.id for tool in Tutor({"name": "Leo"}, None).tools}
    assert {"show_diagram", "add_to_diagram", "edit_diagram", "remove_from_diagram", "focus_diagram"} <= names
    assert {"show_steps", "focus_step", "show_svg", "show_html", "show_ideas"} <= names
    text = instructions({"name": "Leo"})
    assert "equations never go into a diagram" in text and "you cannot draw molecules" in text
