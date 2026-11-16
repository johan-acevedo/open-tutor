# mesm-tts Heart (v2f / v2f_lite / v2g) for the web: pdn engine + misaki-lite front end

Everything to speak with Heart v2f (or v2f_lite, v2g) in a browser (or Node), on the CPU, with no server and no onnxruntime-web:
**pdn**, a dedicated WebAssembly engine for this graph family (38 kB brotli), the v2f / v2f_lite / v2g weights, and **misaki-lite**, the misaki
phonemizer the model was trained on, ported to JavaScript.

```js
import { loadParadee } from "./paradee.mjs";
const tts = await loadParadee({ model: "v2f" });          // "v2f" (default), "v2f_lite" or "v2g"
const audio = await tts.synth("Hello there. How are you?");   // Float32Array, 24 kHz mono
for await (const chunk of tts.stream(longText)) player.push(chunk);   // streaming: first chunk after ~20-40 ms
```

## Files
| path | what |
|---|---|
| `paradee.mjs` | the API: `loadParadee(options)` -> `{ synth, stream, phonemize, plan, info, engine }` (main thread, Worker or Node 20+) |
| `paradee-worker.mjs` | the same in a module Worker (recommended: synthesis is synchronous WASM): `load` / `speak` / `stop` messages, audio chunks back |
| `player.mjs`, `player-worklet.js` | streaming playback: an AudioWorklet queue player in a 24 kHz AudioContext; reports start, finish, underruns |
| `engine/pdn.wasm`, `engine/pdn_r.wasm`, `engine/pdn.mjs` | the engine: SIMD128 build (every browser with WASM SIMD: Chrome / Edge 91+, Firefox 89+, Safari 16.4+) and relaxed-SIMD build (FMA + int8 dot products; Chrome / Edge 114+), picked at load by validating a 72-byte probe module; `pdn_worker.mjs` / `pdn_pool.mjs`: optional multi-worker split |
| `models/v2f.pdn`, `models/v2f_lite.pdn`, `models/v2g.pdn` | the weights (see MANIFEST.json for which release file each was converted from; lossless re-encoding of the 4/6/8-bit grids: 4-bit codes two per byte, 5-8-bit codes one per byte, which is larger raw but compresses better; embedding rows of ids the tokenizer never emits are stored as zeros) |
| `frontend/` | misaki-lite (`misaki_lite.mjs`), its lexicons (`lex/`: 256 + 256 shards fetched as sentences need them; `us_gold.fc.txt` + `us_silver.fc.txt`, the complete files, in the background), the tokenizer, and the eSpeak NG fallback chain (`espeak_chain.mjs`, `kokoro-phonemize.mjs`, `misaki.js`) |
| `integrations/chickadee_pdn.js` | drop-in `loadParadee()` for Chickadee's `extension/src/engine.js` (steps inside) |
| `example.html` | a minimal page: worker + player |
| `check.mjs`, `check.json` | self-check: `node check.mjs` (front end == misaki, SIMD128 renders == the native engine byte for byte, relaxed within 1e-3, int8 runs, timing) |
| `MANIFEST.json`, `SHA256SUMS` | sizes (raw and brotli), hashes, model sources |

## Integration
1. **Serve the directory** as static files (any server; brotli or gzip if it can: the weights and lexicon compress ~15-70%).
   No COOP/COEP headers are needed: pdn uses no SharedArrayBuffer. Extensions (MV3): the existing
   `script-src 'self' 'wasm-unsafe-eval'` CSP is enough.
2. **Load** in a Worker: `new Worker(new URL("./paradee-worker.mjs", import.meta.url), { type: "module" })`, post
   `{ op: "load", model: "v2f", text }` (`text`: the first text if you already have it: it is phonemised while the weights load),
   wait for `{ op: "loaded" }` (about 0.1-0.2 s on a laptop: engine, weights, the lexicon index; the lexicon shards a sentence
   needs are fetched with it, and eSpeak NG and the complete lexicons load in the background after the first sentence).
3. **Play**: create the player from a user gesture (`await createPlayer()`), `player.reset()`, post `{ op: "speak", id, text }`, and
   `player.push(samples)` for every `{ op: "chunk" }`; `player.end()` on `{ op: "done" }`. `{ op: "sentence" }` gives each sentence's
   text and phonemes before its audio, for highlighting.
4. **eSpeak NG fallback** (words outside misaki's lexicon: 3.5% of DEV words, mostly names). `frontend/kokoro-phonemize.mjs`
   imports the bare specifier `phonemizer` (npm `phonemizer`, the package kokoro-js uses). With a bundler (esbuild, Vite, webpack)
   that resolves by itself (`npm i phonemizer`). Without one, pass `espeakUrl` (a module exporting `phonemize(text, lang)`, e.g. a
   copy of `kokoro-phonemize.mjs` whose import points at `phonemizer/dist/phonemizer.js`) or, on the same thread, `espeak: () => import(...)`.
   Licence note: see LICENSES.md (eSpeak NG is GPL-3.0; it is not in this bundle).
5. **Cache** the weights across visits (Cache Storage under a versioned name, or immutable HTTP caching: the file names are
   versioned by the release).

Options of `loadParadee`: `model`, `int8` (default true), `relaxed` (default: auto), `frontend` ("misaki-lite"; "espeak" =
Chickadee's old chain, for comparison only), `espeak` / `espeakUrl`, `lexicon` ("sharded", default | "full": both complete
files before ready), `text` (phonemise the first sentences while loading), `warmup` (default true), `base`
(the bundle's URL when a bundler moves `paradee.mjs`, e.g. `chrome.runtime.getURL("paradee/")`). Sentences are split at . ! ? …
and over-long ones at clause punctuation to fit the model's 512-phoneme window; `speed` scales durations (synth / stream option).

## Numbers (single thread; see ../MODEL_CARD.md for quality)
Speed: this bundle's own engine files on TEST-200, Node 26 (V8) on one reserved desktop x86 core, interleaved with v1.1 int8 on
onnxruntime-web 1.22 (Chickadee's build; 15.2x realtime there); onnxruntime-web rows from the project's progression ladder. Headless
Chrome agrees within ~3%. v2g column: the progression ladder's run (runs/ladder/r3, same protocol). v2f is the default; v2g is
faster and smaller and passed the project's quality rule against v2f (see the model card, "v2g").

| | **v2f** (`models/v2f.pdn`) | **v2f_lite** (`models/v2f_lite.pdn`) | **v2g** (`models/v2g.pdn`) |
|---|---|---|---|
| pdn, relaxed SIMD, int8 | **147x realtime, 9.65x v1.1** | 184x, 12.1x | 201x, 12.9x |
| pdn, SIMD128, int8 | 107x, 7.0x | 130x, 8.6x | 140x, 9.0x |
| pdn, relaxed / SIMD128, fp32 mode | 122x / 102x | 145x / 122x | 157x / 132x |
| onnxruntime-web 1.22, the release ONNX file | 73x, 4.9x | 85x, 5.6x | 96x, 6.0x |
| fresh process to the first audio of a short sentence / peak RSS (onnxruntime-web) | 83 ms / 117 MB (2.6 s / 849 MB) | 74 ms / 106 MB (2.6 s / 774 MB) | 60 ms / 100 MB (2.3 s / 770 MB) |
| time to first audio, streaming, median 6.6 s sentence (relaxed int8; p90) | 29 ms (46) | 20 ms (32) | 10 ms (16): the text side streams too |
| weights, raw / brotli | 3.53 / 2.95 MB | 2.67 / 2.22 MB | 2.34 / 1.95 MB |
| engine memory after load (int8) / peak over TEST-200 (longest sentence 12.8 s) | 29 / 88-93 MB | 26 / 80-85 MB | not measured |

Download before the first audio: engine 38 kB + weights + the lexicon shards the first sentence needs (~90 kB median on DEV /
XDEV, 2 small round trips; the result is exactly the complete lexicon's: tools/lexicon_shard_check.mjs) + eSpeak NG (638 kB) only
if that sentence has a word outside misaki's lexicons. In the background afterwards: the complete lexicons (0.99 MB) and eSpeak NG. Load to ready: 0.13-0.21 s in Chrome (onnxruntime-web: ~2.6 s, mostly compiling its 21.6 MB wasm). Memory is the
wasm heap: per-call buffers grow with the sentence (~4.5 MB per second of audio) and a wasm heap never shrinks, so the peak is set
by the longest sentence (onnxruntime-web v2f: ~0.8 GB peak).

Front end, DEV-400 (pdn v2f int8, same noise, vs the misaki phonemes the model was trained and scored on): misaki-lite gives the
same token ids for 87.5% of sentences (0.21% token edits) and **WER +0.06 pp [-0.07, +0.20], within noise**; the eSpeak NG chain
(what Chickadee shipped) matches 2.3% of sentences (7.0% token edits) and costs **+0.97 pp WER [+0.49, +1.45]**.
