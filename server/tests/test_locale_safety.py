"""The session locale comes from the browser: it must stay a plain language tag."""

import pytest

from open_tutor import prompt
from open_tutor.screen import screenkit


@pytest.mark.parametrize("raw", ['"><script>', "../../etc", "sv/../x", "", None, "SV "])
def test_learner_locale_falls_back_to_swedish(raw):
    assert prompt.learner_locale({"locale": raw}) == "sv"


def test_learner_locale_keeps_a_language_tag():
    assert prompt.learner_locale({"locale": "en-gb"}) == "en-gb"


def test_compose_never_puts_an_unsafe_locale_in_the_page():
    doc = screenkit.compose("<p>x</p>", locale='"><b>x')
    assert '<html lang="sv"' in doc
    assert '"><b>x' not in doc
