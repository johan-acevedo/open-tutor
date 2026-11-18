"""The tutor learns the grade and switches students mid-call.

set_learner_grade / switch_student update the call and ask the browser (which
owns the profiles) to apply the change on topic "profile". Unknown grades
default to the band; band-3 adults are never asked for one.
"""

import json

import pytest

from open_tutor import prompt
from open_tutor.agent import PROFILE_TOPIC, Tutor


class FakeParticipant:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, payload, *, topic, destination_identities=None):
        self.sent.append((topic, payload))


class FakeRoom:
    def __init__(self):
        self.local_participant = FakeParticipant()


class FakeCtx:
    pass


def tutor(learner=None):
    t = Tutor(learner or {"name": "Leo"}, FakeRoom())
    t.child_identity = "learner-1"
    return t


async def test_set_learner_grade_updates_call_and_browser():
    t = tutor({"name": "Leo", "grade": None})
    result = await Tutor.set_learner_grade(t, FakeCtx(), 8)
    assert t.learner["grade"] == 8
    assert "8" in result
    [(topic, payload)] = t.room.local_participant.sent
    assert topic == PROFILE_TOPIC == "profile"
    assert json.loads(payload) == {"grade": 8}


@pytest.mark.parametrize("bad", [0, 13, -1, "fyra"])
async def test_set_learner_grade_rejects_non_years(bad):
    t = tutor({"name": "Leo", "grade": None})
    result = await Tutor.set_learner_grade(t, FakeCtx(), bad)
    assert t.learner["grade"] is None
    assert t.room.local_participant.sent == []
    assert "1-12" in result or "school year" in result


async def test_switch_student_updates_name_and_asks_browser():
    t = tutor({"name": "Elsa", "grade": 4, "notes": [{"topic": "bråk"}]})
    result = await Tutor.switch_student(t, FakeCtx(), "Leo")
    assert t.learner["name"] == "Leo"
    assert "Leo" in result and "notes" in result
    [(topic, payload)] = t.room.local_participant.sent
    assert topic == "profile"
    assert json.loads(payload) == {"switchTo": "Leo"}


async def test_switch_student_needs_a_name():
    t = tutor({"name": "Elsa"})
    result = await Tutor.switch_student(t, FakeCtx(), "  ")
    assert t.learner["name"] == "Elsa"
    assert t.room.local_participant.sent == []


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
    assert "Bo" in line and "Björnen" in line
    assert "läxor" not in line and "skol" not in line


def test_switched_student_context_replaces_notes():
    text = prompt.switched_student_context(
        {"name": "Leo", "grade": None, "notes": [{"topic": "ekvationer"}]})
    assert "Leo" in text and "ekvationer" in text


def test_prompt_bans_grade_forms_and_midcall_switching_rules():
    text = prompt.instructions({"name": "Leo", "grade": None})
    assert "never as a form" in text
    assert "set_learner_grade" in text
    assert "switch_student" in text
