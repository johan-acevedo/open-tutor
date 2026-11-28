"""What the model writes, split into what may be said and what may not.

Board content belongs in tool calls (structured `function_call` items), never in the
reply text. Some models still write it into the reply: a narrated call such as
"*(Anropar `show_steps` …)*", a JSON payload, a code block or a LaTeX `aligned` block.
Such text is not speech. It must not reach the voice, the caption or the chat history
(LiveKit stores the caption text as the assistant message, so a narrated call left
there invites the model to narrate again instead of calling).

`unspoken` removes those blocks and is used for captions and history.
`speakable` also turns maths symbols, chemical formulas, abbreviations and units into
Swedish words for the voice (`swedish_speech`). Both TTS engines (ElevenLabs and the
Google fallback) receive this text; the caption keeps what the model wrote.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterable, AsyncIterator, Callable
from functools import partial

from .locales import get_locale

log = logging.getLogger("open-tutor")

LATEX_WORDS = {
    r"\frac": " ", r"\cdot": " gånger ", r"\times": " gånger ", r"\div": " delat med ",
    r"\sqrt": " roten ur ", r"\pi": " pi ", r"\le": " mindre än eller lika med ",
    r"\ge": " större än eller lika med ", r"\neq": " inte lika med ", r"\approx": " ungefär ",
}
SYMBOLS = {
    "=": " är lika med ", "+": " plus ", "−": " minus ", "÷": " delat med ", "×": " gånger ",
    "·": " gånger ", "≈": " ungefär ", "≤": " mindre än eller lika med ", "≥": " större än eller lika med ",
    "²": " i kvadrat ", "³": " upphöjt till tre ", "→": ", ",
}
_FRAC = re.compile(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_LATEX = re.compile("|".join(re.escape(k) for k in sorted(LATEX_WORDS, key=len, reverse=True)) + r"(?![a-zA-Z])")
_ENV = re.compile(r"\\(?:begin|end)\s*\{[a-zA-Z*]+\}")
_ROW_BREAK = re.compile(r"\\\\")
_COMMAND = re.compile(r"\\[a-zA-Z]+")
_SPACED_MINUS = re.compile(r"(?<=[\w)]) - (?=[\w(])")
_DIGIT_MINUS = re.compile(r"(?<=\d)\s*-\s*(?=\d)")
_FRACTION = re.compile(r"(?<=\d)/(?=\d)")
_STRIP = re.compile(r"[$*#`_{}\\&]")
_SPACES = re.compile(r"[ \t]{2,}")

# Not speech: fenced code, inline code (identifiers such as `show_steps`), stage
# directions in emphasis such as *(visar på tavlan)*, and square-bracket notes.
_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_STAGE = re.compile(r"(?<![\w*_])([*_]{1,2})\s*\([^()]*\)\s*\1(?![\w*_])")
_BRACKETS = re.compile(r"\[[^\[\]]*\]")
# Code identifiers never occur in spoken Swedish: snake_case or dotted names, and a call
# such as print(default_api.show_steps(...)) with its arguments.
_CALL = re.compile(r"\b[A-Za-z]\w*[_.][\w.]*\((?:[^()]|\([^()]*\))*\)")
_EMPTY_CALL = re.compile(r"\b[A-Za-z]\w*\(\s*\)")
_IDENT = re.compile(r"\b[A-Za-z]+(?:[_.][A-Za-z0-9]+)*_[A-Za-z0-9_.]+\b")
_BLANK_LINES = re.compile(r"\n\s*\n+")

LIMIT = 800  # never hold more than this waiting for a block to close

# ---- Swedish words for written chemistry, abbreviations and units ------------------

_SV = get_locale("sv")
# Element symbols a school text uses. A formula is read only when every part is one
# of these, so "E4", "MP3" or "SVT2" stay as they are.
ELEMENTS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
    "Ga Ge As Se Br Kr Rb Sr Zr Mo Ag Cd Sn Sb I Xe Cs Ba W Pt Au Hg Pb Bi Rn Ra U Pu".split()
)
# Formulas without a digit or a charge that are still clearly chemistry. Anything
# else needs a digit (H2O, CO2, CH2OH) or a charge (Na⁺): without one, capital
# letters are far more often an acronym or a Swedish word ("NO", "SO", "OK", "Ni").
BARE_FORMULAS = frozenset({"OH", "NaCl", "NaOH", "HCl", "KOH", "COOH"})
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_LATEX_SUBSCRIPT = re.compile(r"(?<=[A-Za-z)])_\{(\d+)\}")
_LATEX_TEXT = re.compile(r"\\(?:text|mathrm|ce)\s*\{([A-Za-z0-9()]+)\}")
_FORMULA = re.compile(
    r"(?<![\w.,/])(?P<coef>\d+)?"
    r"(?P<body>(?:[A-Z][a-z]?\d*|\((?:[A-Z][a-z]?\d*)+\)\d*)+)"
    r"(?P<charge>[⁰¹²³⁴⁵⁶⁷⁸⁹]*[⁺⁻]|\^\{?\d*[+-]\}?|\+(?![\w+]))?"
    r"(?!\w)"
)
_FORMULA_PART = re.compile(r"[A-Z][a-z]?|\d+")
_ABBREVIATIONS = tuple(
    (re.compile(r"(?<![\w.])" + pattern + r"(?![\w/])"), words) for pattern, words in _SV.SPOKEN_ABBREVIATIONS
)
_DEGREES_C = re.compile(r"(?:(?<=\d) ?)?°C(?!\w)")
_DEGREES = re.compile(r"(?<=\d) ?°(?![CF\w])")
_RESPELLINGS = tuple((re.compile(r"(?<!\w)" + re.escape(written)), spoken)
                     for written, spoken in _SV.SPOKEN_RESPELLINGS)
# A word that is read differently depending on the next one ("åk 7", "s. 34"):
# the stream waits for that next word before speaking it.
_AWAITS_NEXT_WORD = re.compile(r"(?<![\w.])(?:(?:s|S|sid|Sid|t|T)\.|(?:åk|Åk|kl|Kl|nr|Nr|ca)\.?)$")


def number_words(value: str) -> str:
    """Swedish words for 0-99 (formula subscripts); larger numbers stay as digits."""
    n = int(value)
    if n < 20:
        return _SV.NUMBER_WORDS[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _SV.TENS_WORDS[tens] + (_SV.NUMBER_WORDS[ones] if ones else "")
    return value


def _letters(symbol: str) -> str:
    return " ".join(_SV.LETTER_NAMES[c.upper()] for c in symbol)


def _say_formula(match: re.Match) -> str:
    body, charge = match.group("body"), match.group("charge") or ""
    symbols = re.findall(r"[A-Z][a-z]?", body)
    if not all(symbol in ELEMENTS for symbol in symbols):
        return match.group(0)
    if not (re.search(r"\d", body) or charge or body in BARE_FORMULAS):
        return match.group(0)
    words = [number_words(match.group("coef"))] if match.group("coef") else []
    for part in _FORMULA_PART.findall(body):
        words.append(number_words(part) if part.isdigit() else _letters(part))
    if charge:
        sign = "+" if charge[-1] in "+⁺" else "-"
        size = re.sub(r"\D", "", charge.translate(_SUPERSCRIPT_DIGITS))
        if size:
            words.append(number_words(size))
        words.append(_SV.CHARGE_WORDS[sign])
    return " ".join(words)


def swedish_speech(text: str) -> str:
    """Written Swedish school text as it should be said: formulas, abbreviations, units.

    Only for the voice. Every rule is anchored at word boundaries and narrow on
    purpose; ordinary words, acronyms and grades pass through unchanged.
    """
    text = text.translate(_SUBSCRIPTS)
    text = _LATEX_TEXT.sub(r"\1", text)
    text = _LATEX_SUBSCRIPT.sub(r"\1", text)
    text = _FORMULA.sub(_say_formula, text)
    for pattern, words in _ABBREVIATIONS:
        text = pattern.sub(words, text)
    text = _DEGREES_C.sub(" grader Celsius", text)
    text = _DEGREES.sub(" grader", text)
    for pattern, spoken in _RESPELLINGS:
        text = pattern.sub(spoken, text)
    return text


def _drop_json(text: str) -> tuple[str, int]:
    """Remove balanced {...} groups that open like a JSON object ({"key": ...})."""
    out, i, dropped = [], 0, 0
    while i < len(text):
        if text[i] == "{" and re.match(r'\{\s*"', text[i:]):
            depth, j = 0, i
            while j < len(text):
                depth += {"{": 1, "}": -1}.get(text[j], 0)
                if depth == 0:
                    break
                j += 1
            dropped += 1
            i = j + 1  # an unclosed object runs to the end and is dropped
            continue
        out.append(text[i])
        i += 1
    return "".join(out), dropped


def unspoken(text: str, report: bool = False) -> str:
    """Remove tool narration, payloads and code from model text; keep the words."""
    text, dropped = _drop_json(text)
    for pattern in (_FENCE, _INLINE_CODE, _STAGE, _BRACKETS, _CALL, _EMPTY_CALL, _IDENT):
        text, n = pattern.subn(" ", text)
        dropped += n
    if dropped and report:
        # Content stays out of the logs; the count shows the model is narrating instead of calling.
        log.warning("dropped %d non-speech block(s) from the reply text", dropped)
    text = _BLANK_LINES.sub("\n", text)
    return _SPACES.sub(" ", text)


def speakable(text: str) -> str:
    text = unspoken(text)
    text = swedish_speech(text)
    text = _ENV.sub(" ", text)
    text = _ROW_BREAK.sub(", ", text)
    text = _FRAC.sub(r" \1 delat med \2 ", text)
    text = _LATEX.sub(lambda m: LATEX_WORDS[m.group(0)], text)
    text = _COMMAND.sub(" ", text)
    text = _SPACED_MINUS.sub(" minus ", text)
    text = _DIGIT_MINUS.sub(" minus ", text)
    text = _FRACTION.sub(" delat med ", text)
    for symbol, words in SYMBOLS.items():
        text = text.replace(symbol, words)
    text = _STRIP.sub("", text)
    return _SPACES.sub(" ", text)


def _open(text: str) -> bool:
    """True while a block that `unspoken`/`speakable` must see whole is still open."""
    fences = text.count("```")
    rest = text.replace("```", "")
    return bool(
        fences % 2
        or rest.count("`") % 2
        or text.count("$") % 2
        or text.count("{") > text.count("}")
        or text.count("[") > text.count("]")
        or text.count("(") > text.count(")")
        or text.count(r"\begin") > text.count(r"\end")
    )


def _cut(buffer: str) -> int:
    """The last word boundary that is safe to transform up to.

    A word such as "åk" or "s." is read differently before a number, so the cut
    stays in front of it until the next word has arrived."""
    cut = max(buffer.rfind(" "), buffer.rfind("\n"))
    if cut > 0 and _AWAITS_NEXT_WORD.search(buffer[:cut]):
        cut = max(buffer.rfind(" ", 0, cut), buffer.rfind("\n", 0, cut))
    return cut


async def _filtered(chunks: AsyncIterable[str], transform: Callable[[str], str]) -> AsyncIterator[str]:
    """Transform at word boundaries, holding text while a block is open so a block
    split across chunks is seen whole."""
    buffer = ""
    async for chunk in chunks:
        buffer += chunk
        cut = _cut(buffer)
        if cut > 0 and (not _open(buffer[:cut]) or len(buffer) > LIMIT):
            piece = transform(buffer[: cut + 1])
            buffer = buffer[cut + 1 :]
            if piece.strip():
                yield piece
    if buffer:
        piece = transform(buffer)
        if piece.strip():
            yield piece


def speakable_stream(chunks: AsyncIterable[str]) -> AsyncIterator[str]:
    return _filtered(chunks, speakable)


def unspoken_stream(chunks: AsyncIterable[str]) -> AsyncIterator[str]:
    # Reports dropped blocks (counts only); the voice applies the same rule silently.
    return _filtered(chunks, partial(unspoken, report=True))
