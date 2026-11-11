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
  accessCode: "familjekod",      // in-memory only, sent as x-tutor-code, never stored
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

`setAnswerDraft` throws `unknown-page-revision` for stale targets.
`submitAnswer` throws `stale-page` unless the target is the current visible
page, and is the **only** path that shares child input (as
`answer-submitted`). `captureObservation` throws `stale-observation`,
`observation-busy` (overlapping observation) or `no-canvas`.

## Render / ready flow

`ready` means *committed **and** rendered* — never commit alone:

1. `prepare` never changes pixels: `ready` fires when the invisible candidate
   is committed. The visible deck is untouched. A prepare whose candidate was
   superseded by a newer intent settles as `rejected` (`superseded`) instead
   of hanging.
2. `show` / `reveal` change pixels: the controller commits, persists, emits
   `onDeckChange`, then renders the promoted page+revision and only afterwards
   emits `ready` for that page+revision. A `show` with no ready candidate is
   held as an *outstanding request* (accepted, no event yet); when a matching
   candidate arrives it promotes without a second request, otherwise the hold
   lapses into `rejected` after `outstandingShowTimeoutMs`.
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
     fabricated.
4. `captureObservation` reads the attached canvas (`toDataURL("image/png")`)
   or the injected `pixelReader`, and returns `{ pngBase64, context }`. The
   PNG is transient and never written to any store.

## Canvas rendering

```ts
import { renderScreenPage, resolveScreenAssets } from "./screen/index.ts";

const assets = await resolveScreenAssets(page, blobStore, draftText, "Sida 1 av 2");
renderScreenPage(canvas, page, assets);
```

One page at a time, Swedish labels, dark-UI friendly. Draws subject chip,
title, wrapped body lines, one visual (researched image, cover-fit, or a
deterministic map placeholder while a generated SVG awaits preloading),
child answer box, hidden (`🔒 Facit är dolt`) vs revealed solution, and a
footer with sources plus stable `pageId revision` metadata. No arbitrary
iframe HTML; `sanitizeSvg()` strips scripts/event-handlers/iframes from
generated SVG at candidate commit time. `drawScreenPage(ctx, size, page,
assets)` is the testable core; `wrapText` is exported for tests.

## Agents, tools and background work

- Main Screen model: `deepseek-v4.1-flash` through the same-origin
  OpenAI-compatible gateway `/api/screen/openai/{room}/chat/completions`
  (`postScreenChat`: family code as Bearer apiKey in worker memory only,
  `cache: "no-store"`, `max_tokens` clamped to 8192, model pinned —
  mirroring the proven proof-proxy pattern). The provider key stays
  server-side; nothing persists.
- Narrow worker tools: `prepare_exercise`, `propose_geography`,
  `record_artifact`, `fetch_geography`, `request_geography_research`. No
  shell, no files. Subagents may create artifacts/candidates but never
  visible pages — promotion is main-thread only.
- Geography research runs in a Durable-native **background child
  conversation** (`Harness.createConversation` with `ownerless` ownership,
  spawned by `request_geography_research`; the main turn returns
  immediately). The child calls the bounded gateway
  (`fetchGeographyResearch` → `GET /api/screen/research/geography`, provenance
  required) and proposes the candidate. The Screen chooses the medium:
  `selectGeographyVisual` prefers a researched image URL when the gateway
  returns one, otherwise a generated SVG; researched bytes are downloaded,
  sniff-checked, hashed and stored in the blob store by the main thread
  (docs/records carry only the `ScreenAssetRef`).
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
`ScreenPage` / `CandidatePage`, `ScreenArtifact`, `ScreenAssetRef`,
`ScreenDeckSnapshot`, `LessonSummary`, `ScreenObservationRequest` /
`ScreenObservationContext` / `ScreenObservationResult`, plus worker
(`MainToScreenWorker`, `ScreenWorkerToMain`, `ScreenWorkerPort`) and store
(`ScreenStore`, `ScreenBlobStore`, `ResearchRunner`, `SupersessionGate`)
shapes — all in `index.ts` via `types.ts` and siblings.
