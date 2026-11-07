"""Teaching-iteration smoke tests: assembly and compatibility, not wording.

Checks that the prompt still assembles (BASE + learner), that the memory schema the
browser depends on is unchanged, and that the language/ownership fixes are present in
form (not exact sentences). Fictional learner only.
"""

from open_tutor import prompt
from open_tutor.board import Note


def test_instructions_assemble_with_learner():
    text = prompt.instructions({"name": "Leo", "grade": 5})
    assert text.startswith(prompt.BASE)
    assert "About this learner" in text
    assert "Leo" in text and "årskurs 5" in text


def test_learner_notes_warn_against_mastery_reading():
    text = prompt.learner_context({"name": "Leo", "grade": 5,
                                    "notes": [{"at": "2026-11-01", "topic": "Division",
                                               "clicked": "tabeller", "tricky": "", "next": ""}]})
    assert "Division" in text
    # Compatibility anchor: prior clicked must not read as diagnosed mastery.
    assert "not proven mastery" in text or "not diagnosed mastery" in text


def test_memory_schema_compatible_with_browser():
    fields = set(Note.model_fields)
    assert fields == {"at", "topic", "clicked", "tricky", "next"}
    # clicked/tricky/next stay optional; topic required.
    assert Note.model_fields["topic"].is_required()
    assert not Note.model_fields["clicked"].is_required()


def test_goodbye_follows_spoken_language():
    # Regression anchor: do not hard-code a return to Swedish mid-English session.
    assert "Swedish sentences" not in prompt.END_INSTRUCTION
    assert "have been speaking" in prompt.END_INSTRUCTION


def test_base_keeps_agency_and_bounds():
    # Anchors only: child authors work, quiet presence, no tool narration, local
    # experience bounded and rule-free.
    assert "Never write their essay" in prompt.instructions({"name": "Leo"})
    assert "only when you call a board tool" in prompt.BASE
    assert "Never describe or narrate a tool call" in prompt.BASE
    assert "Local experience" in prompt.BASE
    assert prompt.BASE.count("still open") >= 3
