import asyncio

import pytest

from open_tutor.speech import speakable, speakable_stream, swedish_speech, unspoken_stream


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
                                   "Om f(x) är 3x, vad är f(2)?", "Det står i boken.", "NO och SO är ämnen.",
                                   "OK, Ni kan ta E4.", "Svaret är C.", "Åk hem nu!", "Klass 7B läser."])
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


def spoken(text):
    return " ".join(speakable(text).split())


@pytest.mark.parametrize("written, said", [
    ("H2O", "hå två o"),
    ("H₂O", "hå två o"),
    ("CO2-utsläppen", "se o två-utsläppen"),
    ("O2", "o två"),
    ("CH2OH-gruppen", "se hå två o hå-gruppen"),
    ("OH-grupperna", "o hå-grupperna"),
    ("C6H12O6", "se sex hå tolv o sex"),
    ("H2SO4", "hå två ess o fyra"),
    ("Ca(OH)2", "se a, parentes o hå slut parentes, två"),
    ("Fe^{3+}", "eff e tre plus"),
    ("Fe³⁺ och O²⁻", "eff e tre plus och o två minus"),
    ("2H2O", "två hå två o"),
    ("NaCl", "en a se ell"),
    ("Na⁺ och Cl⁻", "en a plus och se ell minus"),
    ("SO₄²⁻", "ess o fyra två minus"),
    ("H+", "hå plus"),
    ("H3O^+", "hå tre o plus"),
    ("pH-värdet", "pe hå-värdet"),
    (r"$\mathrm{H_{2}O}$", "hå två o"),
])
def test_chemical_formulas_are_read_the_swedish_way(written, said):
    assert spoken(written) == said


@pytest.mark.parametrize("text", [
    "NO", "SO-läxan", "OK", "Ni", "Se här", "Ge mig", "In", "I åk", "Be", "Är",
    "E4", "MP3", "A4", "3D", "7B", "4K", "SVT", "USA", "IKEA", "COVID-19", "CO2e",
    "betyget C", "C-vitamin", "B2:B5", "B- och C-uppgifter", "x2", "Karl XII", "CO",
])
def test_capital_letters_that_are_not_formulas_stay(text):
    assert swedish_speech(text) == text


@pytest.mark.parametrize("written, said", [
    ("Det står t.ex. i boken.", "Det står till exempel i boken."),
    ("T.ex. en katt.", "Till exempel en katt."),
    ("Det är dvs. fel", "Det är det vill säga fel"),
    ("alltså d.v.s. rätt", "alltså det vill säga rätt"),
    ("bl.a. glukos", "bland annat glukos"),
    ("pga. regnet", "på grund av regnet"),
    ("äpplen, päron osv.", "äpplen, päron och så vidare."),
    ("äpplen, päron o.s.v. Sedan", "äpplen, päron och så vidare. Sedan"),
    ("pennor m.m.", "pennor med mera."),
    ("Läs s. 34", "Läs sidan 34"),
    ("Jag går i åk 7", "Jag går i årskurs 7"),
    ("Åk 9 har prov", "Årskurs 9 har prov"),
    ("Läs s.34 kl.8.", "Läs sidan 34 klockan 8."),
    ("Det är 1°C ute", "Det är 1 grad Celsius ute"),
    ("Det är −1 °C ute", "Det är minus 1 grad Celsius ute"),
    ("21 °C och 0,1 °C", "21 grader Celsius och 0,1 grader Celsius"),
    ("en vinkel på 1°", "en vinkel på 1 grad"),
    ("kl. 8", "klockan 8"),
    ("nr 3", "nummer 3"),
    ("ca 20", "cirka 20"),
    ("5 st äpplen", "5 stycken äpplen"),
    ("3 ggr", "3 gånger"),
    ("Det är 20 °C ute", "Det är 20 grader Celsius ute"),
    ("Det är 20°C ute", "Det är 20 grader Celsius ute"),
    ("en vinkel på 90°", "en vinkel på 90 grader"),
    ("50 km/h", "50 kilometer i timmen"),
    ("3 m/s", "3 meter per sekund"),
    ("9,8 m/s²", "9,8 meter per sekundkvadrat"),
    ("1 g/cm³", "1 gram per kubikcentimeter"),
])
def test_abbreviations_and_units_are_said_in_full(written, said):
    assert spoken(written) == said


@pytest.mark.parametrize("text", [
    "Åk hem nu", "Åk 5 km söderut.", "åk 2 varv till", "åk 10", "s", "kl", "nr", "Lisa ca", "st", "mm", "Kalla det m", "Ett ess", "sid", "Carl",
    "ggr", "etcetera", "Sankt", "katt.ex", "mest", "dvsx",
])
def test_abbreviation_lookalikes_stay(text):
    assert swedish_speech(text) == text


def test_spreadsheet_cells_keep_their_arithmetic():
    assert spoken("=B2/3") == "är lika med B2 delat med 3"
    assert spoken("=B2-1") == "är lika med B2 minus 1"


def test_locator_errors_never_echo_the_value():
    from open_tutor.pronunciation import parse_locators
    with pytest.raises(ValueError) as error:
        parse_locators("fictional-misplaced-token")
    assert "fictional-misplaced-token" not in str(error.value)


def test_lodjuret_is_said_with_a_silent_d_but_written_as_is():
    assert spoken("Hej, jag heter Lodjuret!") == "Hej, jag heter Lojuret!"
    assert spoken("lodjuren och lodjurets") == "lojuren och lojurets"
    assert " ".join(caption(["Hej, jag heter ", "Lodjuret!"]).split()) == "Hej, jag heter Lodjuret!"
    assert spoken("Slodjur") == "Slodjur"  # only at the start of a word


def test_the_caption_keeps_what_the_model_wrote():
    reply = "Glukos är C6H12O6, t.ex. i frukt, och det är 20 °C i åk 7."
    assert " ".join(caption(list(reply)).split()) == reply


@pytest.mark.parametrize("parts, said", [
    (["Läs s. ", "34 nu."], "Läs sidan 34 nu."),
    (["Jag går i åk ", "7 nu."], "Jag går i årskurs 7 nu."),
    (["Jag går i åk", " 7 nu."], "Jag går i årskurs 7 nu."),
    (["Kom kl. ", "8 i morgon."], "Kom klockan 8 i morgon."),
    (["Det står t. ", "ex. här."], "Det står till exempel här."),
    (["Glukos är C6H", "12O6 och ", "CO2 är gas."], "Glukos är se sex hå tolv o sex och se o två är gas."),
    (["Det är 20 ", "°C."], "Det är 20 grader Celsius."),
    (["Åk ", "hem nu."], "Åk hem nu."),
    (["Lod", "juret ", "är här."], "Lojuret är här."),
    (["Ta 5 ", "st äpplen och 3 ", "ggr till."], "Ta 5 stycken äpplen och 3 gånger till."),
    (["Åk 5 ", "km söderut."], "Åk 5 km söderut."),
    (["Åk ", "5 ", "km söderut."], "Åk 5 km söderut."),
    (["Det är 1 ", "°C."], "Det är 1 grad Celsius."),
])
def test_stream_chunk_boundaries_do_not_split_a_reading(parts, said):
    assert " ".join(say(parts).split()) == said
    # Character by character, as some providers stream.
    assert " ".join(say(list("".join(parts))).split()) == said


def test_a_held_word_is_said_when_the_reply_ends_there():
    assert " ".join(say(["Vi ses kl."]).split()) == "Vi ses kl."
    assert " ".join(say(["Jag går i åk ", "7"]).split()) == "Jag går i årskurs 7"
