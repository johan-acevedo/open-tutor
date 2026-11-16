// eSpeak NG -> misaki spelling, the text front end Chickadee ships: kokoro-js's phonemize (text normalisation + eSpeak NG via the
// `phonemizer` package, American English) -> upstream web/misaki.js. misaki-lite uses it only for words its lexicon cannot
// resolve, as misaki itself falls back to eSpeak. eSpeak NG is a 1.3 MB module: it is imported on first use, through a loader the
// host sets with setEspeak() (a bundler resolves "./kokoro-phonemize.mjs"'s bare "phonemizer" import; a plain page or worker
// passes a loader for a module with the same phonemize(text, lang) export).
import { toMisaki } from "./misaki.js";
let loader = null, espeakMod = null, espeakInit = null;
export function setEspeak(load) { loader = load; espeakMod = espeakInit = null; }   // load: () => Promise<{ phonemize(text, lang) }>
// fetch + instantiate eSpeak NG once (concurrent first calls share it)
export const loadEspeak = () => {
  if (!loader) throw new Error("eSpeak NG loader not set (setEspeak)");
  return (espeakInit ??= (espeakMod ??= loader()).then((m) => m.phonemize("Hi.", "a")));
};
export async function textToPhonemes(text) { await loadEspeak(); const { phonemize } = await espeakMod; return toMisaki(await phonemize(text, "a")); }
