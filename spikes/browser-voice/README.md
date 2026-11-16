# Voice tutor spike: in-browser STT + VAD + TTS, cloud LLM

One static page (`index.html`): talk to an English tutor. Speech-to-text and
voice activity detection run in the browser tab; text-to-speech runs in the
browser tab; the LLM is called straight from the page. **No backend of ours.**

## Stack

| Part | What | Wire |
|---|---|---|
| VAD | Silero VAD **fp32** (`onnx-community/silero-vad` `onnx/model.onnx`, 2.2 MB) via `@ricky0123/vad-web` + `onnxruntime-web` 1.22 (threaded wasm, needs COOP/COEP) | ~2.2 + ~11.3 MB |
| STT | Whistle (`Cactus-Compute/whistle` `whistle.cact`, 16.9 MB) with the Cactus WASM engine (`Cactus-Compute/cactus` `releases/4.1.1/wasm/`) in a Worker. Plain-text output is JSON (`{"text",…}`); `rc >= 0` means success. English only. | ~18.2 MB |
| TTS | mesm-tts **Heart v2** (`mesmertech/mesm-tts` `web/v2`, voice `v2f.pdn`) — `.pdn` WASM engine, misaki-lite frontend. **No espeak fallback** (GPL): words outside the lexicon fail that sentence with a visible ⚠️ and the turn continues. Sentence-by-sentence synth in a Worker, chunks streamed to an AudioWorklet player. | ~7.7 MB incl. background lexicons |
| LLM | Model selector. Default: `meta/muse-spark-1.3-contributor` via the Command Code **Responses** endpoint with `reasoning: {effort: "minimal"}`, `max_output_tokens: 400`. Alternative: `deepseek/deepseek-v4.1-flash` via **chat completions** with `thinking: {type: "disabled"}`, `max_tokens: 400`. Key lives in `localStorage` only; direct browser→API call. | 0 (cloud) |
| Cache | Service worker (cache-first for `vendor/`) + Cache API. Second visit ≈ 0.1 MB. | — |
| **Total** | | **≈ 37–38 MB on the wire** (measured 37.5), budget 50 MB |

Why fp32 VAD: the int8 model (`model_int8.onnx`, 639 kB) fails to create a
session on onnxruntime-web 1.22 — the web wasm build has no `ConvInteger`
kernel. The fp32 build (2.2 MB) works and is still tiny.

## Use it

1. Serve this folder over HTTPS (mic requires it), e.g. `python3 server.py 8001`
   then `tailscale serve --bg --https=8445 http://127.0.0.1:8001`.
   `server.py` sends COOP/COEP (ORT threads) + immutable caching for `vendor/`.
2. Open the URL, paste the Command Code key, pick a model, press Start.
3. Talk. Interrupt the tutor by speaking (barge-in stops TTS + the LLM stream).

Panels: live transcript, per-turn timings, per-asset download bytes
(Resource Timing + worker byte counters).

## Measured (headless Chromium, fake mic, 3 LibriSpeech turns, 2026-11-16)

Muse Spark 1.3 (Responses, reasoning minimal):

| turn | eos→transcript | transcript→1st token | 1st token→1st audio | total eos→audio |
|---|---|---|---|---|
| 1 | 1556 ms | 1737 ms | 42 ms | 3337 ms |
| 2 | 1891 ms | 1517 ms | 46 ms | 3455 ms |
| 3 | 2608 ms | 2172 ms | 39 ms | 4819 ms |

DeepSeek V4.1 Flash, 1 turn: 1540 / 2211 / 127 / 3881 ms.
Second visit wire: 0.13 MB (SW cache). Transcripts matched the refs word for
word; tutor replies streamed; TTS audio verified (AudioContext output).

## Automated test

`test/spike-test.mjs` (needs `puppeteer-core`, drives cached Chrome with
`--use-file-for-fake-audio-capture=test/fixture-turns.wav`): asserts the
transcript appears, an LLM reply streams, TTS audio plays, and prints the
timing panel. Key comes from `$VOICE_SPIKE_KEY` or
`~/.pi/agent/auth.json` (commandcode) at test time only — never committed.
`VOICE_SPIKE_MODEL=deepseek` switches the model under test.

## Known gaps

- No real-device proof yet: verify on desktop Chrome + Safari, and iPhone
  (AudioContext unlock on tap; 24 kHz AudioContext sample rate; memory —
  pdn heap ~90 MB peak, ort threaded wasm, 17 MB Whistle in a worker).
- Barge-in is echo-prone on speakers+mic: VAD uses echo cancellation, but the
  tutor's own voice can re-trigger it. Also barge-in only counts while the
  tutor is audibly speaking; overlap while thinking is queued.
- OOV words (outside misaki-lite lexicon, ~3.5%) skip their sentence with a
  ⚠️ — espeak fallback deliberately not bundled (GPL). Tutor prompt constrains
  vocabulary to common words.
- `cactus_transcribe` returns JSON text + `rc >= 0` on success (not 0);
  language must be explicit (`"en"`, no auto-detect in this build).
- ort 1.22 needs its `.mjs` loader file next to the wasm, and `wasmPaths`
  must be an absolute URL when set programmatically.
