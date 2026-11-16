// Cache-first service worker for the spike: second visit downloads nothing.
const CACHE = "voice-spike-v1";
const PRECACHE = [
  "./", "index.html", "style.css", "app.js", "stt-worker.js", "tts-worker.js",
  "vendor/ort/ort.wasm.min.js",
  "vendor/ort/ort-wasm-simd-threaded.wasm",
  "vendor/vad/vad.bundle.min.js",
  "vendor/vad/vad.worklet.bundle.min.js",
  "vendor/vad/silero_vad_v5.onnx",
  "vendor/cactus/cactus.js",
  "vendor/cactus/cactus.wasm",
  "vendor/models/whistle.cact",
  "vendor/tts/paradee.mjs",
  "vendor/tts/player.mjs",
  "vendor/tts/player-worklet.js",
  "vendor/tts/engine/pdn.mjs",
  "vendor/tts/engine/pdn.wasm",
  "vendor/tts/engine/pdn_r.wasm",
  "vendor/tts/frontend/misaki_lite.mjs",
  "vendor/tts/frontend/tokenizer.mjs",
  "vendor/tts/frontend/tokenizer.json",
  "vendor/tts/frontend/misaki.js",
  "vendor/tts/frontend/espeak_chain.mjs",
  "vendor/tts/frontend/lex/always.txt",
  "vendor/tts/frontend/lex/index.json",
  "vendor/tts/frontend/us_gold.fc.txt",
  "vendor/tts/frontend/us_silver.fc.txt",
  "vendor/tts/models/v2f.pdn",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;
  // Cache-first for vendored assets and lexicon shards; network-first for the app shell.
  if (u.pathname.includes("/vendor/")) {
    e.respondWith(caches.open(CACHE).then(async (c) => {
      const hit = await c.match(e.request);
      if (hit) return hit;
      const res = await fetch(e.request);
      if (res.ok) c.put(e.request, res.clone());
      return res;
    }));
  }
});
