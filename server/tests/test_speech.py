import asyncio

from open_tutor.speech import speakable, speakable_stream


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
