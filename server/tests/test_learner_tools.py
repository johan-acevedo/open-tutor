"""The tutor learns the grade and switches students mid-call.

set_learner_grade / switch_student use acknowledged worker → browser RPCs
(learner.setGrade, learner.switch). The browser owns the profiles; a failed
call leaves the call exactly as it was. A switch ends this lesson exactly
like Avsluta and the next session starts fresh — nothing of lesson A
survives. Unknown grades default to the band; band-3 adults are never asked
for one.
"""

import asyncio
import json

import pytest
from livekit.agents import StopResponse

from open_tutor import prompt
from open_tutor.agent import (
    LEARNER_RPC_SET_GRADE,
    LEARNER_RPC_SWITCH,
    Tutor,
)


class RpcFailed(Exception):
    pass


class FakeParticipant:
    def __init__(self, replies=None, error=None):
        self.calls: list[tuple[str, dict]] = []
        self.replies = replies or {}
        self.error = error

    async def perform_rpc(self, *, destination_identity, method, payload, response_timeout):
        self.calls.append((method, json.loads(payload)))
        if self.error is not None:
            raise self.error
        if method in self.replies:
            reply = self.replies[method]
            return reply if isinstance(reply, str) else json.dumps(reply)
        return '{"ok":true}'


class FakeRoom:
    def __init__(self, **kwargs):
        self.local_participant = FakeParticipant(**kwargs)


class FakeCtx:
    pass


def tutor(learner=None, **room_kwargs):
    t = Tutor(learner or {"name": "Leo"}, FakeRoom(**room_kwargs))
    t.child_identity = "learner-1"
    t.end_event = asyncio.Event()
    return t


async def test_set_learner_grade_acks_then_updates():
    t = tutor({"id": "p1", "name": "Leo", "grade": None})
    result = await Tutor.set_learner_grade(t, FakeCtx(), 8)
    assert t.learner["grade"] == 8
    assert "8" in result
    [(method, payload)] = t.room.local_participant.calls
    assert method == LEARNER_RPC_SET_GRADE == "learner.setGrade"
    assert payload == {"profileId": "p1", "grade": 8}


@pytest.mark.parametrize("bad", [0, 13, -1, "fyra"])
async def test_set_learner_grade_rejects_non_years(bad):
    t = tutor({"name": "Leo", "grade": None})
    result = await Tutor.set_learner_grade(t, FakeCtx(), bad)
    assert t.learner["grade"] is None
    assert t.room.local_participant.calls == []
    assert "1-12" in result or "school year" in result


async def test_set_learner_grade_failure_saves_nothing():
    t = tutor({"id": "p1", "name": "Leo", "grade": None}, error=RpcFailed("gone"))
    result = await Tutor.set_learner_grade(t, FakeCtx(), 8)
    assert t.learner["grade"] is None
    assert "could not store" in result
    assert t.room.local_participant.calls == [(LEARNER_RPC_SET_GRADE, {"profileId": "p1", "grade": 8})]


async def test_switch_student_acks_then_ends_the_lesson():
    t = tutor({"id": "pA", "name": "Elsa", "grade": 4, "notes": [{"topic": "bråk"}]},
              replies={LEARNER_RPC_SWITCH: {"ok": True, "profile": {"id": "pB", "name": "Leo", "grade": None}}})
    with pytest.raises(StopResponse):
        await Tutor.switch_student(t, FakeCtx(), "Leo")
    assert t.end_event.is_set()
    # Nothing of A is carried over: the lesson ends as A, B starts fresh.
    assert t.learner["name"] == "Elsa"
    assert t.learner["grade"] == 4
    [(method, payload)] = t.room.local_participant.calls
    assert method == LEARNER_RPC_SWITCH == "learner.switch"
    assert payload == {"name": "Leo"}


async def test_switch_student_failure_stays_as_a():
    t = tutor({"name": "Elsa", "grade": 4}, error=RpcFailed("gone"))
    result = await Tutor.switch_student(t, FakeCtx(), "Leo")
    assert "Elsa" in result and "did not go through" in result
    assert not t.end_event.is_set()
    assert t.learner["name"] == "Elsa"
    methods = [method for method, _ in t.room.local_participant.calls]
    # Nothing was armed: exactly one RPC went out, the lesson ends as A.
    assert methods == [LEARNER_RPC_SWITCH]


async def test_switch_student_needs_a_name():
    t = tutor({"name": "Elsa"})
    result = await Tutor.switch_student(t, FakeCtx(), "  ")
    assert t.learner["name"] == "Elsa"
    assert t.room.local_participant.calls == []
    assert not t.end_event.is_set()


def test_unknown_grade_defaults_to_ak_1_6():
    text = prompt.learner_context({"name": "Leo", "grade": None})
    assert "not known yet" in text and "set_learner_grade" in text
    assert "åk 1–6" in text


def test_unknown_grade_defaults_to_hogstadiet_on_band_2():
    text = prompt.learner_context({"name": "Leo", "grade": None, "band": "middle"})
    assert "not known yet" in text and "högstadiet" in text


def test_band_3_learns_gymnasiet_year_or_adult():
    text = prompt.learner_context({"name": "Bo", "grade": None, "band": "upper"})
    assert "gymnasiet student or an adult" in text
    assert "Only adults skip the school year" in text


def test_known_grade_still_wins_over_the_band():
    text = prompt.learner_context({"name": "Leo", "grade": 8, "band": "middle"})
    assert "årskurs 8" in text and "not known yet" not in text


def test_band_3_gets_greeting_without_school_framing():
    line, _ = prompt.greeting_line({"name": "Bo", "band": "upper"}, index=0)
    assert "Bo" in line and "Räven" in line
    assert "läxor" not in line and "skol" not in line


def test_prompt_bans_grade_forms_and_midcall_switching_rules():
    text = prompt.instructions({"name": "Leo", "grade": None})
    assert "never as a form" in text
    assert "set_learner_grade" in text
    assert "switch_student" in text
