# Licences of what is in this bundle

| files | origin | licence |
|---|---|---|
| `engine/` (pdn), `paradee.mjs`, `paradee-worker.mjs`, `player*.js`, `frontend/misaki_lite.mjs`, `frontend/espeak_chain.mjs`, `frontend/tokenizer.mjs`, `check.mjs`, `example.html`, `integrations/` | this project | Apache-2.0 (as this repository) |
| `models/*.pdn` | Heart v2f / v2f_lite / v2g weights, re-encoded losslessly from the release ONNX files | Apache-2.0 (as this repository) |
| `frontend/tokenizer.json` | the release's `tokenizer.json`, unchanged | Apache-2.0 |
| `frontend/misaki.js` | Paradee repository, `web/misaki.js` (misaki's eSpeak-to-misaki table) | Apache-2.0 |
| `frontend/us_gold.fc.txt`, `frontend/us_silver.fc.txt`, `frontend/lex/` | misaki 0.9.4 (github.com/hexgrad/misaki) `us_gold.json` / `us_silver.json`, same entries, re-encoded (front-coded text; `lex/`: split into shards) | Apache-2.0 |
| `frontend/misaki_lite.mjs` | a JavaScript port of misaki's `en.py` G2P logic | Apache-2.0 (as misaki) |
| `frontend/kokoro-phonemize.mjs` | kokoro.js `src/phonemize.js` (github.com/hexgrad/kokoro), unmodified | Apache-2.0 |

**Not included: eSpeak NG.** The fallback for words the lexicon cannot resolve loads eSpeak NG through the `phonemizer` npm
package (the one kokoro-js depends on and Chickadee already ships). That package is published as Apache-2.0 but contains eSpeak NG
compiled to WebAssembly, and eSpeak NG itself is GPL-3.0-or-later: whoever ships the fallback should review that. Without it,
misaki-lite still works for every word in its lexicon (96.5% of DEV words); unknown words then raise an error from `phonemize`.
