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
    LEARNER_RPC_SET_NAME,
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


async def test_set_learner_name_acks_then_updates_call():
    t = tutor({"id": "temp-1", "name": "", "grade": None},
              replies={LEARNER_RPC_SET_NAME: {"ok": True, "profile": {"id": "p9", "name": "Noa", "grade": None}}})
    result = await Tutor.set_learner_name(t, FakeCtx(), "Noa")
    assert t.learner["id"] == "p9"
    assert t.learner["name"] == "Noa"
    assert "Noa" in result
    [(method, payload)] = t.room.local_participant.calls
    assert method == LEARNER_RPC_SET_NAME == "learner.setName"
    assert payload == {"profileId": "temp-1", "name": "Noa"}


async def test_set_learner_name_attaches_known_grade():
    t = tutor({"id": "temp-1", "name": "", "grade": None},
              replies={LEARNER_RPC_SET_NAME: {"ok": True, "profile": {"id": "p3", "name": "Moa", "grade": 5}}})
    result = await Tutor.set_learner_name(t, FakeCtx(), " Moa ")
    assert t.learner["name"] == "Moa"
    assert t.learner["grade"] == 5
    assert "5" in result


async def test_set_learner_name_failure_saves_nothing():
    t = tutor({"id": "temp-1", "name": "", "grade": None}, error=RpcFailed("gone"))
    result = await Tutor.set_learner_name(t, FakeCtx(), "Noa")
    assert t.learner["name"] == ""
    assert t.learner["id"] == "temp-1"
    assert "could not save" in result
    assert t.room.local_participant.calls == [(LEARNER_RPC_SET_NAME, {"profileId": "temp-1", "name": "Noa"})]


async def test_set_learner_name_needs_a_name():
    t = tutor({"id": "temp-1", "name": ""})
    result = await Tutor.set_learner_name(t, FakeCtx(), "   ")
    assert t.room.local_participant.calls == []
    assert "type it" in result or "Ask" in result


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


def test_nameless_call_asks_repeats_and_saves_the_name():
    text = prompt.learner_context({"name": "", "grade": None})
    assert "not known yet" in text
    assert "set_learner_name" in text
    # Silent save (2026-11-27): no spoken preamble before the tool, one reply after.
    assert "repeat the name back" not in text
    assert "silently" in text and "one" in text and "single spoken reply" in text
    assert "text field" in text
    # The grade flow is unchanged underneath the naming.
    assert "set_learner_grade" in text
    assert "åk 1–6" in text


def test_nameless_call_still_pitches_to_the_band():
    assert "högstadiet" in prompt.learner_context({"name": "", "grade": None, "band": "middle"})
    upper = prompt.learner_context({"name": "", "grade": None, "band": "upper"})
    assert "gymnasiet student or an adult" in upper


def test_nameless_greeting_asks_for_the_name_without_using_one():
    line, _ = prompt.greeting_line({"name": "", "band": "primary"}, index=0)
    assert "Vad heter du?" in line and "Räven" in line
    assert "du," not in line and "Hej du" not in line
    upper, _ = prompt.greeting_line({"name": "", "band": "upper"}, index=0)
    assert "Vad heter du?" in upper and "Björnen" in upper


def test_nameless_fallback_greeting_asks_for_the_name():
    line, _ = prompt.greeting_line({"name": ""}, index=0)
    assert "do not know it yet" in prompt.greeting_instruction({"name": ""})
    assert "what they are called" in prompt.greeting_instruction({"name": ""})


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


def test_nameless_greeting_names_the_band_companion():
    assert "Lodjuret" in prompt.greeting_line({"name": "", "band": "middle"}, index=0)[0]
    assert "Björnen" in prompt.greeting_line({"name": "", "band": "upper"}, index=1)[0]


def test_prompt_bans_grade_forms_and_midcall_switching_rules():
    text = prompt.instructions({"name": "Leo", "grade": None})
    assert "never as a form" in text
    assert "set_learner_grade" in text
    assert "switch_student" in text


@pytest.mark.parametrize("bad", ["Moa2", "<b>Moa</b>", "a b c d", "x" * 41, "Erik!", "   "])
async def test_set_learner_name_rejects_invalid_names_without_rpc(bad):
    # Finding 6: digits and markup are rejected before anything is stored —
    # the tool asks again and no RPC goes out.
    t = tutor({"id": "temp-1", "name": ""})
    result = await Tutor.set_learner_name(t, FakeCtx(), bad)
    assert t.room.local_participant.calls == []
    assert t.learner["name"] == ""
    assert "Ask once more" in result


@pytest.mark.parametrize("good", ["Noa", "Anna-Lisa", "Mary Jane", "Åsa", "Linnéa"])
async def test_set_learner_name_accepts_real_first_names(good):
    t = tutor({"id": "temp-1", "name": "", "grade": None},
              replies={LEARNER_RPC_SET_NAME: {"ok": True, "profile": {"id": "p9", "name": good, "grade": None}}})
    result = await Tutor.set_learner_name(t, FakeCtx(), f"  {good}  ")
    assert t.learner["name"] == good
    assert good in result
    [(method, payload)] = t.room.local_participant.calls
    assert method == LEARNER_RPC_SET_NAME
    assert payload == {"profileId": "temp-1", "name": good}


async def test_set_learner_name_attach_replaces_grade_and_restores_notes():
    # Findings 3 + 5: attaching to a different profile replaces the grade
    # (including null/unknown) and adopts its notes, and the instructions are
    # refreshed with the same context a returning start gets.
    notes = [{"topic": "multiplikationstabellen", "at": "2026-11-19"}]
    t = tutor({"id": "p9", "name": "Moa", "grade": 5, "notes": [{"topic": "bråk", "at": "2026-11-18"}]},
              replies={LEARNER_RPC_SET_NAME: {"ok": True, "profile": {"id": "pX", "name": "Noa",
                                                                      "grade": None, "notes": notes}}})
    seen: list[str] = []

    async def fake_update(text: str) -> None:
        seen.append(text)

    t.update_instructions = fake_update
    result = await Tutor.set_learner_name(t, FakeCtx(), "Noa")
    assert t.learner["id"] == "pX"
    assert t.learner["name"] == "Noa"
    assert t.learner["grade"] is None
    assert t.learner["notes"] == notes
    assert "årskurs 5" not in result
    assert len(seen) == 1
    assert "Noa" in seen[0]
    assert "multiplikationstabellen" in seen[0]
    assert "årskurs 5" not in seen[0]


async def test_set_learner_name_same_profile_correction_keeps_grade():
    # Findings 2 + 3 (worker side): renaming the same profile in place keeps
    # its school year and refreshes the instructions with the new name.
    notes = [{"topic": "bråk", "at": "2026-11-18"}]
    t = tutor({"id": "p9", "name": "Moa", "grade": 5, "notes": notes},
              replies={LEARNER_RPC_SET_NAME: {"ok": True, "profile": {"id": "p9", "name": "Noa",
                                                                      "grade": 5, "notes": notes}}})
    seen: list[str] = []

    async def fake_update(text: str) -> None:
        seen.append(text)

    t.update_instructions = fake_update
    result = await Tutor.set_learner_name(t, FakeCtx(), "Noa")
    assert t.learner["id"] == "p9"
    assert t.learner["grade"] == 5
    assert "årskurs 5" in result
    assert len(seen) == 1
    assert "Noa" in seen[0] and "årskurs 5" in seen[0]


def test_metadata_tools_are_called_silently():
    """2026-11-27: "repeat the name back first" gave a spoken preamble, a pause
    for the tool round-trip, then a second full turn. Both tools are now
    called without words before them, and confirmed in one reply after."""
    unknown_year = prompt.learner_context({"name": "Leo", "grade": None})
    assert "`set_learner_grade` silently" in unknown_year
    assert "one single spoken reply" in unknown_year
    known_year = prompt.learner_context({"name": "Leo", "grade": 5})
    assert "set_learner_grade" not in known_year
    for tool in (Tutor.set_learner_name, Tutor.set_learner_grade):
        doc = " ".join(((getattr(tool, "__wrapped__", None) or tool).__doc__ or "").split())
        assert "silently" in doc and "one single spoken reply" in doc
        assert "repeat the name back first" not in doc


async def test_metadata_tool_returns_ask_for_one_reply():
    t = tutor({"id": "temp-1", "name": "", "grade": None},
              replies={LEARNER_RPC_SET_NAME: {"ok": True, "profile": {"id": "p9", "name": "Noa", "grade": None}}})
    assert "one warm reply" in await Tutor.set_learner_name(t, FakeCtx(), "Noa")
    t = tutor({"id": "p1", "name": "Leo", "grade": None})
    assert "in one reply" in await Tutor.set_learner_grade(t, FakeCtx(), 8)
