# Screen core — API

Browser-owned visual workspace for Open Tutor (`web/src/screen/`).
Public entry: `web/src/screen/index.ts`. The lead owns React/LiveKit
integration (`screen.intent` / `screen.observe` RPCs, `screen-event` /
`screen-pixels` / `screen-context` streams); this module owns the deck,
drafts, candidates, render/ready gating and observation capture.

Pinned runtime: `@earendil-works/pi-durable`, `@earendil-works/pi-ai`,
`@earendil-works/pi-schema`, `@earendil-works/chord`, all at **1.5.2**
(see `web/package.json`). The Harness lives in the module Web Worker
`screen.worker.ts`; the page owns the pixels.

## Controller

```ts
import { createScreenController } from "./screen/index.ts";

const screen = createScreenController({
  profileId: "profil-123",      // per-profile DB: open-tutor-screen[-blobs]-*
  learnerName: "Alicia",
  grade: "åk 3",                // optional
  priorNotes: [{ text: "Gillar rymden" }], // device-local, newest last
  room: "abc123",               // random LiveKit room id (upstream scoping)
  accessCode: "familjekod",      // in-memory only, sent as x-tutor-code, never stored ("" in public Swedish mode)
  lessonId: "lektion-1",
  viewport: { w: 1280, h: 800, device: "desktop" }, // default shown
  onDeckChange: (snapshot) => render(snapshot),    // optional
  onScreenEvent: (event) => sendToFox(event),      // optional
  createWorker: () => myPort | null,  // default: real Pi worker; null = local-only
  prepareHandler: async (intent, seq) => candidate | null, // explicit authoring seam
  researchRunner: { startGeographyResearch },       // local-only geography seam
  renderPage: async (canvas, page, { draftText, pageLabel }) => { … }, // default built in
  pixelReader: async () => dataUrl,   // observation seam when no canvas attached
  store, blobStore,                   // persistence seams (defaults: IndexedDB + memory fallback)
  now: () => Date.now(), newId: (prefix) => string, // determinism seams
  renderAckTimeoutMs: 8000,           // held show/reveal ready → `failed` after this (0 = hold)
  outstandingShowTimeoutMs: 60000,    // held show with no candidate → `rejected` after this
});

await screen.init(): ScreenDeckSnapshot
await screen.handleIntent(intent: ScreenIntent): ScreenIntentAck
await screen.captureObservation(req: ScreenObservationRequest): ScreenObservationResult
await screen.setAnswerDraft(pageId: string, revision: string, text: string): Promise<void>
await screen.submitAnswer(pageId: string, revision: string): Promise<void>
screen.goTo(index: number): Promise<void>
await screen.addHomeworkPage(input: AddHomeworkPageInput): ScreenDeckSnapshot
await screen.startNewLesson(lessonId: string): ScreenDeckSnapshot
screen.getSnapshot(): ScreenDeckSnapshot
screen.attachCanvas(canvas: HTMLCanvasElement | null): void
screen.notifyRendered(pageId: string, revision: string): void
await screen.close(): Promise<void>
```

`handleIntent` returns **immediately** (never waits for model work, rendering
or assets):

- `{ accepted: true, intentId }` — the intent is admitted; the correlated
  `ready` / `rejected` / `failed` event arrives later on `onScreenEvent`.
- `{ accepted: false, intentId, reason }` — validation or lesson rejection
  (`lesson-mismatch`, `reveal-needs-target`, `unknown-op:…`, `closed`).
- A duplicate `intentId` replays the stored outcome (event re-emitted, never
  executed twice). A duplicate `reveal` on an already-revealed page returns
  the already-ready outcome without another deck mutation.

`addHomeworkPage({ title, text?, images? })` is the lead-owned child homework
intake (MAIN controller only — never a subagent/worker path). The child's
explicit upload authorises immediate visibility: image bytes are stored as
artifact blobs (`ScreenBlobStore.put` + `verifyBlobBytes` + `validateAssetRef`
/ `isAssetRefUsable` lesson scoping), then durable `homework` page(s) commit
directly to the visible deck — one page per image, or a single text-only page
when `images` is empty. The latest page becomes current; the deck persists
(`store.saveDeck`), publishes (`onDeckChange`) and re-renders. Homework pages
are ordinary visible pages (`id` / `revision` / `lessonId` / provenance, kind
`"homework"`, subject `"Läxa"`, empty `solution`), never model candidates, and
never emit a fox `ready` or `answer-submitted` event. Validation errors throw
(`homework-title-required`, `homework-needs-content`, `blob-too-large`,
`mime-mismatch`, `homework-asset-invalid`, …) with the deck unchanged. New
lessons archive homework titles via `startNewLesson`; reopening the same lesson
resumes them via `shouldResumeDeck`.

`setAnswerDraft` throws `unknown-page-revision` for stale targets.
`submitAnswer` throws `stale-page` unless the target is the current visible
page, and is the **only** path that shares child input (as
`answer-submitted`). `captureObservation` throws `lesson-mismatch`
(stale lesson), `stale-observation`, `observation-busy` (overlapping
observation) or `no-canvas`.

## Render / ready flow

`ready` means *committed **and** rendered* — never commit alone:

1. `prepare` never changes pixels: `ready` fires when the invisible candidate
   is committed. The visible deck is untouched. A prepare whose candidate was
   superseded by a newer intent settles as `rejected` (`superseded`) instead
   of hanging. Prepare-only work stays invisible by design.
2. `show` / `reveal` change pixels: the controller commits, persists, emits
   `onDeckChange`, then renders the promoted page+revision and only afterwards
   emits `ready` for that page+revision. A `show` with no ready candidate is
   held as an *outstanding request* **and starts preparation itself using
   that show intent** (synthetic `<showId>:auto-prepare` sharing the show's
   need): the hold never waits 60s for work that was never started. When the
   matching candidate arrives it auto-promotes without a second request,
   otherwise the hold lapses into `rejected` after
   `outstandingShowTimeoutMs`. The controller tracks op per intent: only
   `prepare` settles `ready` at invisible commit, while a `show` settles
   exactly once after promote+render (never at commit, never twice).
3. Rendering target, in order:
   - attached canvas (`attachCanvas`): the controller renders itself via
     `renderPage` (default: `resolveScreenAssets` → `renderScreenPage`), which
     awaits image/SVG asset resolution. Navigation and drafts re-render
     silently through the same path.
   - no canvas (lead-owned external renderer): the controller holds `ready`
     until the lead calls `notifyRendered(pageId, revision)` after the page
     has actually painted. Duplicate reveals consult the render ledger, so a
     re-notified page resolves immediately.
   - render errors (or `renderAckTimeoutMs` lapsing) settle the intent as
     `failed` (`render-failed` / `render-timeout`) — a `ready` is never
     fabricated. A real canvas without a 2d context throws (`no-2d-context`)
     instead of faking success.
4. `captureObservation` reads the attached canvas (`toDataURL("image/png")`)
   or the injected `pixelReader`, and returns `{ pngBase64, context }`. The
   PNG is transient and never written to any store. The request carries
   `lessonId` (stale lessons rejected as `lesson-mismatch`); the context
   carries `lessonId`, `visibleText` (solution only when revealed),
   `viewport { w, h, device }`, `sources` and `privateTeaching`.

## Canvas rendering

```ts
import { renderScreenPage, resolveScreenAssets } from "./screen/index.ts";

const assets = await resolveScreenAssets(page, blobStore, draftText, "Sida 1 av 2");
renderScreenPage(canvas, page, assets);
```

Homework pages (`kind: "homework"`) show the uploaded image contain-fit with
`Bild: <attribution>` and expanded body text, never a permanent loading
placeholder; the exercise answer box and hidden facit are omitted and the freed
space is content. Other page kinds are unchanged.

One page at a time, Swedish labels, dark-UI friendly. Draws subject chip,
title, wrapped body lines, one visual (researched image contain-fit, rasterised
generated SVG, or a deterministic map placeholder only while neither drawable
exists), child answer box, hidden (`🔒 Facit är dolt`) vs revealed solution,
and a footer with sources plus stable `pageId revision` metadata. No arbitrary
iframe HTML; `sanitizeSvg()` strips scripts/event-handlers/iframes from
generated SVG at candidate commit time. Map images use contain-fit
(letterboxed, never cropped). `drawScreenPage(ctx, size, page, assets)` is the
testable core; `wrapText`, `drawContain`/`drawCover` and `decodeSvgDrawable`
are exported for tests.

## Agents, tools and background work

- Main Screen model: `deepseek-v4.1-flash` through the same-origin
  OpenAI-compatible gateway `/api/screen/openai/{room}/chat/completions`
  (`postScreenChat`: family code as Bearer apiKey in worker memory only,
  `cache: "no-store"`, `max_tokens` clamped to 8192, model pinned —
  mirroring the proven proof-proxy pattern). The provider key stays
  server-side; nothing persists.
- Same-origin gateway clients (`postScreenChat`, `fetchGeographyResearch`, worker `fetch_geography`) work with an empty access code in the existing Swedish public mode: `TUTOR_ACCESS_CODE` may be empty, the backend `family_authorized()` permits it, and the clients never require a non-empty credential.
- Narrow worker tools: `prepare_exercise`, `propose_geography`,
  `record_artifact`, `fetch_geography`, `request_geography_research`. No
  shell, no files. Subagents may create artifact blobs/candidates but never
  visible pages — promotion is main-thread only.
- Worker prepare messages are queued on both sides of boot: the controller
  holds `prepare` posts until `harness-ready`, and the worker awaits its
  boot promise before touching `rootHandle` — no `rootHandle`-null race.
- Geography research runs in a Durable-native **background child
  conversation** (`Harness.createConversation` with `ownerless` ownership,
  spawned by `request_geography_research`; the main turn returns
  immediately). The child calls the bounded gateway
  (`POST /api/screen/research/geography` JSON `{ query }` → JSON
  `{ query, place, maps: [{ dataUrl, mime, bytes, sourceUrl, retrievedAt,
  attribution, license }], retrievedAt }`) and proposes the candidate. The
  worker `fetch_geography` tool parses/validates maps, decodes bytes, stores
  them in the per-profile blob store as artifact assets, records concise
  provenance, and returns only concise place + map assetIds/metadata to the
  model — never base64. `propose_geography` accepts a chosen `assetId` and
  constructs the candidate with a validated `ScreenAssetRef` plus source
  attribution; generated-SVG remains as fallback. `selectGeographyVisual`
  prefers a researched map when one exists, otherwise generated SVG.
  `ingestCandidate` accepts/verifies a raw `candidate.asset` (hash + blob
  lookup + lesson scope) instead of discarding it; the legacy `researchImage`
  URL download path is retained only for compatibility, while the real path
  needs no external browser download (docs/records carry only the ref).
- Stale background results are fenced twice: the worker checks the
  `screen.control` doc (`latestByNeed`) before proposing, and the controller
  re-checks its `SupersessionGate` on ingest — newer intents supersede older
  background work, and superseded candidates can never promote.
- Tested seams (no faking): `prepareHandler` and `ResearchRunner` inject
  candidate production when the worker is absent; `renderPage`,
  `pixelReader`, `store`, `blobStore`, `now`/`newId` inject rendering,
  pixels, persistence and determinism. Local-only mode prepares honestly
  fail (`screen-unavailable`) instead of fabricating pages.

## Types

`ScreenIntent`, `ScreenIntentAck`, `ScreenOutboundEvent`,
`ScreenPage` / `CandidatePage` (`ScreenPageKind` now includes `"homework"`),
`AddHomeworkPageInput` / `HomeworkImageInput`, `ScreenArtifact`, `ScreenAssetRef`,
`ScreenDeckSnapshot`, `LessonSummary`, `ScreenObservationRequest` /
`ScreenObservationContext` / `ScreenObservationResult`, plus worker
(`MainToScreenWorker`, `ScreenWorkerToMain`, `ScreenWorkerPort`) and store
(`ScreenStore`, `ScreenBlobStore`, `ResearchRunner`, `SupersessionGate`)
shapes — all in `index.ts` via `types.ts` and siblings.
