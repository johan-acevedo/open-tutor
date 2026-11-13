# Step 4e: real voice + browser material probe (evidence)

One real session against the isolated preview, no mocks. Fictional learner
**Pax** (ephemeral browser profile, no family/student data); learner speech is
**synthetic Swedish TTS, labelled as such everywhere** — this is not a real
child's lesson. The probe never calls `search_materials`/`show_material`;
only the live tutor model can, after hearing the learner.

- Preview: <https://elitebook.tail2e1c4e.ts.net:9443/> (systemd user services
  `open-tutor-materials-web`/`-agent`, parent checkout at `c3576d8`).
- Providers actually used: Soniox STT (sv), Muse Spark via OpenCode Go
  (HTTP Responses, reasoning minimal), Deepgram `flux-ludvig-sv`
  TTS, LiveKit Cloud dispatch `open-tutor-materials-preview`.
- Index: full eight-book `full-library-index` (7233 vectors). Load at start
  0.83 (8 cores); dispatch worked, no quota/login/worker-capacity blocker.
- Session room `tutor-HI7nWVamK5Dv`, 2026-11-13 ~01:28–01:34 UTC.
- Probe: `web/e2e/material_voice_probe.py` (rerunnable; builds the mic tape
  with the existing Deepgram adapter, drives Chromium with
  `--use-file-for-fake-audio-capture`, polls captions/audio/DOM, ends via UI).
- Raw evidence (outside git):
  `~/.local/state/open-tutor/material-probe/20261113T012827Z/`
  (report.json, timeline.jsonl, captions, audio-energy samples, screenshots,
  tape + clips, fetched section HTML/metadata, first source figures).
  No tokens, keys, or media are committed.

## What happened (probe clock)

| t | event |
|---|---|
| 21 s | joined, mic live (1.0 s after Starta) |
| 24–30 s | tutor greets by name: "Hej Pax! Jag är Räven … vad jobbar du med idag?" |
| ~66 s | synthetic U1 airs: search the school book for closed battery/lamp circuits, show the page, explain the figure |
| 90 s | tutor: "Jag söker i skolboken åt dig och tar fram sidan." |
| 141 s | material card ready: `sec-ecd16baf9e4fee44`, "A simple circuit" (Siyavula Natural Sciences and Technology, Grade 6, CC-BY), real attribution + original page in the opaque `sandbox=""` iframe |
| 157–208 s | tutor teaches from the page: battery plus/minus, lamp's two contacts (bottom + threaded side), open vs closed ring, describes the book's first and last figures, asks Pax which figure shows a closed circuit |
| 292 s | probe finishes checks; ends via the real Avsluta button |
| 318 s | clean end card: "Bra jobbat idag, Pax!" + saved note "Sluten elektrisk krets med batteri och lampa" |

32 caption turns (2383 chars), audible inbound tutor audio in 22/135
samples (max RMS 0.276 on the page's `<audio>` element), zero browser errors.
The planned optional second scenario (maths worked example, tape offset 330 s)
never aired: the session ended first by design. It is **not** covered.

## Proven, with the boundary of each claim

- **Real STT → real tutor → real tools.** The spoken Swedish request was acted
  on literally: announced book search, then the exact circuit section appeared.
  No STT transcript strings are quoted (preview sets no `TUTOR_DEBUG_LOG`). Parent independently found room-scoped systemd journal records confirming `tools executed: search_materials`, `board rpc board.show b1 acknowledged=True`, and `tools executed: show_material` for this exact room at 01:30:37–01:30:47 UTC.
- **Model chose search + show itself.** Section `sec-ecd16baf9e4fee44` matches
  the request; the "could not show" fallback never appeared, so the true
  browser acknowledgement (`board.show` → metadata + HTML preflight + frame
  load, inside the 12 s server RPC deadline) succeeded.
- **Real rendered MaterialSection.** Screenshots show the original Siyavula
  page (heading, NEW WORDS box, activity, source styles, CC-BY attribution).
  Fetched over HTTPS like the browser: metadata 200, HTML marker
  `data-material-section` present, 20/20 unique `<img>` refs, 12/12 sampled
  image URLs 200. Opaque sandbox respected: element screenshots only, no code
  run inside the frame.
- **Vision is real for the attached images — and bounded.** The tutor said the
  first figure has one wire plus→lamp-bottom with minus unconnected (open),
  and the last figure has minus→lamp-side plus plus→lamp-bottom (closed ring).
  I inspected the actual source files: `ec-gd-0001.jpg` and `ec-gd-0006.jpg`
  show exactly that routing. The page text says "ONE wire"/"TWO wires" but
  never the routing, so this detail can only come from the attached image
  bytes via image-context injection + Go Responses serialization — not from
  generic circuit knowledge. "Last figure" is consistent with the 6-image
  attach budget (page order 1–6 of 20). **Not** proven: the 14 omitted images,
  other sections, or what the child has scrolled to — and the tutor stayed
  inside that boundary ("skrolla", "säg vilken bild", never claiming full
  coverage).
- **Real TTS audio reached the browser.** Word-stepped captions plus measured
  audio energy on the remote track; greeting, search notice, teaching, and
  goodbye all arrived as sound, not just text.
- **Memory note worked.** The end card carries a correct topic and next step,
  saved through the live session.

## Not claimed

No second scenario, no retrieval-quality statement, no latency claim, no
server-side tool-argument log (no debug trail exists for preview), no product
or deployment change. Small probe CLI is the only new artifact; parent owns
review, rerun decisions, and any follow-up.

## Parent review

The parent inspected the actual report, captions, screenshot and source figures, and independently verified tool execution and the boolean board acknowledgement in the room-scoped systemd journal. The probe now reads those filtered journal messages and exits nonzero on missing material identity, tools, ack, source-image fetches, audible tutor audio, clean end, or browser errors. Those gates were applied retrospectively to the saved real run without another provider call. Future runs require access to the preview's user journal (run on elitebook).

The recorded first search/display wait is long in this single run; this is a working prototype, not evidence of conversational retrieval latency. Optimizing cold model loading and testing a maths conversation remain follow-up work. Source diagrams were shown and discussed successfully; this does not establish learning outcomes.
