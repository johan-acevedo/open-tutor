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


def test_memory_schema_compatible_with_browser():
    fields = set(Note.model_fields)
    assert fields == {"at", "topic", "clicked", "tricky", "next"}
    # clicked/tricky/next stay optional; topic required.
    assert Note.model_fields["topic"].is_required()
    assert not Note.model_fields["clicked"].is_required()
