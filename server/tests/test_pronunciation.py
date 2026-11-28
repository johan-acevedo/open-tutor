"""The Swedish pronunciation lexicon and the TUTOR_TTS_PRONUNCIATION_DICTIONARIES setting."""

import pytest

from open_tutor import debug_log, pronunciation
from open_tutor.pronunciation import LEXICON, parse_locators, validate_lexicon


def test_unset_or_empty_means_no_dictionaries():
    assert parse_locators(None) == ()
    assert parse_locators("") == ()
    assert parse_locators("  ") == ()


def test_up_to_three_locators_separated_by_commas_or_spaces():
    locators = parse_locators(" abc123:v1 , def456:v2 ghi789:v3 ")
    assert [(l.pronunciation_dictionary_id, l.version_id) for l in locators] == [
        ("abc123", "v1"), ("def456", "v2"), ("ghi789", "v3")]
    assert pronunciation.describe_locators(locators) == "abc123:v1,def456:v2,ghi789:v3"


@pytest.mark.parametrize("raw, problem", [
    ("a:1,b:2,c:3,d:4", "at most 3"),
    ("abc123", "<dictionary_id>:<version_id>"),
    ("abc123:", "<dictionary_id>:<version_id>"),
    (":v1", "<dictionary_id>:<version_id>"),
    ("abc/123:v1", "<dictionary_id>:<version_id>"),
    ("abc:v1:extra", "<dictionary_id>:<version_id>"),
    ("abc:v1,abc:v2", "twice"),
])
def test_malformed_settings_are_refused(raw, problem):
    with pytest.raises(ValueError, match=problem):
        parse_locators(raw)


def test_the_setting_is_safe_to_record_in_the_debug_trail():
    assert "TUTOR_TTS_PRONUNCIATION_DICTIONARIES" in debug_log.SAFE_CONFIG_KEYS


def test_the_repository_lexicon_is_valid_and_covers_both_cases():
    lexemes = validate_lexicon(LEXICON.read_text(encoding="utf-8"))
    graphemes = {g for lexeme in lexemes for g in lexeme.graphemes}
    assert {"Lodjuret", "lodjuret", "Lodjur", "lodjur"} <= graphemes
    assert all(lexeme.phoneme and "/" not in lexeme.phoneme for lexeme in lexemes)


def lexicon(body: str, alphabet: str = "ipa", lang: str = "sv-SE") -> str:
    return (f'<?xml version="1.0" encoding="UTF-8"?><lexicon version="1.0" '
            f'xmlns="http://www.w3.org/2005/01/pronunciation-lexicon" alphabet="{alphabet}" '
            f'xml:lang="{lang}">{body}</lexicon>')


def test_alias_rules_are_accepted():
    lexemes = validate_lexicon(lexicon(
        "<lexeme><grapheme>Talarum</grapheme><grapheme>talarum</grapheme><alias>Talarumm</alias></lexeme>"))
    assert lexemes[0].alias == "Talarumm" and lexemes[0].phoneme is None


@pytest.mark.parametrize("text, problem", [
    (lexicon("<lexeme><grapheme>Lodjuret</grapheme><phoneme>x</phoneme></lexeme>"), "no lodjuret variant"),
    (lexicon("<lexeme><grapheme>a</grapheme><grapheme>A</grapheme></lexeme>"), "exactly one"),
    (lexicon("<lexeme><grapheme>a</grapheme><grapheme>A</grapheme><phoneme>x</phoneme><alias>y</alias></lexeme>"),
     "exactly one"),
    (lexicon("<lexeme><grapheme>a</grapheme><grapheme>A</grapheme><phoneme>/a/</phoneme></lexeme>"), "slashes"),
    (lexicon("<lexeme><grapheme>a</grapheme><grapheme>A</grapheme><phoneme>a</phoneme></lexeme>"
             "<lexeme><grapheme>a</grapheme><phoneme>b</phoneme></lexeme>"), "twice"),
    (lexicon("<lexeme><grapheme>a</grapheme><grapheme>A</grapheme><phoneme>a</phoneme></lexeme>", alphabet="x-sampa"),
     "alphabet"),
    (lexicon("<lexeme><grapheme>a</grapheme><grapheme>A</grapheme><phoneme>a</phoneme></lexeme>", lang="en-US"),
     "Swedish"),
    (lexicon(""), "no lexemes"),
    ('<lexicon alphabet="ipa"/>', "not a PLS lexicon"),
])
def test_lexicon_mistakes_are_named(text, problem):
    with pytest.raises(ValueError, match=problem):
        validate_lexicon(text)
