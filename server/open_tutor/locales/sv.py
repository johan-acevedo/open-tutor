"""Per-locale spoken tables for the tutor (Swedish default).

Only fixed lines the child hears (TTS greetings, spoken apologies), short
note topics shown verbatim in the end card, and the tables that turn written
Swedish into what the voice should say (speech.py) live here. The system prompt itself
stays in English and keeps telling the model to speak the session's language.
"""

from __future__ import annotations

LOCALE = "sv"

COMPANIONS = {
    "primary": "Räven",
    "middle": "Lodjuret",
    "upper": "Björnen",
}

GREETING_VARIANTS = (
    "Hej {name}, jag heter {companion} och hjälper dig med läxor och skolarbete. Vad jobbar du med idag?",
    "Hej hej {name}, {companion} här! Jag hjälper dig med läxor och skoluppgifter, så vad jobbar du med idag?",
    "Hej {name}, kul att du är här! Jag är {companion} och hjälper dig med läxor och skolan, vad jobbar du med idag?",
    "Hej {name}, det är {companion}! Jag hjälper dig med läxor och skolarbete, så vad jobbar du med idag?",
)

UPPER_GREETING_VARIANTS = (
    "Hej {name}, jag heter {companion} och hjälper dig att förstå och komma vidare. Vad jobbar du med idag?",
    "Hej hej {name}, {companion} här! Jag hjälper dig att förstå och komma vidare, så vad jobbar du med idag?",
)

NAMELESS_GREETING_VARIANTS = (
    "Hej! Jag heter {companion} och hjälper dig med läxor och skolarbete. Vad heter du?",
    "Hej hej! {companion} här! Jag hjälper dig med läxor och skoluppgifter, så vad heter du?",
)

NAMELESS_UPPER_GREETING_VARIANTS = (
    "Hej! Jag heter {companion} och hjälper dig att förstå och komma vidare. Vad heter du?",
    "Hej hej! {companion} här! Jag hjälper dig att förstå och komma vidare, så vad heter du?",
)

PROVIDER_FAILED_APOLOGY = (
    "Förlåt, jag fick ett tekniskt problem och kan inte fortsätta just nu. "
    "Stäng fönstret och starta en ny session, så försöker vi igen."
)

# Said once, through fixed TTS, when a long silence ends the call (idle.py).
# The page shows the same reason on its end card (web end.idle).
IDLE_GOODBYE = (
    "Det har varit tyst ett tag nu, så jag säger hej då här. "
    "Kom tillbaka när du vill fortsätta!"
)

DEFAULT_NOTE_TOPIC = "Läxhjälp"

# Shown on screen while the next page is prepared (screen.screen_loading).
# The tutor tool result keeps the English wrapper; only this template is spoken/shown.
LOADING_TEMPLATE = "Laddar {topic}…"


# ---- What the voice says for written text (speech.speakable) --------------------
# These change only the text sent to the TTS engines, never the caption or the chat
# history. Keep them conservative: a rule that fires on an ordinary word is worse
# than the mispronunciation it fixes.

# Swedish letter names, used to read chemical formulas the way a teacher does
# ("hå två o", "se o två"). Lower-case second letters (Cl, Na) use the same names.
LETTER_NAMES = {
    "A": "a", "B": "be", "C": "se", "D": "de", "E": "e", "F": "eff", "G": "ge",
    "H": "hå", "I": "i", "J": "ji", "K": "kå", "L": "ell", "M": "em", "N": "en",
    "O": "o", "P": "pe", "Q": "ku", "R": "ärr", "S": "ess", "T": "te", "U": "u",
    "V": "ve", "W": "dubbelve", "X": "ex", "Y": "y", "Z": "säta",
}

NUMBER_WORDS = (
    "noll", "ett", "två", "tre", "fyra", "fem", "sex", "sju", "åtta", "nio", "tio",
    "elva", "tolv", "tretton", "fjorton", "femton", "sexton", "sjutton", "arton", "nitton",
)
TENS_WORDS = {2: "tjugo", 3: "trettio", 4: "fyrtio", 5: "femtio", 6: "sextio",
              7: "sjuttio", 8: "åttio", 9: "nittio"}

CHARGE_WORDS = {"+": "plus", "-": "minus"}

# Abbreviations and units as (regular expression, spoken words). Matched case-
# sensitively between word boundaries. Mid-sentence abbreviations drop their full
# stop so the TTS sentence splitter does not break the sentence there; the ones
# that usually end a sentence keep it (the group captures it).
SPOKEN_ABBREVIATIONS = (
    (r"t\. ?ex\.", "till exempel"),
    (r"T\. ?ex\.", "Till exempel"),
    (r"(?:d\.v\.s\.|dvs\.?)", "det vill säga"),
    (r"(?:D\.v\.s\.|Dvs\.?)", "Det vill säga"),
    (r"bl\.a\.", "bland annat"),
    (r"Bl\.a\.", "Bland annat"),
    (r"(?:p\.g\.a\.|pga\.?)", "på grund av"),
    (r"(?:P\.g\.a\.|Pga\.?)", "På grund av"),
    (r"resp\.", "respektive"),
    (r"inkl\.", "inklusive"),
    (r"exkl\.", "exklusive"),
    (r"jfr\.?", "jämför"),
    (r"(?:o\.s\.v|osv)(\.?)", "och så vidare\\1"),
    (r"m\.m(\.?)", "med mera\\1"),
    (r"etc(\.?)", "etcetera\\1"),
    # Only before a number: "åk" is also the verb ("åk hem"), "s" and "nr" plain letters.
    (r"åk\.?(?= ?\d)", "årskurs"),
    (r"Åk\.?(?= ?\d)", "Årskurs"),
    (r"(?:s|sid)\.(?= ?\d)", "sidan"),
    (r"(?:S|Sid)\.(?= ?\d)", "Sidan"),
    (r"kl\.?(?= ?\d)", "klockan"),
    (r"Kl\.?(?= ?\d)", "Klockan"),
    (r"nr\.?(?= ?\d)", "nummer"),
    (r"Nr\.?(?= ?\d)", "Nummer"),
    (r"ca\.?(?= ?\d)", "cirka"),
    (r"(?<=\d )ggr\.?", "gånger"),
    (r"(?<=\d )st\.?", "stycken"),
    # Units. Longest first, so m/s² is not read as m/s.
    (r"m/s(?:²|2)", "meter per sekundkvadrat"),
    (r"km/h", "kilometer i timmen"),
    (r"m/s", "meter per sekund"),
    (r"g/cm(?:³|3)", "gram per kubikcentimeter"),
    (r"kg/m(?:³|3)", "kilogram per kubikmeter"),
    (r"pH", "pe hå"),
)

# Written words whose spelling misleads the voice, as (written word start, spoken
# word start), replaced at the start of a word. Observed in family calls
# (2026-11-27): the middle band's companion "Lodjuret" was said with an audible d;
# in Swedish the d of "dj" is silent. "Lojuret" spells what should be heard. Any
# change here needs a listening check on both voices (server/README.md).
SPOKEN_RESPELLINGS = (
    ("Lodjur", "Lojur"),
    ("lodjur", "lojur"),
)
