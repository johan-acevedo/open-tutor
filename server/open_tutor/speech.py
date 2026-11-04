"""Turn the model's text into something a Swedish voice can say.

The model is asked to speak plainly, but maths symbols, LaTeX and Markdown still
slip into replies. Captions keep the original text; only the voice gets this.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterable, AsyncIterator

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
_COMMAND = re.compile(r"\\[a-zA-Z]+")
_SPACED_MINUS = re.compile(r"(?<=[\w)]) - (?=[\w(])")
_DIGIT_MINUS = re.compile(r"(?<=\d)\s*-\s*(?=\d)")
_FRACTION = re.compile(r"(?<=\d)/(?=\d)")
_STRIP = re.compile(r"[$*#`_{}\\]")
_SPACES = re.compile(r"[ \t]{2,}")


def speakable(text: str) -> str:
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


async def speakable_stream(chunks: AsyncIterable[str]) -> AsyncIterator[str]:
    """Normalise per sentence-ish piece so a symbol split across chunks is not missed."""
    buffer = ""
    async for chunk in chunks:
        buffer += chunk
        cut = max(buffer.rfind(" "), buffer.rfind("\n"))
        if cut > 0 and not buffer[:cut].count("$") % 2:
            yield speakable(buffer[: cut + 1])
            buffer = buffer[cut + 1 :]
    if buffer:
        yield speakable(buffer)
