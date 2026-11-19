"""Per-locale spoken tables for the tutor (Swedish default).

Only fixed lines the child hears (TTS greetings, spoken apologies) and short
note topics shown verbatim in the end card live here. The system prompt itself
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

DEFAULT_NOTE_TOPIC = "Läxhjälp"

# Shown on screen while the next page is prepared (screen.screen_loading).
# The tutor tool result keeps the English wrapper; only this template is spoken/shown.
LOADING_TEMPLATE = "Laddar {topic}…"
