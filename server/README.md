# Open Tutor backend

Two processes, both in this package:

- **Web service** (`open_tutor.web`, FastAPI): serves the built page from `web/dist`, and `POST /api/session` returns a short-lived LiveKit room token. The learner's name, school year and newest notes travel in the token's participant metadata. Nothing is stored on the server.
- **Tutor worker** (`open_tutor.agent`, LiveKit Agents): joins each room as `open-tutor`, runs Soniox speech recognition, the tutor model and the voice, and drives the board through the protocol in [docs/protocol.md](../docs/protocol.md).

The web service also serves original material sections read-only, rendered from the pinned Siyavula EPUBs (steps 3a/3b in [the material-library state](../docs/material-library/STATE.md)):

- `GET /api/materials/sections/{id}` — visible text, image list, completeness, book/source/license metadata for the tutor.
- `GET /materials/sections/{id}/index.html` — the original section page, embeddable as `<iframe sandbox="">`.
- `GET /materials/sections/{id}/{asset}` — only the section's own packaged images and CSS.

Packages are built lazily per section under `$XDG_CACHE_HOME/open-tutor/material-packages` and published atomically. A host without the EPUBs answers 503 on these routes and is otherwise unchanged.

## Run locally

```bash
cd server
uv sync --python 3.12
bin/with-env uv run python -m open_tutor.agent dev          # worker
bin/with-env uv run uvicorn open_tutor.web:app --port 8710   # web service
cd ../web && npm install && npm run dev                      # page on http://localhost:5173
```

`bin/with-env` loads `~/.config/open-tutor/env` (mode 600, never committed) as defaults (a variable already set in the environment wins) and, if that file names an Infisical project in `OPEN_TUTOR_INFISICAL_PROJECT`, injects provider keys from it. Other hosts can put every variable in the env file instead.

## The OpenCode Go route

Go serves Muse Spark 1.3 Contributor only on its OpenAI Responses endpoint, `https://opencode.ai/inference/go/openai/v1/responses`. Tested 2026-11-04 with fictional material:

- HTTP streaming works. The Responses WebSocket that LiveKit's plugin uses by default answers 404, so the worker uses HTTP (`use_websocket=False`).
- Function calls arrive as structured `function_call` items with complete JSON arguments. Spoken text arrives separately as `output_text`. Tool results are sent back as `function_call_output` in the full context (`store=false`, no `previous_response_id`).
- Image input (`input_image`, data URL) is read correctly.
- Go's usage block has no `cache_write_tokens`; LiveKit 1.8.10 failed every turn on that, so `tutor_llm.py` fills in 0.
- Requests name the app (`User-Agent: open-tutor/…`) and send the room name as `x-opencode-session`, as Go asks of clients.
- Reasoning `minimal`: board tool called in 24 of 24 first requests, median 1.4 s to first output (`low`: 4.2 s median, up to 11.6 s).
- Go's documentation says Muse Spark Contributor prompts and completions are used to train Meta models (not zero data retention), and the workspace must allow paid endpoints that train on request data.

## The voice route

Production uses Deepgram Swedish speech with `TUTOR_TTS=deepgram`, `TUTOR_TTS_MODEL=flux-ludvig-sv`, and `TUTOR_TTS_EXPRESSIVITY=1`. The backend loads `DEEPGRAM_API_KEY` from Infisical. A narrow adapter adds expressivity to LiveKit's TTSv2 requests. Cartesia remains selectable, but production no longer depends on its credits.

ElevenLabs **Eleven v4 Turbo** (`eleven_v4_turbo`, released September 2026), voice **Bella - Professional, Bright, Warm** (`hpp4J3VqNfWAUOO0d1Us`, an ElevenLabs premade voice), Swedish (`language_code=sv`). ElevenLabs recommends v4 Turbo for real-time conversation and `eleven_v4` for produced narration.

v4 is served only through text-to-dialogue. `open_tutor/dialogue_tts.py` speaks the documented single-context socket `wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input`: one registered voice, one socket per reply, each sentence sent and flushed, `keep_alive` while the reply waits for text, `close_socket` at the end. Output is `pcm_24000` with `sync_alignment=true`, so captions follow the audio word by word. An interruption cancels the stream and closes its socket, so an interrupted reply stops at once.

LiveKit's ElevenLabs plugin (1.8.10, the newest release on 2026-11-04) sends v4 to `text-to-dialogue/multi-stream-input` instead. ElevenLabs documents that endpoint as v3-only. It still answered for v4 Turbo in a probe, but the worker does not depend on undocumented behaviour. The plugin is still used for earlier models (`TUTOR_TTS_MODEL=eleven_flash_v2_5` is the rollback).

Checked against the real API on 2026-11-04 with fictional Swedish text:

- The account (Starter tier) lists `eleven_v4` and `eleven_v4_turbo`, both with Swedish. v4 Turbo costs 0.5 credits per character, the same as Flash v2.5. `eleven_v4` costs 1.0.
- Bella works on v4 Turbo. The voice's metadata lists only older models as verified, but the account history records the generations as `eleven_v4_turbo`.
- Connecting the socket takes about 90 ms. In the worker, first audio arrived 88–104 ms after the first sentence was sent.
- Alignment times restart at 0 in every message. Within one flushed sentence they add up to that sentence's audio, which the caption clock follows.
- An unknown voice returns `{"error": "voice_not_found", "code": 1008, ...}` and closes the socket. The worker reports it and does not retry.

The worker logs the route at the start of each session (`tutor TTS route elevenlabs /text-to-dialogue/stream-input model eleven_v4_turbo voice … lang sv`). It also logs the time to first audio of each reply, never the text.

## Configuration

| Variable | Purpose |
|---|---|
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | LiveKit Cloud project (required) |
| `SONIOX_API_KEY` | Speech recognition, Swedish hint |
| `TUTOR_TTS` | `elevenlabs` (default) or `cartesia` |
| `TUTOR_TTS_VOICE`, `TUTOR_TTS_MODEL` | Voice id and model for that provider. ElevenLabs default: `eleven_v4_turbo` with Bella (`hpp4J3VqNfWAUOO0d1Us`), see [the voice route](#the-voice-route). `eleven_v3*`/`eleven_v4*` models use the text-to-dialogue adapter; earlier models such as `eleven_flash_v2_5` use LiveKit's plugin |
| `ELEVENLABS_API_KEY` / `CARTESIA_API_KEY` | Voice provider key |
| `TUTOR_LLM` | `go` (default): Muse Spark 1.3 Contributor (`muse-spark-1.3-contributor`) on OpenCode Go, Responses API over HTTP streaming, `OPENCODE_GO_API_KEY`. `gemini-dev` only reproduces the board/voice bug of the earlier development route (`GEMINI_API_KEY`); do not deploy it. There is no silent fallback. |
| `OPENCODE_GO_API_KEY` | OpenCode Go API key (from the OpenCode console). Backend only |
| `TUTOR_LLM_MODEL`, `TUTOR_LLM_BASE_URL`, `TUTOR_LLM_REASONING` | Override the route's model, endpoint or reasoning effort (Go default `minimal`) |
| `TUTOR_AGENT_NAME` | Dispatch name, default `open-tutor`. Give a test worker and its web service another name so it never takes a family session |
| `EXA_API_KEY` | Resource search |
| `TUTOR_ACCESS_CODE` | Optional family code. When set, the page asks for it once per browser |
| `TUTOR_ALLOWED_COUNTRIES` | Optional comma-separated Cloudflare country codes, e.g. `SE`. Missing/disallowed country headers get 403; `/api/health` remains accessible |
| `TUTOR_MAX_SESSIONS_PER_HOUR` | Owner spending cap across the instance (default 12) |
| `TUTOR_MATERIAL_CACHE` | Directory for rendered original-section packages (default `$XDG_CACHE_HOME/open-tutor/material-packages`, never in the repo) |
| `TUTOR_MATERIAL_INDEX` | Directory of a saved EmbeddingGemma 2 index that the tutor's `search_materials` tool searches (needs the optional `ml` group). Unset: the tool answers "unavailable" and nothing else changes. There is no default or fallback index |
| `TUTOR_MATERIALS_DIR`, `TUTOR_MATERIALS_BOOKS` | Override the downloaded Siyavula EPUB directory and its `books.json`. Without the EPUBs the material routes answer 503; nothing else changes |
| `TUTOR_CLOUD_RECORDING` | `1` uploads session audio and transcripts to LiveKit Cloud observability. Off by default |
| `TUTOR_DEBUG_LOG` | `1` writes a per-session debug trail to a private local directory (see below). Off by default |
| `TUTOR_DEBUG_LOG_DIR` | Override the debug trail directory (default `~/.local/state/open-tutor/sessions`) |
| `TUTOR_STT_MAX_ENDPOINT_MS`, `TUTOR_MIN_ENDPOINT` | Turn-taking tuning for pauses while a child thinks |

### Password-free Sweden testing

For the hosted demo, `TUTOR_ALLOWED_COUNTRIES=SE` and an empty `TUTOR_ACCESS_CODE`
allow Swedish visitors without a password. Country checks cover the page, assets
and session creation. The session-start cap still applies. IP geolocation is
approximate and VPNs affect it.

This restriction trusts Cloudflare's `CF-IPCountry` header. Enable Cloudflare IP
Geolocation and keep the origin private behind its tunnel; a publicly reachable
origin would allow clients to forge that header. The current origin binds to
ThinkCentre's tailnet address, with public requests arriving through the Mini's
Cloudflare tunnel. Health checks are exempt to preserve local monitoring.

## Family-testing debug trail

During authorised family testing, `TUTOR_DEBUG_LOG=1` in the worker environment
writes one private directory per session (`TUTOR_DEBUG_LOG_DIR`, default
`~/.local/state/open-tutor/sessions`, directories 0700, files 0600, outside
git). Each session appends timestamped events to `events.jsonl` as they happen
(wall-clock UTC plus seconds since session start, flushed at once so crashes
leave evidence) and writes `report.json` on shutdown with a header, a summary
and the full timeline.

Captured: learner name/grade (to tell siblings apart), both sides of the
conversation, tool calls with arguments and results (including board content
and notes), homework descriptions (image sizes only; pasted text is kept),
lifecycle and close/disconnect reasons, mode and board acknowledgements,
interrupts, healed malformed tool arguments, speech-state changes, and usage
metrics. Not captured: credentials, keys, tokens, the whole environment, or
audio (LiveKit Cloud recording keeps that when `TUTOR_CLOUD_RECORDING=1`). The
config snapshot is an explicit allowlist. The normal log stream stays free of
session content either way.

Review the most recent sessions where the worker runs:

```bash
bin/with-env uv run python scripts/debug_sessions.py --list
bin/with-env uv run python scripts/debug_sessions.py --last --learner kian
bin/with-env uv run python scripts/debug_sessions.py --show tutor-XXXX
```

Default off, so open-source adopters get no behaviour or file change.

## Teaching boards

- `commission_board` makes a new board for a new topic: placeholder first, then the
  finished drawing at the same new id. A LiveKit progress update releases the
  voice turn immediately, so the tutor can keep helping while drawing runs.
  The finished result arrives automatically with the board id and screenshot.
- `edit_board` sends the saved HTML and the requested change back to the renderer.
  It updates the same board id, using an explicit id or the most recent board when
  omitted. The renderer is instructed to preserve unrelated content and controls.
  Failed edits restore the saved source. The tutor receives confirmation only when
  the browser acknowledges that restoration. Only one drawing or edit runs per
  session; overlapping calls are refused immediately. A later edit uses the latest
  successful source. Boards live only in the session.
  Input values changed inside the sandbox are not currently saved with that source.
- Board engine defaults: `BOARD_MODEL=opencode-go/muse-spark-1.3-contributor`,
  `BOARD_THINKING=minimal`. Environment overrides still apply. `BOARD_MAX_TOKENS=16384`
  caps the provider's output-token limit for board requests only: `board_model.py`
  loads `open_tutor/board_budget.js` explicitly (`--extension` still applies with
  `--no-extensions`), and the extension clamps an existing `max_tokens` /
  `max_completion_tokens` down to the cap while keeping a lower configured limit.
  Replies cut off before `</html>` are rejected. A complete HTML document is kept
  if only its trailing tutor note hits the token cap. Timed-out or cancelled
  processes are killed and reaped. The renderer prompt is adapted from the
  `gym/prompts/r13/system.md` on the `gym/board-renderer` branch, used by the r21
  configuration. Production requests a short tutor note and has no automatic review pass.
- Dimension handshake: `board.show`/`board.update` acks return
  `{ok:true, board:{w,h,device}}` once the pane has settled; the worker uses those
  dims for the frozen design box. Plain `{ok:true}` peers still work.

## Material search proof

`open_tutor/materials/search.py` builds an exact cosine index from passage records and
`scripts/search_materials.py` drives it. This is the bounded EmbeddingGemma 2 proof, not a
production feature: evidence, sample definition, per-query IDs and limitations are in
[docs/material-library/step2b-embedding-proof.md](../docs/material-library/step2b-embedding-proof.md).

The model and index are an optional dependency group and never part of the server runtime:

```bash
uv sync --group ml --python 3.13                 # sentence-transformers, torch, torchvision (CPU)
bin/with-env uv run --no-sync python scripts/search_materials.py prove
bin/with-env uv run --no-sync python scripts/search_materials.py query --query "how do plants make food?"
```

Weights stay in the Hugging Face cache and the index in
`~/.local/share/open-tutor/materials/embeddinggemma-2-index`. Only owned passage text plus heading
and breadcrumb context is embedded; passage HTML spans are never model input, empty passages are
skipped, and hits carry `text_complete: false` when the original content is partly images.

## Tests

```bash
uv run pytest -q
```

`scripts/two_session_probe.py` runs two consecutive typed sessions for one fictional learner against a running worker. The first session's saved note goes into the second, as in the browser. It checks that board items arrive and are acknowledged in both, and that no tool name, arguments or JSON reach the captions (the text the voice speaks).

`scripts/live_probe.py` runs a real session against a running worker with a scripted fictional learner: recorded Swedish clips, a generated worksheet, an interruption, 30 s of quiet work, mumbling, and the end of the session. It writes a JSON timeline and the tutor's audio. It uses live providers and costs a little; it is not part of CI.

Run this prototype material server with `uvicorn open_tutor.web:app --workers 1`. Material packages are built lazily; concurrent publishers adopt a valid existing package rather than replacing it.
