// TTS in a module Worker: vendored mesm-tts paradee (Heart v2), sentence by
// sentence, audio chunks streamed back. No espeak fallback is loaded (GPL), so
// words outside misaki-lite's lexicon fail that sentence with a clear error.
// Main thread posts:
//   {op:'load'} -> {op:'loaded', info} | {op:'error', message}
//   {op:'synth', turnId, i, text} -> {op:'sentence', turnId, i, text} then
//     {op:'chunk', turnId, i, samples (transferred)}... then
//     {op:'sentDone', turnId, i, computeMs} | {op:'sentError', turnId, i, message}
//   {op:'stop', turnId} -> drops the in-flight sentence.
import { loadParadee } from "../vendor/tts/paradee.mjs";

let tts = null, cancelled = 0, ready = null;

function resEntries() {
  // Our own fetches (modules, engine, weights, lexicon shards) with wire sizes.
  return performance.getEntriesByType("resource")
    .filter((e) => e.name.startsWith(self.location.origin))
    .map((e) => [new URL(e.name).pathname, e.transferSize || e.decodedBodySize || 0]);
}

function noEspeak() {
  return Promise.reject(new Error("espeak fallback disabled in this spike (GPL); word outside misaki-lite lexicon"));
}

function load() {
  if (ready) return ready;
  ready = (async () => {
    tts = await loadParadee({ model: "v2f", espeak: noEspeak });
  })();
  return ready;
}

self.onmessage = async ({ data: m }) => {
  try {
    if (m.op === "load") { await load(); self.postMessage({ op: "loaded", info: tts.info, bytes: resEntries() }); return; }
    if (m.op === "stop") { cancelled = m.turnId; return; }
    if (m.op === "synth") {
      await load();
      const myTurn = m.turnId;
      if (myTurn === cancelled) return;
      const t0 = performance.now();
      try {
        self.postMessage({ op: "sentence", turnId: myTurn, i: m.i, text: m.text });
        for await (const c of tts.stream(m.text)) {
          if (myTurn === cancelled) return; // stopped
          self.postMessage({ op: "chunk", turnId: myTurn, i: m.i, samples: c }, [c.buffer]);
          await new Promise((r) => setTimeout(r, 0)); // let a "stop" in
        }
        self.postMessage({ op: "sentDone", turnId: myTurn, i: m.i, computeMs: performance.now() - t0, bytes: resEntries() });
      } catch (e) {
        if (myTurn === cancelled) return;
        self.postMessage({ op: "sentError", turnId: myTurn, i: m.i, message: String(e?.message || e), bytes: resEntries() });
      }
    }
  } catch (e) { self.postMessage({ op: "error", turnId: m.turnId, message: String(e?.stack || e) }); }
};
