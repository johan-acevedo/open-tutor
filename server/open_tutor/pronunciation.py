"""ElevenLabs pronunciation dictionaries for the Swedish voice.

ElevenLabs applies a pronunciation dictionary on its side to the text it receives:
`<phoneme>` rules (IPA) or `<alias>` rules (a respelling), matched case-sensitively
per word. The lexicon is kept in the repository
(`open_tutor/locales/sv_pronunciation.pls`), uploaded with
`scripts/pronunciation_dictionary.py`, and switched on with
`TUTOR_TTS_PRONUNCIATION_DICTIONARIES=<id>:<version_id>[,<id>:<version_id>…]` (at
most three). Unset, every request is exactly as before.

Only ElevenLabs reads it; the Google fallback never sees it. Respellings that both
voices need belong in `locales/sv.py` (`SPOKEN_RESPELLINGS`, applied by
`speech.speakable` before either engine), not here. The dictionary is for what a
respelling cannot express, and for trying an IPA rule against a respelling on Bella.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from livekit.plugins.elevenlabs import PronunciationDictionaryLocator

ENV = "TUTOR_TTS_PRONUNCIATION_DICTIONARIES"
MAX_DICTIONARIES = 3  # ElevenLabs accepts at most three locators per request
LEXICON = Path(__file__).parent / "locales" / "sv_pronunciation.pls"
PLS_NS = "http://www.w3.org/2005/01/pronunciation-lexicon"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def parse_locators(raw: str | None) -> tuple[PronunciationDictionaryLocator, ...]:
    """`id:version_id` pairs separated by commas or spaces; empty means none.

    Raises ValueError naming the problem, so a typo stops the worker at boot instead
    of failing a child's first sentence."""
    entries = [entry for entry in re.split(r"[,\s]+", (raw or "").strip()) if entry]
    if len(entries) > MAX_DICTIONARIES:
        raise ValueError(f"{ENV} takes at most {MAX_DICTIONARIES} dictionaries, got {len(entries)}")
    locators: list[PronunciationDictionaryLocator] = []
    for number, entry in enumerate(entries, start=1):
        dictionary_id, sep, version_id = entry.partition(":")
        if not sep or not _ID.fullmatch(dictionary_id) or not _ID.fullmatch(version_id):
            # Never echo the value: a key pasted into the wrong setting would land in the log.
            raise ValueError(f"{ENV} entry {number} must look like <dictionary_id>:<version_id>")
        if any(loc.pronunciation_dictionary_id == dictionary_id for loc in locators):
            raise ValueError(f"{ENV} entry {number} repeats a dictionary listed twice")
        locators.append(PronunciationDictionaryLocator(dictionary_id, version_id))
    return tuple(locators)


def pronunciation_dictionaries(environ: dict[str, str] | Any | None = None) -> tuple[PronunciationDictionaryLocator, ...]:
    env = os.environ if environ is None else environ
    return parse_locators(env.get(ENV))


def describe_locators(locators: tuple[PronunciationDictionaryLocator, ...]) -> str:
    """For route logs: ids are not secrets."""
    return ",".join(f"{loc.pronunciation_dictionary_id}:{loc.version_id}" for loc in locators)


def locators_payload(locators: tuple[PronunciationDictionaryLocator, ...]) -> list[dict[str, str]]:
    return [
        {"pronunciation_dictionary_id": loc.pronunciation_dictionary_id, "version_id": loc.version_id}
        for loc in locators
    ]


@dataclass(frozen=True)
class Lexeme:
    graphemes: tuple[str, ...]
    phoneme: str | None
    alias: str | None


def _other_case(word: str) -> str:
    first = word[0]
    return (first.lower() if first.isupper() else first.upper()) + word[1:]


def validate_lexicon(text: str) -> list[Lexeme]:
    """Parse a PLS lexicon and check what ElevenLabs needs; raise ValueError listing
    every problem.

    Checks: the PLS namespace, `alphabet="ipa"`, a Swedish `xml:lang`, each lexeme
    with at least one grapheme and exactly one `<phoneme>` or `<alias>`, no grapheme
    twice, IPA written without slashes, and, because rules match case-sensitively,
    every word present both capitalised and in lower case."""
    root = ET.fromstring(text)
    problems: list[str] = []
    if root.tag != f"{{{PLS_NS}}}lexicon":
        raise ValueError(f"not a PLS lexicon: root element {root.tag}")
    if root.get("alphabet") != "ipa":
        problems.append('the lexicon must declare alphabet="ipa"')
    if not (root.get(XML_LANG) or "").lower().startswith("sv"):
        problems.append("the lexicon must declare a Swedish xml:lang")
    lexemes: list[Lexeme] = []
    seen: set[str] = set()
    for element in root.findall(f"{{{PLS_NS}}}lexeme"):
        graphemes = tuple((g.text or "").strip() for g in element.findall(f"{{{PLS_NS}}}grapheme"))
        phonemes = [(p.text or "").strip() for p in element.findall(f"{{{PLS_NS}}}phoneme")]
        aliases = [(a.text or "").strip() for a in element.findall(f"{{{PLS_NS}}}alias")]
        label = graphemes[0] if graphemes else "?"
        if not graphemes or not all(graphemes):
            problems.append(f"lexeme {label}: needs a non-empty grapheme")
        if len(phonemes) + len(aliases) != 1 or not all(phonemes + aliases):
            problems.append(f"lexeme {label}: needs exactly one non-empty <phoneme> or <alias>")
        if any("/" in p for p in phonemes):
            problems.append(f"lexeme {label}: write IPA without slashes")
        for grapheme in graphemes:
            if grapheme in seen:
                problems.append(f"grapheme {grapheme} appears twice")
            seen.add(grapheme)
        lexemes.append(Lexeme(graphemes, phonemes[0] if phonemes else None, aliases[0] if aliases else None))
    if not lexemes:
        problems.append("the lexicon has no lexemes")
    for grapheme in sorted(seen):
        if grapheme[:1].isalpha() and _other_case(grapheme) not in seen:
            problems.append(f"grapheme {grapheme} has no {_other_case(grapheme)} variant (rules are case-sensitive)")
    if problems:
        raise ValueError("; ".join(problems))
    return lexemes
