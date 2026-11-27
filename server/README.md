# Open Tutor backend

Two processes, both in this package:

- **Web service** (`open_tutor.web`, FastAPI): serves the built page from `web/dist`, and `POST /api/session` returns a short-lived LiveKit room token. The learner's name, school year and newest notes travel in the token's participant metadata. Nothing is stored on the server.
- **Tutor worker** (`open_tutor.agent`, LiveKit Agents): joins each room as `open-tutor`, runs Soniox speech recognition, the tutor model and the voice, and drives the Smart Screen through the protocol in [docs/protocol.md](../docs/protocol.md).
  The Smart Screen is the only screen mode (2026-11-18): the legacy card board and its
  `TUTOR_SCREEN` switch are gone. A leftover `TUTOR_SCREEN=smart` is accepted silently; any
  other value is ignored with one warning at session start.

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

## The Gemini route

`TUTOR_LLM=gemini` runs Gemini 4 Hydrogen (`gemini-4-hydrogen`, released 2026-11-12) on
Google's OpenAI-compatible Chat Completions endpoint with `GEMINI_API_KEY`. Hydrogen
rejects `minimal` and `thinking_budget` with a 400; its thinking levels are `low`,
`medium`, `high` (default) and `xhigh`, sent as `reasoning_effort` on this endpoint.
The route uses `low`: median 2.0-2.8 s to first token with the real prompt and tools
(three e2e runs, 2026-11-13).

Gemini 4 enforces thought signatures on replayed function calls. Its compatible stream
puts `index: null` on every function call, while LiveKit's chat stream assembler uses a
changed index to tell parallel calls apart. A reply calling two tools therefore kept only
the last (unsigned) call, and the next request failed with `400 Function call is missing
a thought_signature`. `tutor_llm.GeminiChatLLM` numbers the calls by id, so every call
and the signature on the first one survive; pinned by
tests/test_gemini_route.py against a recorded stream. The native Google plugin was not
needed.

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
| `TUTOR_TTS` | `elevenlabs` (default), `google`, `deepgram`, or `cartesia` |
| `TUTOR_TTS_VOICE`, `TUTOR_TTS_MODEL` | Voice id and model for that provider. ElevenLabs default: `eleven_v4_turbo` with Bella (`hpp4J3VqNfWAUOO0d1Us`), see [the voice route](#the-voice-route). Google default: `sv-SE-Chirp3-HD-Aoede` (`language="sv-SE"`, gRPC streaming via `livekit-plugins-google`). `eleven_v3*`/`eleven_v4*` models use the text-to-dialogue adapter; earlier models such as `eleven_flash_v2_5` use LiveKit's plugin |
| `TUTOR_TTS_FALLBACK` | Optional automatic fallback TTS provider (`google`, `deepgram`, `elevenlabs`, or `cartesia`; empty = none). Session-sticky on failure, with a shared file-backed cooldown across LiveKit job processes on quota/auth errors (`401`/`402`/`429`/`quota_exceeded`) so later calls start directly on the fallback without paying a failed handshake. Preserves Bella's word-synced captions while primary is healthy. Missing or invalid fallback credentials log a fixed warning and serve primary alone |
| `TUTOR_TTS_FALLBACK_VOICE`, `TUTOR_TTS_FALLBACK_MODEL`, `TUTOR_TTS_FALLBACK_COOLDOWN_S`, `TUTOR_TTS_COOLDOWN_FILE` | Optional fallback voice/model override (Google default: `sv-SE-Chirp3-HD-Aoede`; required when `TUTOR_TTS_FALLBACK=cartesia` because Cartesia has no Swedish default), quota cooldown in seconds (default `600`), and cooldown state file path (default `~/.cache/open-tutor/tts-cooldowns.json`, mode `0600`) |
| `ELEVENLABS_API_KEY` / `GOOGLE_TTS_CREDENTIALS_JSON` / `DEEPGRAM_API_KEY` / `CARTESIA_API_KEY` | Voice provider credentials. Google Cloud TTS reads `GOOGLE_TTS_CREDENTIALS_JSON` (compact service-account JSON string, e.g. from Infisical), `GOOGLE_APPLICATION_CREDENTIALS` (file path), or `gcloud` ADC |
| `TUTOR_LLM` | `go` (default): Muse Spark 1.3 Contributor (`muse-spark-1.3-contributor`) on OpenCode Go, Responses API over HTTP streaming, `OPENCODE_GO_API_KEY`. `cc`: the same model (`meta/muse-spark-1.3-contributor`) on Command Code, `COMMAND_CODE_API_KEY` -- the stability backup, usable as the preferred or the fallback route. `go-deepseek`: DeepSeek V4.1 Flash on the same subscription. `gemini`: Gemini 4 Hydrogen (`gemini-4-hydrogen`) on Google's OpenAI-compatible Chat Completions, thinking level `low`, `GEMINI_API_KEY`. `gemini-dev` only reproduces the board/voice bug of the earlier development route; do not deploy it. This is the preferred route; there is no silent fallback to a route the operator did not name. |
| `TUTOR_LLM_FALLBACK` | Optional second candidate route (`go`, `go-deepseek`, `gemini`, `cc`). Empty (default): one route for the whole session, no warm-up race. Set: both routes answer a warm-up request while the greeting plays and the winner serves the session; see [the greeting and the session's voice](#the-greeting-and-the-sessions-voice) |
| `TUTOR_LLM_PREFER_WITHIN_S` | Default `1.5`. The preferred route keeps the session if its warm-up answered within this many seconds, or if it was the faster of the two |
| `TUTOR_LLM_TIMEOUT_S` | Default `5`. Timeout per LLM attempt (the framework default is 10 s), with one retry on the same route; then the failover or the spoken apology |
| `TUTOR_LLM_HEDGE_AFTER_S` | Default `2.5`. Seconds a tutor turn runs on the primary route alone before the identical request also starts on the other route; the first stream to yield a chunk wins. `0` or empty disables hedging (today's single-route turns). Only between routes that both ignore thought signatures (never with `gemini`) |
| `TUTOR_LLM_RACE` | Off by default. `1`/`true`: both routes start every hedged turn at once (hedge delay `0`) and the first chunk wins, so every turn gets min-of-two latency. Needs a hedge target: with `TUTOR_LLM_HEDGE_AFTER_S=0`/empty there is nothing to race and turns stay single-route. `llm_turn` gains `race: true` plus the loser's first-chunk time when it arrived before the cancel |
| `TUTOR_LLM_FALLBACK_BASE_URL` | Override only the fallback route's endpoint (for example a second provider in a test). `TUTOR_LLM_BASE_URL` keeps overriding the preferred route |
| `OPENCODE_GO_API_KEY` | OpenCode Go API key (from the OpenCode console). Backend only |
| `COMMAND_CODE_API_KEY` | Command Code API key (same Muse Spark model on another provider). Backend only |
| `TUTOR_LLM_MODEL`, `TUTOR_LLM_BASE_URL`, `TUTOR_LLM_REASONING` | Override the route's model, endpoint or reasoning effort (Go default `minimal`) |
| `TUTOR_AGENT_NAME` | Dispatch name, default `open-tutor`. Give a test worker and its web service another name so it never takes a family session |
| `EXA_API_KEY` | Resource search |
| `TUTOR_BAND` | Testing override for the age band (`primary` | `middle` | `upper`). Advertised via `/api/config`; applies only when the page names no band (no `?band=`, nothing remembered). Empty (default): the request host picks the band |
| `TUTOR_ALLOWED_COUNTRIES` | Optional comma-separated Cloudflare country codes, e.g. `SE`. Missing/disallowed country headers get 403; `/api/health` remains accessible |
| `TUTOR_MAX_SESSIONS_PER_HOUR` | Owner spending cap across the instance (default 12) |
| `TUTOR_CLOUD_RECORDING` | `1` uploads session audio and transcripts to LiveKit Cloud observability. Off by default |
| `TUTOR_DEBUG_LOG` | `1` writes a per-session debug trail to a private local directory (see below). Off by default |
| `TUTOR_DEBUG_LOG_DIR` | Override the debug trail directory (default `~/.local/state/open-tutor/sessions`) |
| `TUTOR_SCREEN_SHOTS` | Default `1`. How many of the newest Smart Screen screenshots stay in the live tutor's chat context. Each screen page and each applied change adds a high-detail PNG; without a limit every earlier one was re-sent with every voice turn (~1 100 tokens and 50-200 kB each). The newest shot of the page on screen and of any page still held back (`show="hold"`) is always kept, and only screenshots are dropped: the page source stays. `99` keeps every screenshot (the behaviour before 2026-11-27), `0` keeps none. See [the tutor's context](../docs/smart-screen.md#2026-11-27-one-screenshot-in-the-tutors-context-and-look-pass-evidence) |
| `TUTOR_POSTHOG_KEY` | PostHog project token (`phc_…`, EU cloud). Unset (default): analytics fully off, no SDK load, no network calls |
| `TUTOR_POSTHOG_HOST` | PostHog host, default `https://eu.i.posthog.com` |
| `TUTOR_STT_MAX_ENDPOINT_MS`, `TUTOR_MIN_ENDPOINT` | Turn-taking tuning for pauses while a child thinks. `TUTOR_MIN_ENDPOINT` (default `0.6` s) is the silence after a complete answer before the tutor speaks |
| `TUTOR_TURN_DETECTION` | `hesitation` (default): when the child's turn trails off (only filler sounds, a trailing `att`/`och`/comma/ellipsis …), Soniox's end-of-speech is held back so the tutor waits instead of cutting in; LiveKit's turn detection stays `stt`. `stt` holds nothing (the behaviour before 2026-11-27). An unknown value stops the worker at boot. See [the hesitation hold](../docs/smart-screen.md#the-child-may-hesitate-without-being-cut-off) |
| `TUTOR_MAX_ENDPOINT` | Default `2.8` s, `hesitation` mode only: the held end waits `TUTOR_MAX_ENDPOINT − TUTOR_MIN_ENDPOINT` (2.2 s) after Soniox's endpoint before the turn ends. Never below `TUTOR_MIN_ENDPOINT` |
| `TUTOR_NOISE_CANCELLATION` | `off` (default, today's behaviour), `nc` or `bvc`: LiveKit's enhanced noise cancellation on the child's inbound audio, before the VAD and the recogniser. See [noise and background voice cancellation](#noise-and-background-voice-cancellation). An unknown value stops the worker at boot |
| `TUTOR_FILLERS` | `1` lets the fox make one short pre-made sound when a reply to the child's turn is late. Off by default |
| `TUTOR_FILLER_AFTER_S` | How long the child may wait for the reply before the sound (default `0.7`) |
| `TUTOR_FILLER_CLIPS_DIR` | Parent directory for the cached clips (default `~/.cache/open-tutor/fillers`) |
| `TUTOR_IDLE_TIMEOUT_S` | Seconds of learner silence before the call ends itself (default `1200`, 20 minutes). Speech (final or interim transcript), typed chat, homework uploads, page answers and mic-button presses reset the clock; tutor speech alone never does, and it never fires mid-speech. `0` or negative disables the timeout. The page shows the normal end card with the idle message, and the ended event carries outcome `idle_timeout` |
| `SCREEN_FALLBACK` | Optional Smart Screen backup (`cc` = the same Muse model family on Command Code). Empty (default): one provider per model call, today's behaviour. Set: a first-text hedge (below) races the backup against a slow primary within the job budget; without the backup key the fallback is disabled with one warning and the primary serves alone. See [the screen and its backup](../docs/smart-screen.md#command-code-backup-tutor-route-cc-and-screen-failover-2026-11-14) |
| `SCREEN_HEDGE_AFTER_S` | Default `5`. Seconds a screen model call (page, look, retry) runs on the primary alone before the same call also starts on `SCREEN_FALLBACK`; first output text wins, the loser is cancelled and its stream closed. Empty keeps the older flat-timeout failover (`SCREEN_PRIMARY_TIMEOUT_S`); the hedge never starts with under 2 s left in the job or step |
| `SCREEN_RACE` | Off by default. `1`/`true`: with `SCREEN_FALLBACK` set, both providers start every model call at once and the first *completed* call wins (not first text), so a provider that stalls mid-page loses to the one that finishes. One side erroring waits for the other within the call's deadline; both failing raises as today. `screen_hedge` and the per-call notes gain `race: true`, the winner's total time and the loser's time/error when known |
| `SCREEN_PRIMARY_TIMEOUT_S` | Default `10`. Only for the flat-timeout failover above: client timeout per screen model call before the fallback is tried, fitted inside the calling step's own budget |
| `SCREEN_IMAGE_REVIEWS` | Default `3`, at most `6`. How many of a slot's image candidates are downloaded and vision-reviewed at once, and the ceiling on reviews in flight for the whole page (several slots resolve concurrently). `1` reviews them one after another, as before 2026-11-18. Each slot's best-ranked review keeps the hedge; the rest are single attempts, so N candidates cost at most N+1 provider calls per source list. See [concurrent candidate reviews](../docs/smart-screen.md) |
| `SCREEN_IMAGES` | Smart Screen image source: `commons` (default, today's behaviour: Wikimedia Commons only), `commons+parallel` (search both at once via the Parallel Images API in fast mode; review Commons first, take the first candidate the vision review accepts), or `parallel` (Parallel only). Needs `PARALLEL_API_KEY` (Infisical); without it, or while Parallel cools down after credit/auth errors (10 min) or transient failures (1 min), the job falls back to Commons-only silently. Per-image records (source, query, latency, verdict) land in meta.json `images`/`image_reviews`; Parallel ships with a `Källa: <site>` credit, and the existing vision review of the actual picture stays the gate. An accepted Parallel picture is stored under the session (`<session>/images/`, content-addressed `<sha256>.<ext>`) and served by the web app at `/api/images/<sha256>.<ext>` (immutable cache, nosniff); unknown hashes answer 404 |

### Open Sweden testing (no access code)

The public instance asks for no code: `TUTOR_ALLOWED_COUNTRIES=SE` admits
Swedish visitors directly (2026-11-18 the family-code gate was removed from
both the page and the web service; other hosts needing a gate should put it
in a reverse proxy). Country checks cover the page, assets
and session creation. The session-start cap still applies. IP geolocation is
approximate and VPNs affect it.

The `CF-IPCountry` header is forgeable by anyone who can reach the origin
directly, so this check is only as strong as the ingress: keep the web service
reachable solely through the Cloudflare tunnel (production binds a tailnet
address) and never expose the origin itself.

This restriction trusts Cloudflare's `CF-IPCountry` header. Enable Cloudflare IP
Geolocation and keep the origin private behind its tunnel; a publicly reachable
origin would allow clients to forge that header. The current origin binds to
ThinkCentre's tailnet address, with public requests arriving through the Mini's
Cloudflare tunnel. Health checks are exempt to preserve local monitoring.

## Noise and background voice cancellation

A parent and a 13-year-old at one phone in a normal home: sound in the room was taken for the
child, cut the fox off mid-sentence and made it answer talk that was not meant for it. LiveKit's
enhanced noise cancellation runs **server-side on the agent's inbound audio**, before the VAD and
the recogniser, so a turn can only start from filtered audio. That is why it belongs here rather
than in the page.

`TUTOR_NOISE_CANCELLATION` picks the filter (`server/open_tutor/noise.py`):

| Value | Model | What it does |
|---|---|---|
| `off` (default) | none | Today's behaviour. The plugin is not even imported |
| `nc` | `noise_cancellation.NC()` | Krisp NC: removes non-speech noise (traffic, fans, music), keeps every voice |
| `bvc` | `noise_cancellation.BVC()` | Krisp BVC: NC plus removing non-primary voices, i.e. other people talking |

What the documentation says (checked 2026-11-13, not from memory):

- The filter is configured on the agent's audio input and runs before STT and VAD —
  [Noise & echo cancellation](https://docs.livekit.io/transport/media/noise-cancellation/),
  [Agent session](https://docs.livekit.io/agents/logic/sessions/).
- The package is `livekit-plugins-noise-cancellation` (`~=0.3`, ours is 0.3.3) and offers `NC()`,
  `BVC()` and `BVCTelephony()` — [PyPI README](https://pypi.org/project/livekit-plugins-noise-cancellation/).
  The models ship in the wheel (about 70 MB) and run in the worker process; nothing is uploaded
  for it. The package "requires LiveKit Cloud", which is what our rooms already use. No extra key,
  no dashboard setting and no plan upgrade was needed: our Cloud project ran both models on the
  free Build plan.
- **Cost** — [pricing](https://livekit.com/pricing): background noise suppression (Krisp NC,
  ai-coustics QUAIL_L) is included on every plan. Voice isolation (Krisp VIVA/VIVA telephony,
  ai-coustics Voice Focus S/L) is metered: 100 minutes on Build, 1,000 on Ship, then
  $0.0012/minute. BVC is named in neither row, so treat its billing as unconfirmed; it is the
  model the owner asked for and what `TUTOR_NOISE_CANCELLATION=bvc` uses.
- **For one near-field speaker with other voices in the room**, the docs recommend a *voice
  isolation* model ("Voice isolation works well when there is a single speaker, while background
  noise suppression is better for multiple speakers"; the LiveKit blog's short version is "for a
  single primary speaker, use a voice isolation model"). In this package the equivalent intent is
  `BVC`. The dedicated voice-isolation plugins (`livekit-plugins-ai-coustics`,
  `livekit-plugins-krisp`) are separate packages and are the metered ones above.
- **Do not run two cancellation models at once.** "When using noise cancellation or voice
  isolation in the agent code, do not enable noise cancellation models in the frontend… Standard
  noise cancellation and the separate echo cancellation feature can be left enabled." Our page
  asks for the browser's own `echoCancellation`, `noiseSuppression` and `autoGainControl`
  (`web/src/useSession.ts`, `new Room({audioCaptureDefaults})`), does not use
  `@livekit/krisp-noise-filter` and never asks for `voiceIsolation`. That is exactly the allowed
  combination, so **the web app needs no change**; a device that only has `noiseSuppression`
  listed as a supported constraint simply keeps it.

Where the cost lands: the first `import livekit.plugins.noise_cancellation` costs about a second
and loads the native filter, so it happens at process prewarm (`noise.warm_up`, called from
`prewarm`), never on the first turn. Before that fix the dev worker logged "event loop blocked
for 1096 ms importing livekit.plugins.noise_cancellation" inside a session and the greeting
arrived at 1.46-1.49 s instead of 0.22-0.26 s.

What was measured (own instance, 2026-11-13; the numbers and what could not be concluded are in
[docs/smart-screen.md](../docs/smart-screen.md)):

- The filter really runs: on a noise bed it cuts overall level by 25 dB (BVC) and 38 dB (NC) and
the peak from 12,000 to about 5,300 and 1,300.
- On speech it is close to transparent, and `bvc` changed nothing the tutor did in the three
  cases that matter: room-only talk was still heard as the child, the fox was still interrupted
  about 1.9 s in, and a clear sentence was still transcribed in every mode. NC keeps all speech
  by design, and BVC removes *non-primary* voices — with the child silent, the room's voice is
  the primary one, so it passes.
- Greeting timing with `bvc` after the prewarm fix: 0.48-0.86 s (dev "start a process per job"
mode, where prewarm runs at job start) against 0.22-0.29 s with `off` and 1.46-1.49 s before it.

So `bvc` is the value to try on a real phone, and the two failures it cannot fix on its own are
the ones that happen while the child is silent.

Regenerate the audio and measure again (fictional Swedish speech only, synthesized with the
session's own voice):

```bash
OPEN_TUTOR_ENV=~/.config/open-tutor-nc-dev/env \
  server/bin/with-env uv run --project server python server/scripts/noise_cancellation_audio.py \
  --out /tmp/nc-audio
# what the filter itself does to each clip (needs LiveKit Cloud credentials)
OPEN_TUTOR_ENV=... server/bin/with-env uv run --project server python \
  server/scripts/noise_cancellation_bench.py --audio /tmp/nc-audio --out /tmp/nc-bench
# what the tutor does with it, against a running worker
OPEN_TUTOR_ENV=... server/bin/with-env uv run --project server python \
  server/scripts/noise_cancellation_probe.py --audio /tmp/nc-audio --case background \
  --out /tmp/nc-runs/background
```

## Filler sounds

A child who has stopped talking expects an answer. When the tutor model takes
longer than `TUTOR_FILLER_AFTER_S` (default 0.7 s), the fox makes one small sound
("Mm", "Hmm", "Aha", rarely "Ska vi se…") instead of leaving the room silent.
`TUTOR_FILLERS=1` switches it on; it is off by default.

- **The clips are made once, in the configured voice.** `fillers.py` synthesizes
  them with the same TTS the session uses and caches WAV files under
  `~/.cache/open-tutor/fillers/<provider>-<voice>-<hash>/`, keyed by a
  fingerprint of TTS provider, model, voice and expressivity, so a voice change
  regenerates them. They are made in the background on first use (never during a
  turn); if generation fails, the feature stays off and says so once in the log.
- **Playback is LiveKit's `BackgroundAudioPlayer`**, on its own audio track. That
  keeps the sound out of the speech pipeline entirely: no TTS call at that
  moment, nothing in the chat context or the transcript, no caption, no
  `chat_item` in the debug trail, and no speech handle that could queue the real
  reply behind the filler. `PlayHandle.stop()` plus `AudioSource.clear_queue()`
  cuts it the moment the child speaks or the reply starts.
- **When it plays, and when it must not.** Only for a turn the child started
  (speech or typed) and only while a reply is pending; never for the greeting or
  any other session event, never twice in a turn, never the same clip twice in a
  row, nothing in quiet-work or resource mode, and nothing while the child is
  speaking. A reply that arrives sooner cancels it.
- **In the session log** it is its own event: `filler` with the clip name, the
  turn and the delay, `filler_stopped` with why and how much played, and
  `filler_skipped` with the reason when it decided not to play.

Generate the clips ahead of time or listen to them:

```bash
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env \
  server/bin/with-env uv run --project server python server/scripts/filler_clips.py \
  --out /tmp/filler-clips            # --force regenerates
```

The script prints each clip's trimmed duration, level and the number of energy
parts (one hum, two for "a-ha", one per word for a phrase); nothing here is a
substitute for listening once after a voice change.

The web app gives a second agent audio track its own `<audio>` element
(`web/src/audioTracks.ts`); with one element per stream, the filler and the
speech cannot replace each other.

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

Turn-taking events added 2026-11-27: `turn_hold` (the hesitation hold kept a
turn open; reason word and word count only), `turn_hold_resumed` (the child
carried on during the hold) and `screen_prompt_deferred` (a
finished page arrived right after the tutor asked the child a question, so the
page-ready prompt was skipped).

Review the most recent sessions where the worker runs:

```bash
bin/with-env uv run python scripts/debug_sessions.py --list
bin/with-env uv run python scripts/debug_sessions.py --last --learner kian
bin/with-env uv run python scripts/debug_sessions.py --show tutor-XXXX
```

Default off, so open-source adopters get no behaviour or file change.

The trail's config snapshot also records analytics state as `posthog_enabled`
(`"1"`/`"0"`): the project token itself is never written anywhere server-side.
See [hosting](../deploy/README.md) for turning PostHog on.

## Board transport

The tutor never draws. A background Screen agent writes pages and patches (see
[docs/smart-screen.md](../docs/smart-screen.md)); this section covers the transport only.

- Dimension handshake: `board.show`/`board.update` acks return
  `{ok:true, board:{w,h,device}}` once the pane has settled. The worker uses those dims
  as the page's render size. Every board RPC goes through one serialized delivery path
  per session, so no two changes interleave on the way to the browser.
- A `pending` placeholder is still a valid board item, but nothing produces one now:
  a page appears when the Screen has finished it.

## The greeting and the session's voice

The child hears the fox immediately, and the model that serves the session is picked
while that greeting plays (2026-11-13/14).

**The greeting is fixed text, spoken by TTS.** `session.say` speaks one of four variants
(`prompt.GREETING_VARIANTS`) with the child's name: who it is, that it helps with
homework and schoolwork, and what they are working on today. No LLM is involved, so the
greeting lands within about a second whatever the provider is doing. `say` puts the line
in the chat history as the assistant's turn, and `prompt.greeting_note` moves what
`greeting_instruction` used to carry into the instructions (do not greet again, and for
a returning learner, when it fits, say in a few words what you worked on last time). The
greeting is interruptible: speech or typing stops it and the turn is answered as usual,
and a message typed before it plays replaces it (`text_input.TypedChat.start`). The
debug trail records `greeting` (variant and line) and `greeting_done` (interrupted?).

**The route is chosen once, by a warm-up race.** With `TUTOR_LLM_FALLBACK` set,
`session_llm.SessionLLM` sends a short warm-up request to both candidates while the
greeting plays: the real system prompt and the real tool list, one word to say, aborted at
the first token. So the provider does the prompt work the real reply needs and can cache
the prefix, and the whole warm-up costs a handful of output tokens. Time to first token
decides.

The rules:

- the preferred route keeps the session if it answered within `TUTOR_LLM_PREFER_WITHIN_S`,
  or was the faster of the two;
- a route that errors or has not answered within 5 s loses;
- if neither answered, the preferred route stays and normal error handling applies;
- the choice is for the **whole session**. Per-turn switching is unsafe: Gemini rejects a
  retained history that holds function calls it did not sign, so a request is never
  replayed on another route mid-conversation. A first turn that arrives before the race
  decided waits for it, bounded by the 5 s cap.

The choice and both timings are recorded as an `llm_chosen` event and in the report's
summary (`llm`). `AgentSession` takes its LLM at construction and `Agent.update_options`
only swaps for the next turn, so a thin `llm.LLM` wrapper delegates `chat()` to the chosen
route. LiveKit's own `FallbackAdapter` is per-request failover, which is exactly the
per-turn switch described above.

**Shorter leash, one failover.** `TUTOR_LLM_TIMEOUT_S` (5 s) with one retry on the same
route replaces the framework's 10 s with three retries. If the chosen route then fails
before it has said anything, and the other candidate does not need thought signatures,
the session fails over to it for the rest of the run (`llm_failover` in the log). Failing
over to a signature-checking route is not safe, and a failure after the child has heard
words is not repeated; both fall to the existing apology path, which speaks one sentence
without the LLM and ends the session instead of leaving silence with no event. 5 s fits a
warm text prompt (2-3 s to first token here); a turn carrying a screenshot, or a provider
under load, can need more, so raise `TUTOR_LLM_TIMEOUT_S` if sessions end with the apology.

**Hedged turns.** A provider can spike mid-session, after the race. Each turn starts on
the current primary route; if no first chunk (text or tool call) arrives within
`TUTOR_LLM_HEDGE_AFTER_S` (default 2.5 s), the identical request also starts on the
other route. The first stream to yield a chunk wins and serves the whole turn; the loser
is cancelled and closed, and nothing is forwarded before the winner is decided, so the
child never hears a mixed reply. One stream erroring before any chunk lets the other
continue; both failing raises, as a single route would. Attempts never exceed today's
worst case (the primary keeps its one same-route retry, the secondary gets none). Hedging
only runs between routes that both ignore thought signatures (never with `gemini`); with
one route, with hedging off, or with a signature-checking route, turns behave exactly as
before. A secondary route that wins twice running becomes the primary for following
turns (`llm_sticky_switch` in the log), symmetrically back again. Every turn records an
`llm_turn` event (primary, winner, winner ttft, hedged, loser state) and feeds the
`tutor_session_ended` analytics. With `TUTOR_LLM_RACE=1`, both routes start every
hedged turn at once (hedge delay `0`); first chunk still wins and the loser is still
cancelled, so a slow primary never costs a turn its head start.

**Warm connections.** The OpenAI SDK's default keep-alive expiry (5 s) meant most turns
paid a fresh TLS handshake. The tutor and screen clients share one httpx transport per
host with a ~120 s keep-alive (`open_tutor/http_clients.py`), so turns reuse warm
connections across a lesson; worker prewarm opens one cheap request (the provider's model
list) to each configured provider, bounded to ~5 s and never failing the worker.

## Tests

```bash
uv run pytest -q
```

`scripts/two_session_probe.py` runs two consecutive typed sessions for one fictional learner against a running worker. The first session's saved note goes into the second, as in the browser. It checks that board items arrive and are acknowledged in both, and that no tool name, arguments or JSON reach the captions (the text the voice speaks).

`scripts/live_probe.py` runs a real session against a running worker with a scripted fictional learner: recorded Swedish clips, a generated worksheet, an interruption, 30 s of quiet work, mumbling, and the end of the session. It writes a JSON timeline and the tutor's audio. It uses live providers and costs a little; it is not part of CI.

Run the web service with `uvicorn open_tutor.web:app --workers 1`.
