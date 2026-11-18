import pytest

from open_tutor import prompt


@pytest.mark.parametrize("band,name", [("primary", "Räven"), ("middle", "Lodjuret"), ("upper", "Björnen")])
def test_tutor_and_fixed_greeting_use_the_displayed_companion(band, name):
    learner = {"name": "Testelev", "band": band}
    assert prompt.instructions(learner).startswith(f"Your name is {name}.\n")
    assert f"Introduce yourself as {name}" in prompt.greeting_instruction(learner)
    greeting, _ = prompt.greeting_line(learner, index=0)
    assert f"jag heter {name}" in greeting
    assert "Testelev" in greeting
