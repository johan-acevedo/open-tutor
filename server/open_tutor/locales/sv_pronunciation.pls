<?xml version="1.0" encoding="UTF-8"?>
<!--
  Swedish pronunciation lexicon for the ElevenLabs voice (open_tutor/pronunciation.py).

  ElevenLabs applies it only when TUTOR_TTS_PRONUNCIATION_DICTIONARIES names an
  uploaded version (scripts/pronunciation_dictionary.py); unset, it is not used.
  Rules match case-sensitively, so every word is listed capitalised and in lower case.
  Keep it to words heard mispronounced in a real call.

  The lodjur family (2026-11-27): "Lodjuret" was said with an audible d. The worker
  respells it as "Lojuret" for both voices (locales/sv.py SPOKEN_RESPELLINGS), so in
  production these rules only take effect if that respelling is removed. They are
  here so a listening probe can compare the IPA rule with the respelling on Bella
  (server/README.md, "Swedish pronunciation").
-->
<lexicon version="1.0"
    xmlns="http://www.w3.org/2005/01/pronunciation-lexicon"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.w3.org/2005/01/pronunciation-lexicon http://www.w3.org/TR/2007/CR-pronunciation-lexicon-20071212/pls.xsd"
    alphabet="ipa" xml:lang="sv-SE">
  <lexeme>
    <grapheme>Lodjur</grapheme>
    <grapheme>lodjur</grapheme>
    <phoneme>ˈluːˌjʉːr</phoneme>
  </lexeme>
  <lexeme>
    <grapheme>Lodjuret</grapheme>
    <grapheme>lodjuret</grapheme>
    <phoneme>ˈluːˌjʉːrɛt</phoneme>
  </lexeme>
  <lexeme>
    <grapheme>Lodjurets</grapheme>
    <grapheme>lodjurets</grapheme>
    <phoneme>ˈluːˌjʉːrɛts</phoneme>
  </lexeme>
  <lexeme>
    <grapheme>Lodjuren</grapheme>
    <grapheme>lodjuren</grapheme>
    <phoneme>ˈluːˌjʉːrɛn</phoneme>
  </lexeme>
</lexicon>
