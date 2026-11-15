# Browser voice models, November 2026: STT + VAD + TTS that fit in a tab

Research for the open-tutor voice tutor: speech runs **entirely in the browser**
(ONNX Runtime Web / Transformers.js / WASM / WebGPU), the LLM stays a cloud API.
Web Speech API and Gemini Nano are out of scope. Research only — no product code.

- Window for "new": **2026-09-20 → 2026-11-15**. Dates below are `createdAt` from
  `https://huggingface.co/api/models/<id>` unless noted.
- Sizes below are the **download sizes of the files the browser actually needs**
  (from `…/api/models/<id>?blobs=true`), not marketing numbers.
- "Measured" = run by me on CPU in `~/scratch/browser-voice-research/`
  (LibriSpeech test-clean clips for STT, 3 fixed sentences for TTS, whisper
  tiny.en int8 as the TTS intelligibility judge). Repro commands: Appendix.
- Bottom line up front: **Whistle (STT, 16.9 MB) + Silero int8 (VAD, 0.64 MB) +
  mesm-tts Heart v2 (TTS, ~8 MB incl. frontend) ≈ 26–28 MB on the wire** —
  well under the 50 MB budget, Apache-2.0 throughout, no espeak/GPL anywhere.

## Ranked shortlist (details + risks in §5)

| Use | Pick | Wire size | Risk in one line |
|---|---|---|---|
| English default | Whistle + Silero-int8 + mesm-tts Heart v2 | **≈ 26–28 MB** | All three maturities are weeks old; Whistle's benchmarks are vendor-run. |
| Multilingual (7–8 langs) | Same STT/VAD + one Kitten TTS 2 Pico model per language | ≈ 26 MB + **8 MB per extra TTS language** | Pico per-language quality outside en/de/fr is unreviewed; 3+ languages approach the budget. |

Swedish: no in-window small Swedish model exists (gap noted honestly in §5).

## 1. TTS candidates

"DL" = what the browser downloads for **one voice**. ORT = onnxruntime-web unless noted.

| Model | Release (verified) | Params | DL per required file | Runtime path | Langs | Stream | Measured RTF | Measured WER | License | Phonemizer dep | Maturity | Browser demo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [tiny-voca](https://huggingface.co/n4ze3m/tiny-voca) ⭐ new | 2026-11-14 (`createdAt`) | 4.5M | model.onnx **21.39 MB** + g2p.npz 1.84 + lexicon.tsv 3.45 (+align/homographs ~0.1) + ORT-web ~2 + **Pyodide ~10–12** → **≈ 39 MB** | ORT-Web; G2P runs dizione **inside Pyodide** (`web/public/worker.js` loads pyodide v0.26.4 + `ort.wasm.min.js`) | en only, 2 fixed voices (F2/M2), 24 kHz | No ("No streaming yet", README) | **0.019–0.03** steady, ORT CPU incl. phonemize (first run 0.33) | **0.00** on 2/2 clean sentences; digits/dates expand correctly ("$42.50"→"forty two dollars…", "March 3rd, 2024"→"March third…") | Apache-2.0 (code+weights); dataset CC-BY-4.0 | **dizione** (author's own, Apache-2.0, created 2026-11-14, data: CMUdict + homograph lists with license files in-repo) — **no espeak, no GPL** | Days old; 1 author; 56 likes; trained 7.7 h on 1×RTX 4090 ($9.56) | [tiny-voca.n4ze3m.com](https://tiny-voca.n4ze3m.com) (repo `web/`) |
| [mesm-tts](https://huggingface.co/mesmertech/mesm-tts) ⭐ new | 2026-11-05 (`createdAt`) | not published (~4–8M by weight size) | **Heart v2: v2f.pdn 3.53 MB raw / 2.95 brotli** (or v2g 2.34/1.95) + engine `pdn.wasm` 136 kB raw / **38 kB brotli** + misaki-lite frontend (us_gold+silver lex ~3.8 raw / **~1 brotli**, js ~33 kB) → **≈ 7.7 MB raw, ≈ 4 MB brotli-wire; NO onnxruntime needed** (10-voice pv set: `web/voices/*.pdn` ~5.3–5.8 each instead) | Custom **`.pdn` WASM engine** (SIMD128 + relaxed-SIMD builds, auto-picked), `paradee.mjs` API | en, 10 voices (pv) + Heart v2 (f/lite/g), 24 kHz | **Yes — true sample streaming**, `tts.stream()`, first chunk ~20–40 ms (README) | **0.028–0.035**, ORT CPU via `tts.py` on `onnx/voices/hadley.onnx` 5.34 MB | **0.00** on 2/2 clean sentences; s1 content words all correct per judge | **Apache-2.0** (+NOTICE crediting Kokoro/Paradee/Phonon/misaki); eSpeak fallback is **optional** and explicitly excluded from the license grant — shippable without it | misaki-lite (JS port of misaki, Apache) bundled; Python path uses `misaki==0.9.4` + `espeakng-loader` (droppable) | Days old; 1 author (mesmer.tools); published native-ORT benchmark protocol + per-sentence xRT JSON in `benchmarks/` | `web/demo.html` + `web/say.mjs` in repo; voice try-out linked from [announcement](https://artrealmai.com/article/mesm-tts-wasm-english-voices) |
| [Kitten TTS 2 Pico](https://huggingface.co/KittenML/kitten-tts-2-pico) ⭐ new | 2026-11-13 (`createdAt`) | 7.2M/lang | **en: onnx int8 7.95 + voices_en.npz 2.09 + g2p_bart 3.01 + cmu dict 3.42 + vocab** → **≈ 16.5 MB** + ORT-web ~2 | ORT-Web via [KittenTTS-web SDK](https://github.com/KittenML/KittenTTS-web) | 8 langs (en de es it pt ru hi fr), 30 voices, 24 kHz | Sentence-chunked: `generate_stream()` yields per-sentence audio | **0.10–0.15** steady, ORT CPU incl. frontend (first synthesis 21.5 s one-time G2P/spacy init) | 0.00–0.11 (the 0.11 is judge hearing "Kitten Pico" as "Ken Pico"; phonemes verified correct: `kˈɪtn pˈikO`) | Apache-2.0 | **misaki** (bundled BART G2P, Apache) for en; **espeak-ng for non-en** (frontend `phonemize_v2.py`: "misaki only where its output fits the vocab (en, ja, zh); espeak for every other language") — **non-English voices pull GPL phonemizer** | KittenML established (nano-0.1: 522 likes; mini-0.8: 165); loader PR #192, `kittenml` 0.9.8 | [webml-community/KittenTTS-web](https://huggingface.co/spaces/webml-community/KittenTTS-web) Space + [shreyask/KittenTTS-WebGPU](https://huggingface.co/spaces/shreyask/KittenTTS-WebGPU) |
| [Kitten TTS 2 Nano](https://huggingface.co/KittenML/kitten-tts-2-nano) ⭐ new | 2026-11-13 | 17M/lang | en onnx int8 **17.36** (+ same ~8.5 G2P/voices as Pico) → **≈ 26 MB** | Same as Pico | 8 langs | Sentence-chunked | not measured (same code path as Pico; expect ~Pico or slower) | not measured | Apache-2.0 | Same as Pico (espeak-ng for non-en) | Same org as Pico; 827 downloads in 2 days | Same SDK as Pico |
| [Kitten TTS 2 Mini](https://huggingface.co/KittenML/kitten-tts-2-mini) ⭐ new | 2026-11-13 | 82M | onnx int8 **82.71 alone** (+voices/G2P) → **over budget by itself** | Same as Pico | **16 langs incl. sv**, ja, zh…, 118 voices | Sentence-chunked | not measured | not measured | Apache-2.0 | Same as Pico | 1271 downloads in 2 days | Same SDK as Pico |
| [Paradee-8M v1.1](https://huggingface.co/sahilmahendrakar/Paradee-8M-v1.1) ⭐ new | 2026-10-15 | 7.88M | int8 onnx **8.46** (+misaki G2P) | ORT; Python pkg + training code on GitHub | en, 1 voice (af_heart) | No (utterance-level) | not measured (vendor: 62×RT, 16 ms/s on 1 CPU thread) | vendor: 5.9% vs Kokoro 5.7%; UTMOS 4.39 vs 4.52 | Apache-2.0 | **misaki** (Kokoro frontend, Apache) — no espeak | Paper [arXiv 2610.06817](https://huggingface.co/papers/2610.06817); 28 likes; mesm-tts is its browser-optimized descendant (measured instead) | [Nymbo/Paradee-TTS](https://huggingface.co/spaces/Nymbo/Paradee-TTS) Space |
| [Pocket TTS small](https://huggingface.co/kyutai/pocket-tts) (via [ken107/pocket-tts-onnx](https://huggingface.co/ken107/pocket-tts-onnx)) ⭐ new | Blog 2026-10-20; `english_*_2026-10` dirs modified 2026-10-21; ONNX export created **2026-10-25** | 18.2M / 6.9M / 2.3M | INT8 ONNX totals: **18m ≈ 48.4** (20.41+13.31+8.19+5.52+0.92) / **7m ≈ 31.7** / **2m ≈ 25.0** (+tokenizer ~0.3 + 1 speaker embedding ~3–5) → 2m/7m fit, 18m does not | ORT-Web (ken107 export, as used by pocket.ttstool.com) | English (small series; full Pocket TTS has 6 langs) | Yes (streaming-capable autoregressive) | not measured | not measured | **Weights CC-BY-4.0 + mandatory consent gate** ("forbids cloning anyone's voice without consent"); code MIT — attribution + gate OK for us, but terms are stricter than Apache | own tokenizer (no espeak) | Kyutai lab; pocket-tts 10k GitHub stars; 3 tech reports | [pocket.ttstool.com](https://pocket.ttstool.com/) (HTTP 200 verified 2026-11-15) |
| [sanoTTS](https://huggingface.co/ampixa/sanoTTS) (out-of-window baseline, updated in window) | Created 2026-07-13, `lastModified` 2026-11-14 | 0.29–2.27M | per-voice e.g. heartnano int8 **316 kB**, heart f32 8.1 MB + espeak-ng WASM 275 kB | Custom WASM; runs realtime on ESP32-S3 | **16 langs, 28–30 voices** | utterance-level (verify) | not measured | vendor: leads sub-15M class on SCOREQ/UTMOS | **GPL-3.0** ⚠️ copyleft — bundling into a proprietary app is a problem; keep at arm's length | **espeak-ng compiled to WASM** (the 275 kB port) | 814 GitHub stars, active; smallest neural TTS known | [ampixa.github.io/sanoTTS](https://ampixa.github.io/sanoTTS/) (live, 30 voices) |
| Piper voices (baseline) | 2023 (`rhasspy/piper-voices`) | ~15M (VITS) | ~60 MB/voice typical (verify per voice: 1× `.onnx` + `.onnx.json`) + espeak-ng data | `piper` binary / `piper-tts` (Python); no official browser build | 30+ langs incl. sv | sentence-chunked (streaming flag in server) | not measured | not measured | **Engine GPL-3.0** (embeds espeak-ng); voice MODEL_CARDs vary | **espeak-ng embedded** (GPL) | Home Assistant / OHF; huge voice catalog | No official in-browser demo found |
| Kokoro-82M (baseline) | 2024-12-26 | 82M | onnx q8f16 **86.03** / quantized 92.36 (+voices) → over budget | ORT / kokoro.js | en (+variants) | No | not measured | not measured | Apache-2.0 | misaki/espeak-based frontend (verify per integration) | 7428 likes; teacher of Paradee/mesm/phonon | kokoro.js web player (hexgrad) |
| Kitten TTS nano-0.8-int8 (baseline) | 2026-02-19 | ~15M | onnx int8 **24.37** + voices.npz 3.28 (+misaki) → ~30 MB | ORT-Web via KittenTTS-web | en, 8 voices | Sentence-chunked | not measured | not measured | Apache-2.0 | misaki (en) | 38 likes; superseded by Pico (smaller, multilingual) | Same KittenTTS-web Space |
| [Phonon-31m-en](https://huggingface.co/gradium/phonon-31m-en) (in-window but over budget — lead) | 2026-10-19 | 31M | safetensors **102.82** / q4k gguf 55.08 → over budget | `transformers` (torch); streaming tag; no ORT export in repo | en, built-in voice + phonon-voices | **Yes** (tagged streaming) | not measured | not measured | Apache-2.0 | own (builds on Pocket TTS + Mimi; no Mimi weights included) | 162 likes in 4 weeks; mesm-tts teacher | unknown |

## 2. STT candidates

"DL" = browser download. All measured on the same 5 LibriSpeech test-clean clips
(4–9 s, refs in `eval/stt/refs.txt`), normalized lowercase/no-punct WER.

| Model | Release (verified) | Params | DL per required file | Runtime path | Langs | Stream | Measured RTF | Measured WER | License | Maturity | Browser demo |
|---|---|---|---|---|---|---|---|---|---|---|---|
| [Whistle](https://huggingface.co/Cactus-Compute/whistle) ⭐ new | **2026-09-30** (`createdAt`; launched Oct 2) | not published (16.9 MB file) | **`whistle.cact` 16.92** + cactus engine artifact per platform (browser/WASM target shipped; engine size not yet verified — est. ~1–2 MB) | **Cactus C++ engine** (own beam-search decoder, no ORT/transformers); `pip install cactus-compute`, JS/WASM via platform folders in [Cactus-Compute/cactus](https://huggingface.co/Cactus-Compute/cactus) | **7 (en de fr es it nl pl)**, auto-detect; word timestamps + speech embeddings included | No true streaming: ≤30 s clips, windowed beyond; TTFT 11 ms (vendor, M4 Pro) | **0.08–0.26** CPU (cactus runtime; first run incl. download) | **1.2%** (1 word in 83: "Oz"→"oars") | Apache-2.0 | Weeks old; 573 likes, 90k downloads; vendor-benchmarked ahead of Whisper-base on Libri clean/other, SPGI, Earnings-22, FLEURS-avg (vendor-run, note bias) | Vendor references browser target + demo on [blog](https://cactuscompute.com/blog/whistle); `cactus whistle playground` CLI |
| [AuroraASR-1M](https://huggingface.co/AuroraAI-Research/AuroraASR-1M) ⭐ new | **2026-10-18** | **949K** (4 weight-shared Conformer-lite blocks, CTC, 256-BPE) | **int8 1.06** / fp32 3.81 (+bpe 0.24) | **torch + transformers custom code only — no ONNX/browser path exists**; int8 = stored-int8 dequantized on the fly (smaller, not faster) | en only, lowercase a-z output, no punct | No (greedy CTC over clip) | **0.003–0.06** torch CPU int8 (fastest measured here) | **2.4%** (2 words: "braids"→"bides", "all"→"up"); card: 11.43% test-clean / 26.5% test-other greedy | Apache-2.0 | Days-to-weeks old; 41 likes; LibriSpeech-960h-only training (narrow domain) | None |
| Moonshine tiny (baseline; streaming sibs Feb 2026, out of window) | 2024 (`UsefulSensors` IDs currently 404; use `onnx-community/moonshine-tiny-ONNX` Dec 2024, MIT) | 27M | Native quantized `.ort` set: encoder 13 + decoder 30 + tokenizer ≈ **43 MB**; ORT-Web path: encoder q4 10.73 + decoder q4 44.65 + tokenizer ≈ **55 MB+** | Native `moonshine-voice` lib, or Transformers.js (WebGPU) | en (+separate ja/ar/tiny-streaming variants) | **Yes** (streaming variants; non-streaming measured) | **0.05–0.08** CPU (native lib, non-streaming) | **1.2%** (1 artifact token "S." prefix) | **MIT** (repo LICENSE; onnx-community export tagged `license:mit`); ⚠️ non-English Moonshine models are under the non-commercial Community License | Established (paper, 1k+ ★ family); default `en` model in `moonshine-voice` is now medium-streaming (257 MB!) — **pin `ModelArch.TINY`** | `examples/web` in [repo](https://github.com/moonshine-ai/moonshine); Transformers.js WebGPU examples |
| Whisper tiny.en (baseline; onnx-community re-export touched 2026-11-10) | 2023 (openai); export updated 2026-11-10 | 39M | ORT-Web path: encoder q4 ~7 + **decoder q4 ~87** + tokenizer ≈ **95 MB → over budget**; whisper.cpp WASM similar class | Transformers.js (WebGPU) / whisper.cpp WASM | en | No (30 s padded windows) | 0.06–0.63 (proxy: faster-whisper int8 CPU; browser ORT-Web will differ) | **1.2%** ("exclaimed"→"exclaim") | Apache-2.0 (MIT for onnx-community export scaffolding) | The known quantity; 7.6k+ likes family-wide | [Transformers.js WebGPU guide](https://huggingface.co/docs/transformers.js/main/guides/webgpu) (official example) |
| Moonshine base (baseline, one line) | 2024 | 61M | ORT decoder q4 **85.09 alone** (+encoder) → far over budget | Same as tiny | en | variants | not measured | card: 4.58% test-clean (per Aurora card) | MIT | Established | Same as tiny |

Unverified STT leads (all in-window, none hands-on — §6): `corygong/stt_en_conformer_ctc_small`
(NeMo 53 MB, Nov 15), `mario-sieg/magnetron-whisper` (custom `.mag`, Nov 1),
`hencohen83/zipformer2-66m-streaming-en-qnn-sm8750` (Snapdragon NPU-only, Nov 15),
`Hebrish/Sabich-Rolling-sherpa-onnx-int8` (652 MB encoder — over budget anyway, Nov 2).
Proprietary and therefore excluded: WisprFlow Canto (Sep 17, 3.4% vendor WER), Qwen3-ASR
family (600 MB+ class).

## 3. VAD / end-of-turn

| Model | Release | DL | Runtime path | Measured | License | Notes / demo |
|---|---|---|---|---|---|---|
| [Silero VAD](https://github.com/snakers4/silero-vad) via `onnx-community/silero-vad` | 2020 (v4/v5 current) | **`model_int8.onnx` 639 kB** (fp32 2.24 MB) | ORT-Web; drop-in `<script>`/npm integration: [`@ricky0123/vad-web`](https://github.com/ricky0123/vad) | **RTF 0.012 CPU**, mean speech-prob 0.84–0.92 on the 5 Libri clips (512-sample windows @16 kHz) | onnx-community export tagged **`license:mit`**; repo is MIT — but old threads dispute weight terms, so confirm before commercial ship | The default; streaming (stateful, zero-lookahead windows); used by vad-web in browsers today |
| [TEN VAD](https://huggingface.co/TEN-framework/ten-vad) | 2025-05-14 (HF) | lib 306 kB–2.2 MB by platform; web `ten_vad.wasm` 283 kB + js | WASM/JS in `lib/Web`, C/C++/mobile SDKs; claims lower compute than Silero | not measured (vendor: RTF 0.0086–0.016 vs Silero 0.0127) | **Apache-2.0 WITH additional conditions** (commercial deployment terms — read LICENSE before shipping) | Candidate if Silero terms bother you and you accept TEN's conditions |
| [PulseVAD](https://github.com/AydinAdnan/PulseVAD) | 2026-09-01 (GitHub, MIT, 65 ★) | **26.8 kB** ONNX, 2,118 params, causal zero-lookahead | ORT-Web friendly | not measured (vendor: trails Silero on noisy audio/music) | MIT | Smallest; verify on real mic noise before trusting |

End-of-turn beyond energy gating (e.g. semantic holdover, backchannel suppression) is
application logic on top of VAD + partial STT — no new in-window model covers it; the
[Wispr/Canto-style](https://wisprflow.ai/canto) endpointing work is proprietary.

## 4. What fits in 50 MB (the shortlist, itemized)

**English default — ≈ 26–28 MB wire (brotli where published):**

| Part | Pick | Wire |
|---|---|---|
| STT | Whistle `whistle.cact` | **16.92** |
| STT runtime | cactus `wasm/cactus.wasm` 1.24 MB + `cactus.js` 0.06 MB (release 4.1.1, exposes `cactus_transcribe` and `cactus_stream_transcribe_*`; verified by lead 2026-11-15) | **1.30** raw |
| VAD | Silero `model_int8.onnx` | **0.64** |
| VAD glue | existing vad-web integration pattern | ~0 |
| TTS | mesm-tts Heart v2 (`v2f.pdn` brotli 2.95 + `pdn.wasm` brotli 0.04 + misaki-lite lex brotli ~0.99 + js ~0.01) | **~4.0** |
| TTS runtime | pdn engine is the runtime (no ORT) | 0 |
| ORT-Web shared | only needed if you keep an ORT model alongside | 0 in this combo |
| **Total** | | **≈ 22–24 + engine ≈ 26–28 MB** |

- Why this TTS: only candidate that is simultaneously tiny, streaming (20–40 ms
  first chunk), Apache-2.0 with no GPL phonemizer, and measured here at RTF 0.03 /
  WER 0.0. tiny-voca sounds as good but its Pyodide G2P (~10–12 MB) breaks the
  budget; Kitten Pico costs ~16.5 MB + ORT and isn't sample-streaming.
- Why this STT: only in-window STT that is multilingual, single-file, Apache-2.0,
  browser-targeted, and measured here (1.2% WER, RTF ≤ 0.26). AuroraASR-1M is 17×
  smaller but has no browser path and trains/evaluates on LibriSpeech only.
- Why this VAD: 639 kB, measured working, zero-lookahead stateful.

**Lead verification (2026-11-15):** HF API confirms Whistle (created 2026-09-30, Apache-2.0, 16.92 MB), mesm-tts (created 2026-11-05, Apache-2.0, `web/` runtime present) and Kitten TTS 2 Pico (created 2026-11-13, Apache-2.0, 7.95 MB per language). Caveats: mesm-tts has 0 likes and 91 downloads (single author, very new); the TTS numbers were measured on the `hadley` voice through Python ONNX Runtime, not on Heart v2 in the `.pdn` browser engine, so browser speed and quality are still unmeasured.

**Main risk (one line):** all three picks are weeks old and their headline numbers
are vendor-run — budget a day to re-run the Appendix eval on real tutor audio
before committing.

**Multilingual alternative — ≈ 26 MB + ~8 MB per extra TTS language:**
Whistle already covers de/fr/es/it/nl/pl; add one Kitten TTS 2 Pico model per
language (en pack ≈ 16.5 MB incl. shared G2P, each extra language ≈ 8 MB voice
ONNX + small voices file). Two languages ≈ 35 MB, three ≈ 43 MB — a fourth
language breaks the budget. Risk: Pico non-English quality is unreviewed and
non-English phonemization runs through **espeak-ng (GPL)** — quarantine or
replace that path before shipping.

**Swedish gap (stated plainly):** no small in-window Swedish model exists. Nearest:
`Phoonnx/vits-sv_se-lisa` (created **2026-11-14**, MIT-tagged, Piper-style VITS)
at **63.51 MB** — over budget alone and espeak-ng-dependent; or Kitten Mini's
Swedish voice (82.7 MB). Recommendation: ship English first, revisit Swedish
when a Pico-class `sv` model appears.

## 5. Unverified leads (do not rely on these)

- `corygong/stt_en_conformer_ctc_small` (created 2026-11-15, NeMo `.nemo` 53 MB):
  no browser/ORT path; unmeasured.
- `mario-sieg/magnetron-whisper` (2026-11-01, custom `.mag` 148 MB): new
  container format, no browser story; unmeasured.
- `hencohen83/zipformer2-66m-streaming-en-qnn-sm8750` (2026-11-15): Qualcomm NPU
  binaries — irrelevant to browser; listed so nobody re-finds it.
- `hukumvoice`, `quillforall` benchmark pages: vendor SEO, not models.
- `kokoro7mdistill` (r/TextToSpeech rumor, ~7.5M params / 28.7 MB): no source repo
  found; possibly confused with Paradee-8M.
- `shefowl/neutts-nano-polish` (Sep 2 — outside window): small non-English
  (pl); not assessed.
- Qwen3-ASR GGUF/INT4 quants (Oct–Nov): 600 MB–1.6 GB class; irrelevant to budget.
- `mesmertech/Breeze-TTS-2-int4-hqq-g64` (Sep 2): 3B-class weight-only int4;
  irrelevant to budget.
- WisprFlow Canto (Sep 17): proprietary, no weights; endpointing ideas only.

## Appendix — reproduce the hands-on results

Environment: `~/scratch/browser-voice-research/` (throwaway uv project; WAVs and
`eval/stt/refs.txt` kept there, not in this repo). CPU: generic x86-64 Linux box.
All "measured" numbers above come from these commands; first-run timings include
one-time model downloads.

```bash
cd ~/scratch/browser-voice-research
uv pip install onnxruntime soundfile librosa jiwer numpy huggingface_hub \
  faster-whisper datasets sentencepiece transformers cactus-compute
UV_INDEX_URL=https://download.pytorch.org/whl/cpu uv pip install torch
uv pip install "dizione @ git+https://github.com/n4ze3m/dizione" kittenml
uv pip install -r <mesm-tts-snapshot>/requirements.txt   # misaki==0.9.4, spacy, num2words, espeakng-loader, …
uv pip install moonshine-voice   # isolated env recommended (see below)

# TTS weights
hf download n4ze3m/tiny-voca --include 'onnx/model.onnx phonemizer/*'
hf download KittenML/kitten-tts-2-pico --include 'kitten_tts_2_pico_en.onnx voices_en.npz config.json vocab.json g2p/*'
# mesm-tts: clone https://huggingface.co/mesmertech/mesm-tts (needs onnx/voices/hadley.onnx + tts.py)

# TTS bench (scripts kept in the scratch dir: bench_tinyvoca.py; kitten/mesm one-liners in shell history)
DIZIONE_DATA=<snapshot>/phonemizer PYTHONPATH=tiny-voca-repo/src \
  python -m tiny_voca.infer --checkpoint <snapshot>/tiny-voca.pt --voice F2 --text "..." --output out.wav
python bench_tinyvoca.py                       # ORT session over onnx/model.onnx; prints RTF per sentence
python ${M}tts.py "Hello there..." --voice hadley --out mesm.wav   # M = mesm-tts snapshot
# kitten (isolated env: kitten-env/.venv has ../kitten-repo + soundfile):
kitten-env/.venv/bin/python -c "
from kittenml.kittentts2_tiny.model import KittenTTS2Tiny
m = KittenTTS2Tiny('KittenML/kitten-tts-2-pico', backend='onnx')
w = m.generate('Hello! …', voice='Eleanor')"   # time around generate() for RTF

# STT eval clips: 5 LibriSpeech test-clean utterances (1284-134647-0000, 1284-1181-0002…0005),
# extracted from https://www.openslr.org/resources/12/test-clean.tar.gz, resampled to 16 kHz (refs.txt).
CACTUS_TELEMETRY=0 python -c "import cactus; print(cactus.transcribe('eval/stt/<utt>_16k.wav'))"
moon-env/.venv/bin/python -c "                                   # moonshine-voice, ModelArch.TINY pinned
from moonshine_voice import Transcriber, load_wav_file, get_model_for_language
from moonshine_voice import moonshine_api
mp, ma = get_model_for_language('en', moonshine_api.ModelArch.TINY)
t = Transcriber(model_path=mp, model_arch=ma)"  # transcribe_without_streaming() per clip
# whisper tiny.en via faster-whisper int8 (av pinned/worked around; decode via librosa, beam_size=1)
# AuroraASR-1M int8: AutoModelForCTC.from_pretrained('AuroraAI-Research/AuroraASR-1M',
#   subfolder='int8', trust_remote_code=True).transcribe(wav)  (needs torch, transformers, sentencepiece)
# Silero VAD int8 (onnx-community/silero-vad onnx/model_int8.onnx): 512-sample windows,
#   inputs {'input':[1,512], 'state':zeros(2,1,128), 'sr':16000}; mean prob + frac>0.5 per clip.

# WER: wer_stt.py (STT hyps inline, normalized lower/strip-punct) and the TTS-judge block
# (faster-whisper tiny.en int8 transcribes tinyvoca_f2_s*.wav, kittenpico_s*.wav, mesm_s*.wav).
```

STT hypotheses used for the WER table (5 clips, order 1284-134647-0000,
1284-1181-0002/3/4/5): Whistle 1 sub ("oars"); Moonshine-tiny 1 prefix artifact;
Whisper-tiny.en 1 sub ("exclaim"); Aurora-1M 1 sub + 1 insertion — corpus WER
1.2% / 1.2% / 1.2% / 2.4% on n=5 (indicative, not a benchmark).

Sentences synthesized for TTS (s0 hello/"clearly for you" with the voice's name,
s1 names+digits+date+money, s2 weather): see `wer_all.py` refs in scratch dir;
judge = faster-whisper `tiny.en` int8; "Ken Pico" is a judge artifact (phonemes
verified `kˈɪtn pˈikO`), s1 deltas are judge number-formatting, not misreads.
