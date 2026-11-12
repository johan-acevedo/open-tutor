# Open Tutor backend

Two processes, both in this package:

- **Web service** (`open_tutor.web`, FastAPI): serves the built page from `web/dist`, and `POST /api/session` returns a short-lived LiveKit room token. The learner's name, school year and newest notes travel in the token's participant metadata. Nothing is stored on the server.
- **Tutor worker** (`open_tutor.agent`, LiveKit Agents): joins each room as `open-tutor`, runs Soniox speech recognition, the tutor model and the voice, and drives the board through the protocol in [docs/protocol.md](../docs/protocol.md).

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

The Screen development fox uses Muse Spark 1.3 Contributor through OpenCode Go: `TUTOR_LLM=go` and `TUTOR_LLM_MODEL=muse-spark-1.3-contributor`. It uses the Responses API with the existing `OPENCODE_GO_API_KEY` and default `minimal` reasoning. The legacy `gemini-dev` override was removed from the running development configuration on 2026-11-12.

The Screen development instance uses ZONOS3-Mini on pc2014 with the Swedish embedding voice:

```sh
TUTOR_TTS=zonos
TUTOR_TTS_BASE_URL=https://pc2014.tail2e1c4e.ts.net:8448
TUTOR_TTS_VOICE=default_6c74e01948232c55
```

`open_tutor/zonos_tts.py` posts complete sentences to `/v2/generate` with explicit embedding mode and decodes the returned WAV into 44.1 kHz mono PCM. LiveKit's standard sentence adapter connects it to streamed LLM text and handles playback cancellation. Each sentence waits for HTTP synthesis before playback; this endpoint does not stream generated audio. It requires no paid-provider API key. The direct provider probe and a real browser fox session both produced audio on 2026-11-12.

Deepgram Flux remains selectable with these settings:

```sh
TUTOR_TTS=deepgram
TUTOR_TTS_MODEL=flux-ludvig-sv
TUTOR_TTS_EXPRESSIVITY=1
```

`DEEPGRAM_API_KEY` comes from the existing Infisical `homelab` project. The key stays on the server. The route streams linear16 PCM through LiveKit's `TTSv2` at `/v2/speak`. A small adapter adds `expressivity` to the streaming and batch query parameters because plugin 1.8.10 does not expose that control. See the [Deepgram voice catalog](https://developers.deepgram.com/docs/flux-tts/voices) and [voice control reference](https://developers.deepgram.com/reference/speak/v-2/audio/generate).

The default provider remains selectable as before:

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

## Adaptive interruption handling

Set `TUTOR_ADAPTIVE_INTERRUPTION=1` to let LiveKit classify overlapping speech before stopping the tutor. The default remains VAD-based interruption detection. This setting keeps the existing STT, LLM, TTS, and endpointing delays.

The classifier uses LiveKit Inference with the project's existing `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET`. Self-hosted workers receive a monthly development allowance. If the allowance runs out or inference fails, the SDK falls back to VAD-based interruption detection. See [LiveKit's allowance and fallback rules](https://docs.livekit.io/deploy/admin/quotas-and-limits/#adaptive-interruption-handling).

The Screen development worker enables this setting. Set it to `0` and restart the worker to return to VAD-only handling.

## Local speech for pre-rendering

VoxCPM2 is available over the tailnet at <https://johan-4070.tail2e1c4e.ts.net:8447>. It provides an unmetered HTTP synthesis endpoint. The app does not call it automatically; ZONOS3 on pc2014 is the development fox's live voice path. A LiveKit adapter is still needed to use VoxCPM2 for live sessions.

Use `warm-voice-v2` explicitly for Räven. Its anchor supports Swedish and English. `warm-voice-v1` is English, and `warm-voice-v3` is a clone anchor. The health response currently reports `warm-voice-v1` as the default.

| Request | Response |
|---|---|
| `GET /health` | Model, device, available voices, sample rate, and `busy` |
| `POST /tts` with JSON `{ "text": "…", "voice": "warm-voice-v2" }` | Raw signed 16-bit little-endian PCM, 48 kHz mono. `Content-Type: audio/pcm`; sample rate in `X-Sample-Rate` |

The operator's interface contract limits text to 2000 characters. Only one synthesis can run at a time. A concurrent request receives HTTP 409 and must wait before retrying.

To generate and convert a short sample:

```sh
curl --fail-with-body --silent --show-error \
  -H 'Content-Type: application/json' \
  --data '{"text":"Hej! Jag heter Räven.","voice":"warm-voice-v2"}' \
  https://johan-4070.tail2e1c4e.ts.net:8447/tts -o raven.pcm
ffmpeg -f s16le -ar 48000 -ac 1 -i raven.pcm raven.wav
```

Check the HTTP status before treating the response as audio. The PCM response has no WAV header.

The operator reports about 8.9 GB of GPU memory held on johan-4070. Check `nvidia-smi` before heavy GPU work, and do not run heavy ComfyUI renders alongside this service. To release the GPU:

```sh
ssh johan-4070 'systemctl --user stop voxcpm-tts'
```

Operator handoff: 2026-11-12, `scripts/serve_voxcpm.py` and `voxcpm-tts.service`. Boot startup and persistent Tailscale serving were confirmed by the operator. A read-only check from dell5500 on the same date returned `status: ok`, model `VoxCPM2`, device `cuda:0`, all three voices, 48000 Hz, and `busy: false`. No synthesis or GPU workload was started for that check. Recheck Swedish years and numbers by ear before using generated clips.

### ZONOS3-Mini alternative

ZONOS3-Mini has two interchangeable CPU endpoints:

| Host | Base URL |
|---|---|
| johan-4070 | <https://johan-4070.tail2e1c4e.ts.net:8448> |
| pc2014 | <https://pc2014.tail2e1c4e.ts.net:8448> |

Both expose the same API and speaker ids. Change only `TUTOR_TTS_BASE_URL` to use the other host. The johan-4070 instance proxies port 1919. The development fox selects pc2014 through the ZONOS3 LiveKit adapter. Automatic provider failover is not implemented.

`GET /v2/speakers` was checked on both endpoints from dell5500 on 2026-11-12 and returned these embedding voices:

| Label | Speaker id | Operator-described anchor |
|---|---|---|
| `raeven sv` | `default_6c74e01948232c55` | Swedish and English |
| `warm en` | `default_138a887d96716b8a` | English |

Always supply a voice and `speaker_mode: "embedding"`. The operator reports that omitting the voice produces silence. Omitting embedding mode selects reference mode and returns HTTP 400 because the reference encoder weights are not installed. The examples use the canonical id returned by speaker discovery; the operator also reports the shortcut `raeven-sv`.

Native request:

```sh
curl --fail-with-body --silent --show-error \
  -H 'Content-Type: application/json' \
  --data '{"text":"Hej! Jag heter Räven.","speaker_embedding_id":"default_6c74e01948232c55","speaker_mode":"embedding","stream":false,"format":"wav"}' \
  https://johan-4070.tail2e1c4e.ts.net:8448/v2/generate -o raven-zonos.wav
```

The OpenAI-compatible `/v1/audio/speech` endpoint accepts `model: "zonos3"`, `input`, `voice` set to the same speaker id, `speaker_mode: "embedding"`, and `response_format: "wav"`. Both return 16-bit WAV at 44.1 kHz according to the operator's contract. This differs from VoxCPM2's headerless 48 kHz PCM.

On johan-4070, keep the managed ZONOS3 service on its CPU backend, batch 8. The operator verified correct Swedish output there and broken audio with this ggml CUDA build on the 4070 Ti SUPER. CPU operation adds no VRAM use and can coexist with VoxCPM2. The existing restriction on heavy ComfyUI renders still applies because VoxCPM2 remains GPU-resident.

The pc2014 instance also uses the CPU backend. The operator reports about 1.8 GB resident RAM, no VRAM use, and 1.2 GB of models on disk, with `zonos3-tts.service` enabled at boot and persistent Tailscale serving. Logs: `ssh pc2014 'journalctl --user -u zonos3-tts'`. A Vulkan build for its RX 6500 XT is in progress; GPU operation remains pending operator validation.

Service: `zonos3-tts.service`, enabled at boot. Source/build: `~/zonos3` on johan-4070; voice embeddings: `~/zonos3/voices`. Logs: `ssh johan-4070 'journalctl --user -u zonos3-tts'`. The same endpoint serves the Studio UI. The operator reports optional delivery steering through `steer.gguf` and `/v2/controls`. No backend rebuild, synthesis, or listening check was performed when recording this handoff.

## Configuration

| Variable | Purpose |
|---|---|
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | LiveKit Cloud project (required) |
| `SONIOX_API_KEY` | Speech recognition, Swedish hint |
| `TUTOR_TTS` | `elevenlabs` (default), `cartesia`, `deepgram`, or `zonos` |
| `TUTOR_TTS_BASE_URL` | ZONOS3 base URL, default `https://pc2014.tail2e1c4e.ts.net:8448` |
| `TUTOR_TTS_EXPRESSIVITY` | Deepgram expressive range, integer `-2` to `2`, default `1` |
| `TUTOR_TTS_VOICE`, `TUTOR_TTS_MODEL` | Voice id and model for that provider. ElevenLabs default: `eleven_v4_turbo` with Bella (`hpp4J3VqNfWAUOO0d1Us`), see [the voice route](#the-voice-route). `eleven_v3*`/`eleven_v4*` models use the text-to-dialogue adapter; earlier models such as `eleven_flash_v2_5` use LiveKit's plugin |
| `ELEVENLABS_API_KEY` / `CARTESIA_API_KEY` / `DEEPGRAM_API_KEY` | Selected voice provider key |
| `TUTOR_LLM` | `go` (default): Muse Spark 1.3 Contributor (`muse-spark-1.3-contributor`) on OpenCode Go, Responses API over HTTP streaming, `OPENCODE_GO_API_KEY`. `gemini-dev` only reproduces the board/voice bug of the earlier development route (`GEMINI_API_KEY`); do not deploy it. There is no silent fallback. |
| `OPENCODE_GO_API_KEY` | OpenCode Go API key (from the OpenCode console). Backend only |
| `TUTOR_LLM_MODEL`, `TUTOR_LLM_BASE_URL`, `TUTOR_LLM_REASONING` | Override the route's model, endpoint or reasoning effort (Go default `minimal`) |
| `TUTOR_AGENT_NAME` | Dispatch name, default `open-tutor`. Give a test worker and its web service another name so it never takes a family session |
| `EXA_API_KEY` | Resource search |
| `TUTOR_ACCESS_CODE` | Optional family code. When set, the page asks for it once per browser |
| `TUTOR_ALLOWED_COUNTRIES` | Optional comma-separated Cloudflare country codes, e.g. `SE`. Missing/disallowed country headers get 403; `/api/health` remains accessible |
| `TUTOR_MAX_SESSIONS_PER_HOUR` | Owner spending cap across the instance (default 12) |
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
  finished drawing at the same new id. The tool result names the board id.
- `edit_board` sends the saved HTML and the requested change back to the renderer.
  It updates the same board id, using an explicit id or the most recent board when
  omitted. The renderer is instructed to preserve unrelated content and controls.
  Failed edits restore the saved source. The tutor receives confirmation only when
  the browser acknowledges that restoration. Concurrent edits to one board run in
  order, each using the latest successful source. Boards live only in the session.
  Input values changed inside the sandbox are not currently saved with that source.
- Board engine defaults: `BOARD_MODEL=opencode-go/deepseek-v4.1-flash`,
  `BOARD_THINKING=low` (env overrides stay; the installed Pi maps `off` to `low`
  for this model, so the default names `low` explicitly). `BOARD_MAX_TOKENS=16384`
  caps the provider's output-token limit for board requests only: `board_model.py`
  loads `open_tutor/board_budget.js` explicitly (`--extension` still applies with
  `--no-extensions`), and the extension clamps an existing `max_tokens` /
  `max_completion_tokens` down to the cap while keeping a lower configured limit.
  Length-truncated replies are rejected, and timed-out or cancelled processes are
  killed and reaped. The renderer prompt is adapted from the
  `gym/prompts/r13/system.md` on the `gym/board-renderer` branch, used by the r21
  configuration. Production requests a short tutor note and has no automatic review pass.
- Dimension handshake: `board.show`/`board.update` acks return
  `{ok:true, board:{w,h,device}}` once the pane has settled; the worker uses those
  dims for the frozen design box. Plain `{ok:true}` peers still work.

## Tests

```bash
uv run pytest -q
```

`scripts/two_session_probe.py` runs two consecutive typed sessions for one fictional learner against a running worker. The first session's saved note goes into the second, as in the browser. It checks that board items arrive and are acknowledged in both, and that no tool name, arguments or JSON reach the captions (the text the voice speaks).

`scripts/live_probe.py` runs a real session against a running worker with a scripted fictional learner: recorded Swedish clips, a generated worksheet, an interruption, 30 s of quiet work, mumbling, and the end of the session. It writes a JSON timeline and the tutor's audio. It uses live providers and costs a little; it is not part of CI.
