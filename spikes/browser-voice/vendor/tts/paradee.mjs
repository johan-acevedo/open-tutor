// Paradee text-to-speech in the browser (or Node): text -> misaki-lite phonemes -> pdn (WebAssembly) -> 24 kHz mono audio.
// Works on the main thread, in a Worker (recommended: synthesis is synchronous WASM) and in Node 20+.
//
//   import { loadParadee } from "./paradee.mjs";
//   const tts = await loadParadee({ model: "v2f" });              // "v2f" | "v2f_lite" | "v2g" | URL | Uint8Array of a .pdn
//   const audio = await tts.synth("Hello there. How are you?"); // Float32Array @ tts.sampleRate (24000)
//   for await (const chunk of tts.stream(longText)) player.push(chunk);   // first chunk after ~20-40 ms on a laptop core
//
// Options: int8 (default true: the int8 candidates' numerics, faster), relaxed (default: auto-detect relaxed SIMD, else SIMD128),
// frontend ("misaki-lite" default | "espeak": Chickadee's eSpeak chain, for comparison only: +0.97 pp WER on DEV), espeak /
// espeakUrl (loader function / module URL for the eSpeak NG fallback, see README), lexicon ("sharded", default: only the lexicon
// shards a sentence needs, the complete lexicons in the background | "full": both complete files at load), text (the first text,
// if known: its first sentences are phonemised while the engine and weights load),
// warmup (one tiny synthesis at load so the first sentence is fast, default true), base (URL of the bundle directory; default:
// next to this file; set it when a bundler moves this module, e.g. chrome.runtime.getURL("paradee/") in an extension).
import { createEngine, relaxedSimdSupported } from "./engine/pdn.mjs";
import { loadTokenizer, tokenize } from "./frontend/tokenizer.mjs";
import { setEspeak, loadEspeak, textToPhonemes as espeakChain } from "./frontend/espeak_chain.mjs";
import { loadShardedLexicon, useFullLexicon, parseLexicon, g2p } from "./frontend/misaki_lite.mjs";

export const SAMPLE_RATE = 24000;
export { relaxedSimdSupported };
const isNode = typeof process !== "undefined" && !!process.versions?.node;
const MAX_IDS = 512;

// Node reads files, the browser fetches URLs
const loc = (u) => (isNode && u.protocol === "file:" ? decodeURIComponent(u.pathname) : u.href);
async function readText(u) {
  if (isNode && u.protocol === "file:") { const fs = await import("node:fs"); return fs.readFileSync(decodeURIComponent(u.pathname), "utf8"); }
  const r = await fetch(u.href); if (!r.ok) throw new Error(`${u.href}: HTTP ${r.status}`); return r.text();
}

// Sentences: split after . ! ? … (and any closing quotes / brackets) followed by a capital, digit, quote or bracket (the unit the
// model was trained on), except after titles, common abbreviations and initials ("Dr. Smith", "J. R. R. Tolkien", "U.S. Army").
const ABBREV = /(?:^|[\s"“(])(?:Mr|Mrs|Ms|Dr|St|Jr|Sr|Prof|Rev|Gen|Gov|Sen|Rep|Capt|Lt|Col|Sgt|Adm|Mt|Ft|No|Nos|vs|etc|Inc|Ltd|Co|Corp|Bros|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|[A-Z]|(?:[A-Za-z]\.)+[A-Za-z])\.$/;
export function splitSentences(text) {
  const out = [];
  for (const p of text.replace(/\s+/g, " ").trim().split(/(?<=[.!?…]["”’')\]]*)\s+(?=[A-Z"“(\d])/)) {
    if (out.length && ABBREV.test(out[out.length - 1])) out[out.length - 1] += " " + p; else out.push(p);
  }
  return out.map((s) => s.trim()).filter(Boolean);
}
// A phoneme string longer than the model's 512-id window is cut at the last clause punctuation, else the last word break,
// before the limit (each piece keeps its own '$' ends).
function splitPhonemes(ps, max = MAX_IDS - 12) {
  const out = []; let s = ps;
  while ([...s].length > max) {
    const head = [...s].slice(0, max).join("");
    let k = Math.max(...[", ", "; ", ": ", "— ", "… "].map((p) => head.lastIndexOf(p)));
    k = k > max / 3 ? k + 1 : head.lastIndexOf(" "); if (k <= 0) k = head.length;
    out.push(s.slice(0, k).trim()); s = s.slice(k).trim();
  }
  if (s) out.push(s); return out;
}

export async function loadParadee(opts = {}) {
  const base = new URL(opts.base ?? "./", import.meta.url);
  const { model = "v2f", int8 = true, frontend = "misaki-lite", lexicon = "sharded", warmup = true } = opts;
  const lite = frontend !== "espeak";
  const t0 = performance.now();
  setEspeak(opts.espeak ?? (opts.espeakUrl ? () => import(new URL(opts.espeakUrl, base).href) : () => import("./frontend/kokoro-phonemize.mjs")));
  const pdnSrc = model instanceof Uint8Array || model instanceof ArrayBuffer ? model
    : loc(/^[\w-]+$/.test(model) ? new URL(`models/${model}.pdn`, base) : new URL(model, base));
  const relaxed = opts.relaxed ?? relaxedSimdSupported();
  // misaki-lite's lexicon. Sharded: an index + the always-needed entries now (2 kB), the shards a sentence needs when it is
  // phonemised (~90 kB for a typical first sentence instead of 0.5-1 MB; the output is exactly the complete lexicon's), the
  // complete lexicons in the background once the first sentence is done. Full: both complete files before ready.
  const full = () => Promise.all([readText(new URL("frontend/us_gold.fc.txt", base)), readText(new URL("frontend/us_silver.fc.txt", base))])
    .then(([g, s]) => useFullLexicon(parseLexicon(g), parseLexicon(s)));
  const lexSetup = !lite ? null : lexicon === "full" ? full() : loadShardedLexicon((f) => readText(new URL(`frontend/lex/${f}`, base)));
  // the caller's first text: phonemise its first sentences while the engine and weights load
  const early = new Map();
  if (lite && opts.text) for (const s of splitSentences(opts.text).slice(0, 2)) { const p = lexSetup.then(() => g2p(s)); p.catch(() => {}); early.set(s, p); }
  const [engine] = await Promise.all([
    createEngine(pdnSrc, { int8, relaxed, warmup, wasm: opts.wasm ?? loc(new URL(`engine/${relaxed ? "pdn_r" : "pdn"}.wasm`, base)) }),
    readText(new URL("frontend/tokenizer.json", base)).then((t) => loadTokenizer(JSON.parse(t))),
    lexSetup,
  ]);
  // Background work (the complete lexicons, eSpeak NG) starts once the first audio chunk exists (or 2 s after load if nothing is
  // said), so its download and parsing never delay the first sound; a sentence that needs eSpeak NG still loads it at once.
  // The eSpeak chain needs eSpeak NG for everything, so there loading waits for it.
  let bg = null; const ready = { lex: null, esp: null }; const lexiconReady = new Promise((r) => (ready.lex = r)), espeakReady = new Promise((r) => (ready.esp = r));
  const background = () => bg ??= Promise.all([
    (lite && lexicon !== "full" ? full() : Promise.resolve()).then(ready.lex, ready.lex),
    loadEspeak().then(() => ready.esp(performance.now() - t0), (e) => ready.esp(Promise.reject(e))),
  ]);
  if (!lite) { background(); await espeakReady; } else { const tm = setTimeout(background, 2000); tm.unref?.(); }
  espeakReady.catch(() => {});
  const phonemize = lite ? g2p : espeakChain;

  async function sentenceIds(sentence) {
    const p = early.get(sentence); early.delete(sentence);
    const ps = await (p ?? phonemize(sentence));
    return splitPhonemes(ps).map((p) => ({ phonemes: p, ids: tokenize(p) }));
  }
  return {
    sampleRate: SAMPLE_RATE,
    info: { model: typeof model === "string" ? model : "(bytes)", build: engine.relaxed ? "relaxed-simd" : "simd128", int8, frontend: lite ? "misaki-lite" : "espeak",
            load_ms: performance.now() - t0, memory_bytes: engine.memoryBytes() },
    espeakReady, lexiconReady, silverReady: lexiconReady, engine, splitSentences,
    // one sentence -> misaki-style phoneme string
    phonemize,
    // text -> [{ sentence, phonemes, ids }] (sentences, long ones split to fit the model)
    async plan(text) {
      const out = [];
      for (const s of splitSentences(text)) for (const p of await sentenceIds(s)) out.push({ sentence: s, ...p });
      return out;
    },
    // whole text -> one Float32Array (sentences back to back, the model's own leading / trailing silence kept)
    async synth(text, { speed = 1 } = {}) {
      const parts = []; let n = 0;
      for (const s of splitSentences(text)) for (const { ids } of await sentenceIds(s)) { const y = engine.synth(ids, speed); parts.push(y); n += y.length; background(); }
      const y = new Float32Array(n); let o = 0; for (const p of parts) { y.set(p, o); o += p.length; } return y;
    },
    // text -> Float32Array chunks as soon as they are ready: per sentence, the text side + trunk run first, then the head / DSP
    // in chunks of `first`, then `chunk` 80-fps frames (bit-identical in total to synth in fp32; int8 within DEV noise).
    // onSentence(i, sentence, phonemes) fires before each sentence's first chunk (for highlighting).
    async *stream(text, { speed = 1, first = 16, chunk = 40, onSentence } = {}) {
      let i = 0;
      for (const s of splitSentences(text)) for (const { phonemes, ids } of await sentenceIds(s)) {
        onSentence?.(i++, s, phonemes);
        for (const c of engine.stream(ids, speed, first, chunk)) { yield c; background(); }
      }
    },
  };
}
