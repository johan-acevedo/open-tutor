// STT in a Worker: Cactus WASM + Whistle model. Main thread posts:
//   {op:'load'} -> {op:'loaded'} | {op:'error', message}
//   {op:'transcribe', turnId, audio: Float32Array@16kHz (transferred)}
//     -> {op:'transcript', turnId, text, ms} | {op:'error', turnId, message}
importScripts("../vendor/cactus/cactus.js");

let M = null, outPtr = 0, outCap = 65536, ready = null, readyBytes = [];

function load() {
  if (ready) return ready;
  ready = (async () => {
    const wasmUrl = new URL("vendor/cactus/cactus.wasm", self.location.href).href;
    const wasmBinary = await (await fetch(wasmUrl)).arrayBuffer();
    readyBytes.push(["/vendor/cactus/cactus.wasm", wasmBinary.byteLength]);
    M = await createCactus({
      wasmBinary,
      locateFile: (p) => new URL("vendor/cactus/" + p, self.location.href).href,
    });
    const res = await fetch(new URL("vendor/models/whistle.cact", self.location.href).href);
    if (!res.ok) throw new Error("whistle.cact HTTP " + res.status);
    const bytes = new Uint8Array(await res.arrayBuffer());
    readyBytes.push(["/vendor/models/whistle.cact", bytes.length]);
    const ptr = M._malloc(bytes.length);
    M.HEAPU8.set(bytes, ptr);
    const rc = M._cactus_load(ptr, BigInt(bytes.length));
    M._free(ptr);
    if (rc !== 0) throw new Error("cactus_load failed: " + M.UTF8ToString(M._cactus_last_error()));
    M.ccall("cactus_set_threads", null, ["number"], [Math.min(4, (self.navigator?.hardwareConcurrency || 4))]);
    outPtr = M._malloc(outCap);
  })();
  return ready;
}

self.onmessage = async ({ data: m }) => {
  try {
    if (m.op === "load") { await load(); self.postMessage({ op: "loaded", bytes: readyBytes }); return; }
    if (m.op === "transcribe") {
      await load();
      const t0 = performance.now();
      const pcm = m.audio; // Float32Array, 16 kHz mono
      const pPtr = M._malloc(pcm.length * 4);
      new Float32Array(M.HEAPU8.buffer, pPtr, pcm.length).set(pcm);
      const rc = M.ccall("cactus_transcribe", "number",
        ["number", "number", "string", "string", "number", "number", "number"],
        [pPtr, pcm.length, "en", "", 0, outPtr, outCap]);
      M._free(pPtr);
      if (rc < 0) {
        let err = "";
        try { const p = M._cactus_last_error(); err = p ? M.UTF8ToString(p) : ""; } catch {}
        throw new Error("cactus_transcribe failed: " + err);
      }
      // The engine returns a JSON payload ({"text", "language", "ttft_ms", ...}), rc >= 0 means success.
      const raw = M.UTF8ToString(outPtr).trim();
      let text = raw;
      try { text = (JSON.parse(raw).text || "").trim(); } catch {}
      self.postMessage({ op: "transcript", turnId: m.turnId, text, ms: performance.now() - t0 });
    }
  } catch (e) { self.postMessage({ op: "error", turnId: m.turnId, message: String(e?.stack || e) }); }
};
