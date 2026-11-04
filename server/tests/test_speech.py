import asyncio

import pytest

from open_tutor.speech import speakable, speakable_stream, unspoken_stream


def test_maths_is_spoken_in_swedish():
    assert speakable("$3x + 5 = 20$").split() == "3x plus 5 är lika med 20".split()
    assert speakable("x = 15 ÷ 3").split() == "x är lika med 15 delat med 3".split()
    assert "minus" in speakable("20 - 5") and "minus" in speakable("20-5")
    assert speakable(r"$\frac{1}{2} \cdot 4$").split() == "1 delat med 2 gånger 4".split()


def test_markdown_and_ordinary_words_survive():
    assert speakable("**Bra** jobbat, Jonatan-boken!").strip() == "Bra jobbat, Jonatan-boken!"


def test_stream_keeps_latex_together():
    async def chunks():
        for part in ["Vi har $3x ", "+ 5", " = 20$ nu. ", "Klart"]:
            yield part

    async def collect():
        return "".join([piece async for piece in speakable_stream(chunks())])

    assert asyncio.run(collect()).split() == "Vi har 3x plus 5 är lika med 20 nu. Klart".split()


def say(parts):
    async def chunks():
        for part in parts:
            yield part

    async def collect():
        return "".join([piece async for piece in speakable_stream(chunks())])

    return asyncio.run(collect())


def caption(parts):
    async def chunks():
        for part in parts:
            yield part

    async def collect():
        return "".join([piece async for piece in unspoken_stream(chunks())])

    return asyncio.run(collect())


# Reply texts the deployed Gemini route really produced instead of calling a board tool
# (2026-11-04, fictional prompts).
NARRATED_CALLS = [
    "Det gör jag gärna! \n\n*(Anropar `show_steps` för att visa ekvationen och dess steg.)*",
    "Det fixar jag direkt! \n\n*(Anropar `show_svg` för att rita en rätvinklig triangel)*",
    "Då tar vi det ett steg i taget. \n\n*(Note: The user asked to show on the board. Let's use `show_steps`.)*\n",
    'Här kommer det. show_steps {"title": "Ekvation", "steps": [{"tex": "3x + 5 = 20", "op": null}]} Kolla!',
    "Okej.\n```json\n{\"name\": \"show_text\", \"arguments\": {\"markdown\": \"x = 5\"}}\n```\nSå.",
    "Jag visar det. [Session event, not the child's words: board]",
    "Visst. print(default_api.show_steps(title='Ekvation', steps=[{'tex': '3x'}])) Klart.",
    "Jag kör show_steps nu.",
]


@pytest.mark.parametrize("reply", NARRATED_CALLS)
def test_tool_calls_written_as_text_are_never_spoken(reply):
    for spoken in (speakable(reply), say(list(reply)), say([w + " " for w in reply.split(" ")]), caption(list(reply))):
        for leaked in ("Anropar", "Note", "{", '"', "title", "tex", "arguments", "json", "Session event", "`", "show", "steps", "default"):
            assert leaked not in spoken, (leaked, spoken)
    assert speakable(reply).split()[0] in reply  # the real words are still said


def test_board_content_in_the_reply_is_said_as_maths_not_markup():
    reply = "Så här:\n\n$\\begin{aligned}\n2x - 4 &= 10 \\\\\n2x &= 14 \\\\\nx &= 7\n\\end{aligned}$"
    spoken = say([reply[i:i + 7] for i in range(0, len(reply), 7)])
    assert "aligned" not in spoken and "&" not in spoken and "\\" not in spoken
    assert "2x minus 4 är lika med 10" in " ".join(spoken.split())
    assert "x är lika med 7" in " ".join(spoken.split())


@pytest.mark.parametrize("reply", ["Ja.", "Sju!", "Nej, inte riktigt.", "Bra (alltså fem) – snyggt!", "Vad tror du?",
                                   "Om f(x) är 3x, vad är f(2)?", "Det står t.ex. i boken."])
def test_short_answers_and_ordinary_words_are_untouched(reply):
    assert " ".join(say([reply]).split()) == reply
    assert " ".join(caption(list(reply)).split()) == reply


def test_an_unclosed_block_does_not_hold_speech_forever():
    reply = "Titta [" + "ord " * 300 + "slut"
    pieces = []

    async def chunks():
        for word in reply.split(" "):
            yield word + " "

    async def collect():
        async for piece in speakable_stream(chunks()):
            pieces.append(piece)

    asyncio.run(collect())
    assert len(pieces) > 1  # speech resumed before the end of the reply
