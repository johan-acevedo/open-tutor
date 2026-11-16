// Multi-core pdn without SharedArrayBuffer (so no cross-origin isolation / COOP+COEP): K workers, each with its own wasm
// instance and weights, talking by postMessage with transferred buffers.
//   const p = await createPool(pdnBytes, wasmBytes, { workers: 4, relaxed, int8 });
//   await p.synth(ids)        one sentence split across all workers (each runs the text side + trunk, then decodes 1/K of the
//                             head / DSP frames; bit-identical to the 1-thread result): lower latency per sentence
//   await p.synthOne(ids)     one sentence on the next free worker: K sentences in flight = K x throughput
const node = typeof process !== "undefined" && process.versions?.node;
export async function createPool(pdn, wasm, opts = {}) {
  const K = opts.workers || 2; const url = new URL("./pdn_worker.mjs", import.meta.url); const ws = [];
  const Worker = node ? (await import("node:worker_threads")).Worker : globalThis.Worker;
  for (let i = 0; i < K; i++) {
    const w = node ? new Worker(url) : new Worker(url, { type: "module" }); const q = new Map();
    const onmsg = (m) => { const r = q.get(m.id ?? "init"); if (r) { q.delete(m.id ?? "init"); r(m); } };
    node ? w.on("message", onmsg) : (w.onmessage = (ev) => onmsg(ev.data));
    const ready = new Promise((r) => q.set("init", r));
    w.postMessage({ op: "init", pdn: pdn.slice().buffer, wasm: wasm.slice().buffer, relaxed: opts.relaxed, int8: opts.int8 }); await ready;
    ws.push({ w, q, busy: 0 });
  }
  let nid = 0, nseed = 1;
  const call = (x, msg) => new Promise((r) => { const id = ++nid; x.q.set(id, r); x.busy++; x.w.postMessage({ ...msg, id }); }).then((m) => { x.busy--; return m; });
  return {
    workers: K,
    async synth(ids, speed = 1) {
      const seed = nseed++; const parts = await Promise.all(ws.map((x, k) => call(x, { op: "part", ids, speed, seed, k, K })));
      const n = parts.reduce((s, p) => s + p.wave.length, 0), out = new Float32Array(n);
      for (const p of parts) out.set(p.wave, p.start); return out;
    },
    async synthOne(ids, speed = 1) { const x = ws.reduce((a, b) => (b.busy < a.busy ? b : a)); return (await call(x, { op: "synth", ids, speed })).wave; },
    close() { for (const x of ws) x.w.terminate(); },
  };
}
