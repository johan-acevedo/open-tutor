"""Check, upload and listen to the Swedish pronunciation lexicon (open_tutor/pronunciation.py).

    # check the lexicon (no network)
    uv run --project server python server/scripts/pronunciation_dictionary.py check

    # upload it as a new ElevenLabs dictionary; prints the id:version_id locator
    OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env \\
        server/bin/with-env uv run --project server python server/scripts/pronunciation_dictionary.py \\
        upload --name open-tutor-sv-2026-11-28

    # write probe sentences as WAV files to listen to, with and without the dictionary
    # and with and without the worker's speech normalisation (fictional text only)
    OPEN_TUTOR_ENV=... server/bin/with-env uv run --project server python \\
        server/scripts/pronunciation_dictionary.py listen --out /tmp/pronunciation \\
        --dictionary <id>:<version_id> [--google]

Uploading creates a new dictionary each time; put the printed locator in
TUTOR_TTS_PRONUNCIATION_DICTIONARIES on a development instance first. The API key comes
from ELEVENLABS_API_KEY and is never printed. `listen` costs a few hundred ElevenLabs
characters (and Google characters with --google).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import wave
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from open_tutor.pronunciation import LEXICON, parse_locators, validate_lexicon  # noqa: E402

API = "https://api.elevenlabs.io/v1"

# Fictional probe lines: the companion names, the formulas and abbreviations seen in
# science calls, and words worth a listen before anyone adds a rule for them.
PROBES = (
    ("lodjuret", "Hej, jag heter Lodjuret. Lodjuren och lodjurets ungar bor i skogen."),
    ("companions", "Räven, Lodjuret och Björnen hjälper dig på Talarum."),
    ("glukos", "Glukos är C6H12O6 och har en CH2OH-grupp och flera OH-grupper."),
    ("vatten", "Vatten är H2O, och när vi andas ut kommer det CO2 och H2O."),
    ("joner", "Na⁺ och Cl⁻ bildar NaCl, och pH-värdet är sju."),
    ("abbreviations", "Läs s. 34 i åk 7, t.ex. uppgift 3, dvs. den om 20 °C och 50 km/h."),
    ("science-words", "I Sjuan läser vi kemi: sackaros, glukos, fruktos och kolhydrat på kemisidan."),
    ("djur", "Däggdjur och rovdjur är djur, och gjorde hjälpte ljuset."),
)


def api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY") or ""
    if not key:
        raise SystemExit("ELEVENLABS_API_KEY is not set")
    return key


def check(path: Path) -> list:
    lexemes = validate_lexicon(path.read_text(encoding="utf-8"))
    graphemes = sum(len(lexeme.graphemes) for lexeme in lexemes)
    print(f"{path.name}: {len(lexemes)} lexemes, {graphemes} graphemes, valid")
    return lexemes


async def upload(path: Path, name: str, description: str) -> None:
    check(path)
    form = aiohttp.FormData()
    form.add_field("name", name)
    form.add_field("description", description)
    form.add_field("file", path.read_bytes(), filename=path.name, content_type="application/pls+xml")
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{API}/pronunciation-dictionaries/add-from-file",
                                headers={"xi-api-key": api_key()}, data=form) as response:
            body = await response.text()
            if response.status >= 400:
                # The error body names the problem; it never echoes the key.
                raise SystemExit(f"upload failed: HTTP {response.status}: {body[:500]}")
    data = json.loads(body)
    locator = f"{data['id']}:{data['version_id']}"
    print(f"uploaded {name}: {locator}")
    print(f"TUTOR_TTS_PRONUNCIATION_DICTIONARIES={locator}")


async def synthesize(engine, text: str) -> tuple[bytes, int, str]:
    """PCM, sample rate and the aligned transcript (empty when the engine has none)."""
    from livekit.agents.types import USERDATA_TIMED_TRANSCRIPT

    stream = engine.stream()
    stream.push_text(text)
    stream.end_input()
    pcm, rate, words = bytearray(), 0, []
    async for audio in stream:
        pcm += bytes(audio.frame.data)
        rate = audio.frame.sample_rate
        words += audio.frame.userdata.get(USERDATA_TIMED_TRANSCRIPT) or []
    await stream.aclose()
    return bytes(pcm), rate, "".join(str(word) for word in words)


def write_wav(path: Path, pcm: bytes, rate: int) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)


async def listen(out: Path, dictionary: str, google: bool, only: set[str]) -> None:
    from open_tutor.config import DEFAULT_TTS_MODEL, DEFAULT_TTS_VOICE
    from open_tutor.dialogue_tts import DialogueTTS
    from open_tutor.speech import speakable

    out.mkdir(parents=True, exist_ok=True)
    locators = parse_locators(dictionary)
    async with aiohttp.ClientSession() as session:
        def bella(dicts=()):
            return DialogueTTS(api_key=api_key(), voice_id=DEFAULT_TTS_VOICE, model=DEFAULT_TTS_MODEL,
                               language="sv", http_session=session, pronunciation_dictionaries=dicts)

        variants = [("bella-raw", bella(), False), ("bella-spoken", bella(), True)]
        if locators:
            variants.append(("bella-raw-dict", bella(locators), False))
        if google:
            from open_tutor.tts_fallback import DEFAULT_GOOGLE_LANGUAGE, DEFAULT_GOOGLE_VOICE, build_google_tts

            engine = build_google_tts(voice=DEFAULT_GOOGLE_VOICE, language=DEFAULT_GOOGLE_LANGUAGE)
            variants += [("aoede-raw", engine, False), ("aoede-spoken", engine, True)]
        for name, text in PROBES:
            if only and name not in only:
                continue
            for label, engine, normalised in variants:
                sent = " ".join(speakable(text).split()) if normalised else text
                pcm, rate, aligned = await synthesize(engine, sent)
                path = out / f"{name}--{label}.wav"
                write_wav(path, pcm, rate)
                same = " ".join(aligned.split()) == " ".join(sent.split())
                note = "no alignment" if not aligned else ("alignment = sent text" if same else f"alignment differs: {aligned!r}")
                print(f"{path.name}: {len(pcm) / (2 * rate):.1f} s, {note}")
                print(f"    sent: {sent}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lexicon", type=Path, default=LEXICON)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="validate the lexicon")
    up = commands.add_parser("upload", help="upload the lexicon as a new dictionary")
    up.add_argument("--name", required=True)
    up.add_argument("--description", default="Open Tutor Swedish lexicon (server/open_tutor/locales/sv_pronunciation.pls)")
    li = commands.add_parser("listen", help="write probe sentences as WAV files")
    li.add_argument("--out", type=Path, required=True)
    li.add_argument("--dictionary", default="", help="id:version_id locator(s) to compare against")
    li.add_argument("--google", action="store_true", help="also synthesise with the Google fallback voice")
    li.add_argument("--only", default="", help="comma-separated probe names (default: all), e.g. lodjuret,glukos")
    args = parser.parse_args()
    try:
        if args.command == "check":
            check(args.lexicon)
        elif args.command == "upload":
            asyncio.run(upload(args.lexicon, args.name, args.description))
        else:
            only = {name.strip() for name in args.only.split(",") if name.strip()}
            asyncio.run(listen(args.out, args.dictionary, args.google, only))
    except ValueError as error:
        raise SystemExit(f"invalid: {error}") from None


if __name__ == "__main__":
    main()
