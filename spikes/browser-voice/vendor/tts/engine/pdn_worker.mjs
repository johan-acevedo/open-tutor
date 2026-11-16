// pdn worker (Web Worker or Node worker_threads): its own wasm instance + weights. Messages:
//   {op: "init", pdn, wasm, relaxed, int8} -> {op: "ready"}
//   {op: "synth", id, ids, speed} -> {id, wave}            whole sentence (sentence-parallel pool)
//   {op: "part", id, ids, speed, seed, k, K} -> {id, k, start, wave}   share k of K of one sentence (split mode)
import { createEngine } from "./pdn.mjs";
const node = typeof process !== "undefined" && process.versions?.node;
const port = node ? (await import("node:worker_threads")).parentPort : self;
const on = (f) => (node ? port.on("message", f) : (port.onmessage = (ev) => f(ev.data)));
let e = null;
on(async (m) => {
  if (m.op === "init") { e = await createEngine(new Uint8Array(m.pdn), { wasm: new Uint8Array(m.wasm), relaxed: m.relaxed, int8: m.int8 }); port.postMessage({ op: "ready" }); return; }
  if (m.op === "synth") { const w = e.synth(m.ids, m.speed); port.postMessage({ id: m.id, wave: w }, [w.buffer]); return; }
  if (m.op === "part") { const r = e.part(m.ids, m.speed, m.seed, m.k, m.K); port.postMessage({ id: m.id, k: m.k, start: r.start, wave: r.samples }, [r.samples.buffer]); }
});
