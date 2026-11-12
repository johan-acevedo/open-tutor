# Browser-owned Screen track

Status: Screen fixes reviewed; Muse fox with local pc2014 ZONOS3 speech verified in development, 2026-11-12.
Lead: this thread. Workers receive focused briefs; the lead owns integration and decisions.

## Source of truth

- Development branch: `feat/browser-screen-agent`.
- Base: `origin/main@05c23a451fd2fae7191c366b49e8d95dff9ae15d`, verified as the live ThinkCentre checkout on 2026-11-11.
- Technical proof: `t3/browser-owned-pi-proof@cb910f1`, `experiments/browser-screen/`; 15/15 live-browser checks passed in the proof environment.
- Production remains untouched. No deployment is part of this stage.

## Destination

Räven leads the live voice moment. A separate, browser-owned Screen agent thinks about the visual workspace, prepares material on its own, and owns the durable page deck. The Screen is not a server-side drawing command with a new name: it has its own agent history, local persistence, tools, and authority over what becomes visible.

The first real slice must support both:

1. A maths exercise with a private solution, child-submitted input, fox-gated reveal, and recovery after an interrupted lesson.
2. A geography question for which background workers research or create map material, the main Screen promotes an appropriate candidate, and Räven observes the actual visible page.

## Agreed product contract

### Räven owns

- Voice, interruption, turn-taking, and the live pedagogical moment.
- High-level visual intents and the lesson context needed to fulfil them.
- Deciding when a visual is relevant and when a prepared answer may be revealed.
- Its own tutor model and voice-session state on the server for now.

### The main Screen owns

- Its browser-resident Pi Durable session and all commits to the visual workspace.
- Page and revision identity, current-page state, navigation, and page-local child input.
- Validation, selection, and promotion of invisible candidates into visible pages.
- Acceptance, stale rejection, duplicate handling, progress, and failure reporting for fox intents.
- Its own tools and internal worker/artifact pipeline.

Only the main Screen may promote a candidate into the visible deck. Neither Räven nor a research subagent writes visible pages directly.

### Autonomy and double buffering

The Screen may research in anticipation of an imminent fox request. Its internal layers are:

1. **Artifacts:** raw or derived materials such as search results, source text, downloaded images, generated SVG, map data, calculations, captions, and attribution. A subagent may produce artifacts for another subagent without creating a page candidate.
2. **Candidates:** complete but invisible page compositions, including references to their artifacts and private teaching context.
3. **Visible pages:** durable, revisioned pages promoted by the main Screen.

If Räven has an outstanding request that a candidate satisfies, the main Screen may promote it when ready without a second request. Merely anticipatory work remains invisible until requested. Candidates tied to superseded lesson context are rejected or discarded.

The Screen may choose the medium and tools—generated SVG, sourced images, map SDKs, generated layouts, or others—rather than being restricted to a predefined board-card type. Tool choice is an implementation detail bounded by security, provenance, and the task.

### Knowledge and observation

Räven receives two deliberately separate things:

- **Public observation:** the actual pixels of the current rendered page, captured on demand after rendering has settled. No continuous screenshot stream.
- **Private teaching context:** a narrow field such as the correct solution or teacher notes, supplied so Räven can teach without exposing hidden content.

Räven does not receive the Screen's whole Durable history. Hidden answers must not be included in public observations.

### Child input

A page may expose a designated answer area owned by the child. Arbitrary child editing of generated pages is not implied.

- Local edits may be persisted by the Screen for interruption recovery.
- Räven does not receive every keystroke.
- The answer is shared on explicit submission or when the child discusses it.
- Typed and spoken answers may be associated with the current page, but the first slice requires explicit typed submission.

### Continuity

An intentional new visit starts a new lesson with an empty visible workspace. The learner should still receive a familiar greeting informed by previous work on that device.

- Prior-lesson summaries and learner profile/notes remain device-local.
- Previous work is not loaded onto the new visible board.
- There is no server-side learner workspace, cross-device sync, or account system in this track.
- An accidentally interrupted lesson should be resumable; intentional new lessons should not reuse its visible deck.
- The existing browser profile notes remain compatible. The Screen may keep richer local lesson summaries without moving them to the server.

## Current live architecture relevant to the change

- `server/open_tutor/agent.py`: fox tools commission/edit server-rendered boards through LiveKit RPC and receive a server-generated board screenshot.
- `server/open_tutor/board.py` and `web/src/protocol.ts`: mirrored board item and protocol types.
- `web/src/useSession.ts`: LiveKit RPC handlers, board item state, learner notes, homework intake, and session lifecycle.
- `web/src/components/Board.tsx`: the current accumulated/scrolling board surface. The Screen replaces this interaction model with one page at a time, not another scrolling feed.
- `web/src/db.ts`: browser-local profiles and the latest 20 tutor notes.
- `docs/protocol.md`: protocol documentation that must change with the implementation.

The proof's canvas and controls are technical test surfaces, not the production visual design to ship.

## External protocol v1

The new namespace is separate from legacy `board.*`. The production Screen path does not retain a scrolling legacy board alongside it; homework and other material enter the Screen's artifact/page model instead.

### Fox to browser

RPC `screen.intent` carries:

```ts
{
  intentId: string;
  lessonId: string;
  op: "prepare" | "show" | "reveal"; // focus/revise are later extensions
  need?: string;
  background?: string;
  target?: { pageId: string; revision: string };
  viewport: { w: number; h: number; device: string };
}
```

The RPC returns immediately with `{ accepted: true, intentId }` or a validation/lesson rejection. It never waits for model work, rendering, or assets. `prepare` may produce a candidate without changing the visible page. `show` authorises promotion when a suitable candidate is ready. `reveal` is a deterministic page/revision operation, not a Screen model turn.

RPC `screen.observe` carries `{ observationId, lessonId, pageId, revision }` and returns immediately after accepting a current-page observation request. Overlapping or stale observations are rejected rather than queued indefinitely.

### Browser to fox

Text stream `screen-event` carries correlated outcomes:

```ts
{
  type: "ready" | "rejected" | "failed" | "answer-submitted" | "page-changed";
  intentId?: string;
  lessonId: string;
  page?: { id: string; revision: string };
  reason?: string;
  answer?: string; // answer-submitted only
}
```

A duplicate intent id receives the existing outcome rather than executing twice. `ready` means the page is committed and its visible canvas has rendered. Räven may then request an observation. A stale reveal returns `rejected`; a duplicate reveal returns the already-ready outcome without another mutation.

For an accepted observation, byte stream `screen-pixels` carries one bounded PNG with `observationId`, page id, and revision attributes. Text stream `screen-context` carries a small JSON record with the same correlation ids, visible interaction state, viewport, sources, and `privateTeaching` (for example the hidden solution). The whole Screen transcript and page HTML/source are never sent.

The fox tool may await the asynchronous ready event and observation internally, but LiveKit RPC calls themselves stay within their short timeout. Slow preparation therefore does not block the voice loop or cause a misleading mount acknowledgement.

## Browser architecture decisions

- Pin the published Pi Durable packages initially at the proven 1.5.2 versions.
- Keep the Harness in a Web Worker and credentials out of browser storage and source.
- Use one Durable session per learner profile on that device. Its current visible deck has a `lessonId`; an intentional new lesson archives/summarises the old deck and clears visibility, while interruption reopen retains it.
- Use Durable-native child conversations and background tasks for research. JSON docs outside the main chat log hold raw/derived artifacts and candidates. Child conversations use explicit model/compaction settings and replay-safe request ids.
- Large binary assets live in a separate IndexedDB blob store. Durable docs contain only asset ids, hashes, MIME type, provenance, lesson/request scope, and status. Observation PNGs are transient and are not added to durable docs.
- The main Screen validates and promotes candidates with a plain TypeScript commit. Subagents never receive a visible-deck write tool.
- The main conversation remains reactive to newer intents; expensive work runs in background children. Busy steering and cancellation/supersession are explicit rather than implicit UI behaviour.
- Model calls go through the existing FastAPI service at `/api/screen/openai/{room}/chat/completions`. The family code is the existing browser credential; the random room id scopes upstream routing and rate limits. The provider key remains server-side, responses are `no-store`, and no request/response lesson record is persisted.
- The first geography tool calls a bounded `/api/screen/research/geography` gateway. It uses public Nominatim/Wikimedia data, enforces HTTPS/DNS/private-address/redirect/size/time/content-type limits, and returns provenance with small static assets. Generic web search, interactive map SDKs, and new paid providers are later work.
- Research subagents get narrow task-specific tools. No shell or arbitrary local file access in the learner browser.
- Speculative artifacts/candidates need not survive an intentional new lesson. Promoted pages, referenced assets, and interruption-recovery state do.
- Single-tab use is accepted for the first supervised slice. The proof's Web Locks fencing is not considered real leader election.

### First-slice rendering and observation

The production board pane hosts a responsive canvas with stable previous/next controls outside generated content. Declarative page renderers compose text, simple equations, SVG, and image artifacts into that canvas. The designated child answer control is stable DOM, but its current text is also drawn into the visible canvas so observations include exactly what the learner sees.

This avoids both a server-side rerender that can diverge from the child and unreliable screenshots of sandboxed cross-origin iframes. The fox PNG comes directly from the visible canvas after rendering.

Later interactive HTML/map-SDK tools must either produce a vetted raster/SVG artifact for canvas composition or provide an equivalently faithful observation path. They are not a reason to weaken the first slice's actual-pixels guarantee.

## First-slice non-goals

- Autonomous visible changes without an outstanding fox intent.
- Continuous screen watching or camera/microphone observation beyond the existing voice call.
- Cross-device sync, accounts, parent dashboards, export/import UI, or migration of old production boards.
- A general purpose child drawing editor.
- Real multi-tab leader election.
- Embedding an interactive third-party map when a static sourced or generated map is sufficient.
- A broad tool marketplace. Add the bounded tools needed by the two scenarios while keeping the artifact model open to more.

## Acceptance evidence

The milestone is not complete from unit tests alone. It requires the real served app, real LiveKit fox, live models, and real browser:

1. Räven greets a returning learner using device-local prior context without loading an old page.
2. A voice-led maths exercise is prepared by the browser Screen and appears once at the correct page/revision.
3. Räven can use the private solution while the public pixels keep it hidden.
4. Child input survives local page navigation and browser reopen during an interrupted lesson, but reaches Räven only on explicit submission/discussion.
5. Current reveal succeeds; stale and duplicate reveals cannot affect another page or apply twice.
6. A geography request produces background research/artifacts and an invisible candidate; no subagent writes the visible deck.
7. The main Screen promotes the candidate, and Räven observes the actual visible map/page pixels before teaching from them.
8. A newer intent can supersede pending background work without leaving the voice loop blocked.
9. Intentional new lesson starts empty; interrupted lesson offers/resumes the correct local deck.
10. Desktop and phone layouts remain one-page-at-a-time with stable controls outside generated content.

Focused tests run during implementation; the full server and web suites plus the real browser scenarios run before handoff.

## Work log

- 2026-11-11: Product boundaries and first maths + geography slice agreed with Johan.
- 2026-11-11: Live base verified on ThinkCentre at `05c23a4`; fresh development branch created. No production deployment.
- 2026-11-11: Existing proof reviewed. Its fox is simulated and its observation runs in the same Screen Durable session; it proves live pixel vision, not yet two independent agents.
- 2026-11-11: Worker reconnaissance completed for LiveKit/UI integration, Pi Durable 1.5.2, and model/research gateways. Durable child conversations/background tasks/docs are API-native; binary assets require a separate browser blob store.
- 2026-11-11: Protocol v1 fixed around immediate RPC acceptance plus correlated asynchronous ready/observation streams. First production renderer chosen as a visible canvas to preserve actual-pixel observation.
- 2026-11-11: FastAPI model/research gateways and fox intent/observation tools integrated. Session metadata now carries a stable device-local lesson id. Capable fox prompts no longer contain legacy board-owner instructions.
- 2026-11-11: Real public geography probe returned a bounded 208 KB Wikimedia PNG with attribution after fixing thumbnail host/bucket handling. Gateway/session tests: 43 passed. Fox/web focused tests: 29 server + 14 web passed.

## Next

1. Finish live supersession and physical microphone checks. The browser sessions use typed input because microphone permission is unavailable.
2. Keep PR #25 in draft until the remaining checks pass. Production stays unchanged.

## Development verification, 2026-11-11

The development build runs on dell5500 at <https://dell5500.tail2e1c4e.ts.net:9444/>. Its services are `open-tutor-screen-dev-web.service` and `open-tutor-screen-dev-agent.service`. Production and `origin/main@05c23a4` are unchanged.

The latest real-browser run used the served build, a real LiveKit room, and the existing development fox. It verified:

- Reload restores the interrupted maths page and its typed draft from IndexedDB.
- The browser announces the restored page only after rendering. It queues the announcement until the fox advertises an active session state. A live run without that queue reproduced the fox reporting an empty screen despite a visible exercise.
- The restarted fox's `observe_screen` receives PNG bytes from the visible canvas and separate private teaching context. The screenshot keeps the solution hidden before reveal.
- Explicit submission sends `answer-submitted`; the fox receives the submitted answer and responds to it.
- The fox's `reveal_screen` reveals the restored page, receives another real pixel observation, and leaves the page id and revision intact.
- The 390 by 844 phone viewport shows the question, draft, revealed solution, and stable controls without overlapping the fox. Compact rendering reserves space for each section instead of clipping the question. This was a browser CSS viewport check, not a physical-phone test.
- After intentional **Avsluta**, starting the same learner's next lesson opens an empty workspace and hides the canvas.

Regression evidence: the restored-page test failed before the recovery change because no event was emitted. The 390 by 240 renderer test failed before the layout change because the question was omitted. Both pass after the fixes.

Validation commands from the final code tree:

```sh
cd web
npm test          # 136 passed
npm run build    # TypeScript and Vite pass
cd ../server
uv run --frozen pytest -q  # 175 passed
```

The build retains its existing Pi `node:fs` browser-externalization and bundle-size warnings. The development gateway records upstream quota failures as HTTP 502 responses containing `upstream error 429`, which currently triggers SDK retries before the fox's request times out.

## Development verification, 2026-11-12

Johan enabled extra OpenCode Go credits. Fresh maths generation succeeded through the served app, real fox `show_screen`, browser model, candidate promotion, canvas rendering, and PNG observation. A draft answer survived navigation to the geography page and back without being submitted.

Fresh geography also completed through a Durable child, the geography gateway, candidate promotion, and the real fox's PNG observation. The child chose a generated SVG map. Visual inspection caught a small-map layout and clipped body text, while the observation record incorrectly included the full body. The fix gives geography a dedicated responsive layout and derives public observation text from actual canvas draw calls. The revised desktop page was inspected on the served app. Complete post-fix fox observation remains pending the voice-service issue below.

Direct research with a concise `France` query exposed unrelated photos being returned as map candidates. The gateway now searches for maps and accepts safe raster thumbnails of SVG maps. A real request returned a Wikimedia France map. The Screen now chooses a concise geographic search term rather than sending the entire teaching request as a search query.

The first Muse review proved three bugs on `ce8e86b`: visuals could evict a short-canvas question, local preparation errors left shows waiting until timeout, and a shared candidate completed only the first matching show. Regression checks now cover each case. Internal auto-prepare outcomes remain off the external event stream, and one promotion can satisfy several matching shows.

The quiet recovery notification is now an explicit `page-changed` event. It also covers child navigation and homework intake after rendering, so the fox does not retain an old page identity. A targeted fox test verifies that this event changes the default observation target without adding a chat turn.

Validation on the latest source: 146 web tests, 177 server tests, TypeScript, and the Vite build pass. Full voice acceptance remains blocked by Cartesia, not OpenCode Go: one direct raw vendor response returned HTTP 402 with insufficient credits and no audio. An earlier timestamp explanation was incomplete; disabling timestamps did not restore audio, and that unrelated code change was removed. No credits were purchased and no speech provider was switched.

Johan subsequently authorized Deepgram's `flux-ludvig-sv` voice with `expressivity=1` instead of Cartesia. The existing development environment receives `DEEPGRAM_API_KEY` from Infisical. Integration and live audio verification are in progress; production is unchanged.

The final cross-family Screen review found no proven blockers. It reran the 90 Screen web checks, 60 Screen server checks, and TypeScript. It confirmed the rendering, observation, page notification, preparation failure, and concurrent-show fixes. This review excludes the later Deepgram integration.

Deepgram integration is now complete in development. The Muse implementation was reviewed by the Sol lead against the installed plugin. Thirteen focused tests verify the chosen voice, expressivity on the wire, audio transport, and vendor error propagation. The full server suite passes 190 tests.

A real configured streaming probe produced non-empty audio. In the served browser, the fox greeting had a live audio track, advancing playback, a non-silent incoming signal, and captions. Session metadata identifies `Deepgram` and `flux-ludvig-sv`. A subsequent live geography request completed through the Screen worker and fox pixel observation using the revised drawn-text record. The learner's unsubmitted maths draft survived navigation across all three pages. The child microphone remains unverified.

After the child navigated back to maths, the real fox's default `observe_screen` selected the correct restored exercise and received its actual 894 by 501 canvas observation. Its `reveal_screen` then revealed that page's solution and received another pixel observation. Hidden and revealed public text matched the corresponding canvas state.

Johan also supplied a local VoxCPM2 endpoint for fallback or pre-rendering. Its health endpoint was checked from dell5500 and returned healthy and idle. Use `warm-voice-v2` explicitly; the reported default is the English v1 anchor. The HTTP interface, PCM format, single-request limit, and GPU constraints are recorded in [the server README](../server/README.md#local-speech-for-pre-rendering). Deepgram remains the live voice path; automatic fallback and a VoxCPM2 LiveKit adapter are not implemented.

Johan then authorized replacing the legacy Gemini development fox with Muse Spark 1.3 Contributor through the OpenCode Go subscription. The running development configuration now selects `TUTOR_LLM=go` and `TUTOR_LLM_MODEL=muse-spark-1.3-contributor`, using Responses API and default minimal reasoning. A real browser session verified Muse calling `show_screen`, receiving the new exercise's PNG and private solution while keeping the public answer hidden, and speaking its follow-up through Deepgram. The Screen's own DeepSeek model is unchanged. Production is unchanged.

Johan also supplied ZONOS3-Mini on johan-4070 port 8448 as a second local speech endpoint. A read-only speaker discovery check returned `raeven sv` and `warm en`, both with embedding mode. Its voice requirement, embedding-mode requirement, WAV format, and CPU-only operating constraint are documented in [the server README](../server/README.md#zonos3-mini-alternative). No automatic fallback, synthesis request, or live voice switch was added.

On 2026-11-12, Johan authorized enabling LiveKit adaptive interruption handling in development. `TUTOR_ADAPTIVE_INTERRUPTION=1` now selects the hosted classifier on `open-tutor-screen-dev-agent.service`; the application default remains VAD-only. Soniox, Muse, Deepgram, and the endpointing delays are unchanged. A fictional learner joined through the served development API and sent prerecorded Swedish speech over the fox's greeting. The session recorded 12 classifier requests and an adaptive interruption decision, received voiced tutor audio, and logged no fallback to VAD. This confirms live integration, not Swedish child or backchannel accuracy. Temporary diagnostic logging was restored to its previous settings. All 190 server tests pass. The SDK falls back to VAD if inference fails or the monthly allowance runs out. Production is unchanged.

A third local endpoint is available on pc2014 port 8448, running ZONOS3-Mini on CPU with the same API and speaker ids. A read-only discovery request confirmed both expected embedding voices. It can replace the johan-4070 ZONOS3 base URL without changing the payload. Johan subsequently validated correct Swedish with Vulkan on its RX 6500 XT, but ruled out GPU hosting: existing tenants plus ZONOS3 reach 98% of the card's 4 GiB VRAM. The managed service stays on CPU on internal port 1919; the Vulkan build is retained for reconsideration after VRAM becomes available. See the [hosting constraints](../server/README.md#zonos3-mini-alternative) for details.

Johan subsequently authorized using pc2014 ZONOS3 as the fox's active speech provider. A batch LiveKit adapter now posts each sentence with the explicit Swedish voice and embedding mode, validates PCM16 mono 44.1 kHz WAV, and sends decoded PCM to LiveKit. The framework's sentence adapter bridges streamed LLM text and cancellation. A real endpoint request, the configured LiveKit provider probe, and non-silent browser playback with captions all passed. Runtime logs confirm Muse Spark 1.3 Contributor through Go plus ZONOS3 speech. The full server suite passes 218 tests, including 28 focused ZONOS3 checks. Deepgram remains selectable; automatic provider failover is not implemented. Production is unchanged.

Development session logging is now enabled at Johan's request for experience iteration before merging. The worker's private environment sets `TUTOR_DEBUG_LOG=1` and stores session timelines and reports under `/home/johan/.local/state/open-tutor-screen-dev/sessions` on dell5500. A fictional learner connected through the served development API and LiveKit; its log captured the fox greeting, a typed learner request, the fox's response, and the disconnect, then wrote `report.json` with outcome `child_left`. Both files have mode 0600. Cloud audio recording stays off. Logging applies to new sessions and cannot recover earlier conversations; main and production are unchanged.

Latest pc2014 operator handoff supersedes the earlier CPU-only verdict: competing GPU services were stopped and disabled with Johan's approval, and the same port-8448 endpoint now serves ZONOS3 through Vulkan with about 2.6 GB VRAM headroom. Johan reports correct Swedish, about 2.9× realtime solo, and eight successful simultaneous requests with 6–12 second latency each. This thread did not repeat those measurements. The operator recommends bulk/pre-render/fallback use; the development app still selects ZONOS3 while the live-provider choice is clarified. No application configuration or production change was made for this handoff.
