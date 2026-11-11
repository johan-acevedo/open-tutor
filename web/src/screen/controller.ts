/**
 * Main-thread Screen controller.
 *
 * Owns the visible deck, intent registry, candidate store, child drafts and
 * the render/ready pipeline. The Pi Harness (when available) lives in a
 * module Web Worker and only proposes invisible candidates; every commit to
 * the visible deck goes through the pure functions in `deck.ts`.
 *
 * Render/ready contract (see `API.md`):
 * - `prepare` never changes pixels: `ready` means the invisible candidate
 *   is committed.
 * - `show` / `reveal` change pixels: `ready` is emitted only after the
 *   promoted page+revision has actually rendered — either by the
 *   controller into the attached canvas, or by the lead's external renderer
 *   confirmed via `notifyRendered`. `ready` is never emitted at commit time.
 * - `captureObservation` reads the attached canvas (or an injected pixel
 *   reader in tests) and never persists the PNG.
 */
import {
  addCandidate,
  applyDraft,
  applyReveal,
  createEmptyDeck,
  currentPage,
  draftKey,
  findPromotionCandidate,
  getIntentOutcome,
  goToIndex,
  needKey,
  promoteCandidate,
  readDraft,
  registerIntent,
  settleIntent,
  shouldResumeDeck,
  startNewLesson as startNewLessonDeck,
  type CandidateStore,
  type IntentOutcome,
  type IntentRegistry,
} from "./deck";
import {
  createBlobStore,
  isAssetRefUsable,
  MAX_BLOB_BYTES,
  sniffMimeType,
  validateAssetRef,
  verifyBlobBytes,
  type ScreenBlobStore,
} from "./assets";
import type { ResearchBundle, ResearchRunner } from "./childTasks";
import { createSupersessionGate, type SupersessionGate } from "./childTasks";
import { buildObservationContext, validateObservationRequest } from "./observation";
import {
  createIndexedDbScreenStore,
  type ScreenStore,
} from "./persistence";
import { downloadAssetBytes } from "./research";
import { renderScreenPage, resolveScreenAssets, sanitizeSvg } from "./renderer";
import type {
  AddHomeworkPageInput,
  CandidatePage,
  LessonSummary,
  PriorNote,
  ScreenAssetRef,
  ScreenDeckSnapshot,
  ScreenEventType,
  ScreenIntent,
  ScreenIntentAck,
  ScreenObservationContext,
  ScreenObservationRequest,
  ScreenObservationResult,
  ScreenOutboundEvent,
  ScreenPage,
  ScreenViewport,
} from "./types";
import {
  createPiScreenWorker,
  type ScreenWorkerPort,
  type ScreenWorkerToMain,
} from "./worker-protocol";

export type ScreenRenderPageFn = (
  canvas: HTMLCanvasElement,
  page: ScreenPage,
  opts: { draftText: string; pageLabel: string },
) => Promise<void>;

export type PrepareHandler = (
  intent: ScreenIntent,
  seq: number,
) => Promise<Omit<CandidatePage, "status" | "receivedAt"> | null>;

export interface ScreenControllerOptions {
  profileId: string;
  learnerName: string;
  grade?: string;
  priorNotes: PriorNote[];
  room: string;
  accessCode: string;
  lessonId: string;
  viewport?: ScreenViewport;
  onDeckChange?: (snapshot: ScreenDeckSnapshot) => void;
  onScreenEvent?: (event: ScreenOutboundEvent) => void;
  /** Defaults to the real Pi Harness worker; return null for local-only mode. */
  createWorker?: () => ScreenWorkerPort | null;
  /** Explicit authoring seam (tests, local-only prepare). Runs before worker. */
  prepareHandler?: PrepareHandler;
  /** Background geography research for the local-only path. Runs when no worker. */
  researchRunner?: ResearchRunner;
  /** Render seam; defaults to resolveScreenAssets + renderScreenPage. */
  renderPage?: ScreenRenderPageFn;
  /** Pixel seam for tests without a real canvas. */
  pixelReader?: () => string | Promise<string>;
  store?: ScreenStore;
  blobStore?: ScreenBlobStore;
  now?: () => number;
  newId?: (prefix: string) => string;
  /** Held show/reveal `ready` waits for render proof; timeout emits `failed`. */
  renderAckTimeoutMs?: number;
  /** Outstanding `show` with no ready candidate waits this long, then `rejected`. */
  outstandingShowTimeoutMs?: number;
}

export interface ScreenController {
  init(): Promise<ScreenDeckSnapshot>;
  handleIntent(intent: ScreenIntent): Promise<ScreenIntentAck>;
  captureObservation(request: ScreenObservationRequest): Promise<ScreenObservationResult>;
  setAnswerDraft(pageId: string, revision: string, text: string): Promise<void>;
  submitAnswer(pageId: string, revision: string): Promise<void>;
  goTo(index: number): Promise<void>;
  /**
   * Child homework intake (lead-owned, MAIN controller only).
   *
   * The child's explicit upload authorises immediate visibility: stores
   * image bytes as artifact blobs, creates durable `homework` page(s)
   * (one per image, or a single text-only page), appends them to the
   * visible deck, selects the latest, persists/publishes and renders.
   * Ordinary visible pages — never model candidates, never a fox `ready`
   * or `answer-submitted` event.
   */
  addHomeworkPage(input: AddHomeworkPageInput): Promise<ScreenDeckSnapshot>;
  startNewLesson(lessonId: string): Promise<ScreenDeckSnapshot>;
  getSnapshot(): ScreenDeckSnapshot;
  attachCanvas(canvas: HTMLCanvasElement | null): void;
  notifyRendered(pageId: string, revision: string): void;
  close(): Promise<void>;
}

interface PendingRender {
  intentId: string;
  pageId: string;
  revision: string;
  timer: ReturnType<typeof setTimeout> | null;
}

interface OutstandingShow {
  intentId: string;
  lessonId: string;
  need: string;
  needText?: string;
  backgroundText?: string;
  /** Synthetic prepare intent spawned by this show (show-starts-prepare). */
  prepIntentId?: string;
  timer: ReturnType<typeof setTimeout>;
}

const DEFAULT_RENDER_ACK_TIMEOUT_MS = 8000;
const DEFAULT_OUTSTANDING_SHOW_TIMEOUT_MS = 60_000;

function eventForOutcome(
  type: ScreenEventType,
  intentId: string | undefined,
  lessonId: string,
  outcome: IntentOutcome,
): ScreenOutboundEvent | null {
  if (outcome.status === "pending") return null;
  if (outcome.status === "ready") {
    return { type, intentId, lessonId, page: outcome.page };
  }
  return { type, intentId, lessonId, reason: outcome.reason };
}

export function createScreenController(options: ScreenControllerOptions): ScreenController {
  const now = options.now ?? Date.now;
  const newId =
    options.newId ??
    ((prefix: string) => `${prefix}${Date.now().toString(36)}${Math.floor(Math.random() * 0xffff).toString(36)}`);
  const store = options.store ?? createIndexedDbScreenStore();
  const blobStore = options.blobStore ?? createBlobStore(options.profileId);
  const viewport = options.viewport ?? { w: 1280, h: 800, device: "desktop" };
  const renderAckTimeoutMs = options.renderAckTimeoutMs ?? DEFAULT_RENDER_ACK_TIMEOUT_MS;
  const outstandingShowTimeoutMs = options.outstandingShowTimeoutMs ?? DEFAULT_OUTSTANDING_SHOW_TIMEOUT_MS;
  const renderPageFn: ScreenRenderPageFn =
    options.renderPage ??
    (async (canvas, page, opts) => {
      const assets = await resolveScreenAssets(page, blobStore, opts.draftText, opts.pageLabel);
      renderScreenPage(canvas, page, assets);
    });

  let deck: ScreenDeckSnapshot = createEmptyDeck(options.profileId, options.lessonId, now());
  let lessonId = options.lessonId;
  const registry: IntentRegistry = new Map();
  const lastEventByIntent = new Map<string, ScreenOutboundEvent>();
  const needByIntent = new Map<string, string>();
  const opByIntent = new Map<string, ScreenIntent["op"]>();
  const candidates: CandidateStore = new Map();
  const gate: SupersessionGate = createSupersessionGate();
  const pendingRenders: PendingRender[] = [];
  const outstandingShows: OutstandingShow[] = [];
  let renderSeq = 0;
  let lastRendered: { pageId: string; revision: string } | null = null;
  let canvas: HTMLCanvasElement | null = null;
  let worker: ScreenWorkerPort | null = null;
  let workerFailed = false;
  let harnessReady = false;
  const queuedPrepares: Array<{ intent: ScreenIntent; seq: number }> = [];
  let inFlightObservations = new Map<string, Promise<ScreenObservationResult>>();
  let closed = false;
  let initialized = false;
  let resumePage: { id: string; revision: string } | null = null;

  function announceRestoredPage(pageId: string, revision: string): void {
    const visible = currentPage(deck);
    if (closed || visible?.id !== pageId || visible.revision !== revision ||
        !resumePage || resumePage.id !== pageId || resumePage.revision !== revision) return;
    resumePage = null;
    // There is no waiting fox intent behind this event. The fox's tracker uses
    // it to learn the current page/revision after a tutor restart.
    emit({ type: "ready", intentId: `resume-${lessonId}`, lessonId, page: { id: pageId, revision } });
  }

  function emit(event: ScreenOutboundEvent): void {
    if (event.intentId) lastEventByIntent.set(event.intentId, event);
    try {
      options.onScreenEvent?.(event);
    } catch {
      // Listener errors must not break the deck pipeline.
    }
  }

  function publish(): void {
    try {
      options.onDeckChange?.(deck);
    } catch {
      // ignore listener errors
    }
  }

  async function persist(): Promise<void> {
    try {
      await store.saveDeck(deck);
    } catch {
      // Local persistence is best-effort; the in-memory deck stays authoritative.
    }
  }

  function settle(intentId: string, lesson: string, outcome: IntentOutcome): void {
    settleIntent(registry, intentId, outcome);
    const type: ScreenEventType =
      outcome.status === "ready" ? "ready" : outcome.status === "rejected" ? "rejected" : "failed";
    if (outcome.status === "pending") return;
    const event = eventForOutcome(type, intentId, lesson, outcome);
    if (event) emit(event);
  }

  function pageLabel(): string {
    if (deck.pages.length === 0) return "";
    return `Sida ${deck.current + 1} av ${deck.pages.length}`;
  }

  function scheduleRender(intentId: string, pageId: string, revision: string): void {
    const pending: PendingRender = { intentId, pageId, revision, timer: null };
    pendingRenders.push(pending);
    if (renderAckTimeoutMs > 0) {
      pending.timer = setTimeout(() => {
        const index = pendingRenders.indexOf(pending);
        if (index === -1) return;
        pendingRenders.splice(index, 1);
        settle(intentId, lessonId, { status: "failed", reason: "render-timeout" });
      }, renderAckTimeoutMs);
    }
    void pumpRender();
  }

  function completeRender(pending: PendingRender): void {
    const index = pendingRenders.indexOf(pending);
    if (index === -1) return;
    pendingRenders.splice(index, 1);
    if (pending.timer) clearTimeout(pending.timer);
    lastRendered = { pageId: pending.pageId, revision: pending.revision };
    settle(pending.intentId, lessonId, {
      status: "ready",
      page: { id: pending.pageId, revision: pending.revision },
    });
  }

  /**
   * Render pipeline. With an attached canvas the controller renders the
   * current page itself and completes every pending ready that waits for
   * it. Without a canvas (lead-owned external renderer) pendings wait for
   * `notifyRendered`. Silent refreshes (navigation, drafts) reuse the same
   * path but never settle intent outcomes.
   */
  async function pumpRender(): Promise<void> {
    if (!canvas) return; // external renderer path: wait for notifyRendered
    const target = currentPage(deck);
    if (!target) return;
    const my = ++renderSeq;
    const relevant = pendingRenders.some((p) => p.pageId === target.id && p.revision === target.revision);
    try {
      const draft = readDraft(deck, target.id, target.revision);
      await renderPageFn(canvas, target, { draftText: draft, pageLabel: pageLabel() });
    } catch {
      if (my !== renderSeq || !relevant) return; // superseded, or silent path
      const stuck = pendingRenders.filter((p) => p.pageId === target.id && p.revision === target.revision);
      for (const pending of stuck) {
        const index = pendingRenders.indexOf(pending);
        if (index !== -1) pendingRenders.splice(index, 1);
        if (pending.timer) clearTimeout(pending.timer);
        settle(pending.intentId, lessonId, { status: "failed", reason: "render-failed" });
      }
      return;
    }
    if (my !== renderSeq) return; // a newer render won; it completes the pendings
    lastRendered = { pageId: target.id, revision: target.revision };
    announceRestoredPage(target.id, target.revision);
    if (!relevant) return;
    for (const pending of pendingRenders.filter((p) => p.pageId === target.id && p.revision === target.revision)) {
      completeRender(pending);
    }
  }

  /** Re-render the current page when pixels change without an intent event. */
  function refreshPixels(): void {
    if (!canvas) return;
    void pumpRender();
  }

  function attachCanvas(next: HTMLCanvasElement | null): void {
    canvas = next;
    if (canvas && deck.pages.length > 0) refreshPixels();
  }

  function notifyRendered(pageId: string, revision: string): void {
    lastRendered = { pageId, revision };
    announceRestoredPage(pageId, revision);
    for (const pending of pendingRenders.filter((p) => p.pageId === pageId && p.revision === revision)) {
      completeRender(pending);
    }
  }

  function flushQueuedPrepares(): void {
    if (!worker || workerFailed || !harnessReady) return;
    const pending = queuedPrepares.splice(0, queuedPrepares.length);
    for (const item of pending) {
      try {
        worker.post({ kind: "prepare", intent: item.intent, seq: item.seq });
      } catch {
        workerFailed = true;
        worker = null;
        queuedPrepares.unshift(item);
        break;
      }
    }
  }

  function ensureWorker(): void {
    if (worker || workerFailed || closed) return;
    const factory = options.createWorker ?? createPiScreenWorker;
    let port: ScreenWorkerPort | null = null;
    try {
      port = factory();
    } catch {
      port = null;
    }
    if (!port) return;
    worker = port;
    worker.onmessage = (message) => {
      void handleWorkerMessage(message);
    };
    workerFailed = false;
    harnessReady = false;
    try {
      worker.post({
        kind: "init",
        init: {
          profileId: options.profileId,
          room: options.room,
          lessonId,
          learnerName: options.learnerName,
          grade: options.grade,
          priorNotes: options.priorNotes,
          accessCode: options.accessCode,
        },
      });
    } catch {
      workerFailed = true;
      worker = null;
    }
  }

  async function handleWorkerMessage(message: ScreenWorkerToMain): Promise<void> {
    if (message.kind === "harness-ready") {
      harnessReady = true;
      flushQueuedPrepares();
      return;
    }
    if (message.kind === "worker-log") return;
    if (message.kind === "worker-failed") {
      if (message.intentId && getIntentOutcome(registry, message.intentId)?.status === "pending") {
        settle(message.intentId, lessonId, { status: "failed", reason: message.reason });
        rejectOutstandingShows(message.intentId, message.reason);
      }
      return;
    }
    if (message.kind === "candidate") {
      await ingestCandidate(message.candidate, message.researchImage);
    }
  }

  function rejectOutstandingShows(failedIntentId: string, reason: string): void {
    const need = needByIntent.get(failedIntentId);
    if (!need) return;
    for (let i = outstandingShows.length - 1; i >= 0; i--) {
      const show = outstandingShows[i];
      if (!show || show.need !== need || show.lessonId !== lessonId) continue;
      outstandingShows.splice(i, 1);
      if (show.timer) clearTimeout(show.timer);
      settle(show.intentId, lessonId, { status: "rejected", reason: `prepare-failed: ${reason}` });
    }
  }

  /**
   * Single ingestion pipeline for every candidate source (worker, prepare
   * handler, research runner). Validates, resolves researched images,
   * stores invisibly, settles the prepare intent and auto-promotes an
   * outstanding matching show.
   */
  function needOfStored(stored: CandidatePage): string {
    return needByIntent.get(stored.intentId) ?? "";
  }

  async function ingestCandidate(
    raw: Omit<CandidatePage, "status" | "receivedAt">,
    researchImage?: { url: string; attribution: string },
  ): Promise<void> {
    const intentId = raw.intentId;
    if (raw.lessonId !== lessonId) return; // superseded by a lesson change
    const need = needByIntent.get(intentId);
    const seq = raw.requestSeq;

    const sanitizedSvg = raw.svgAsset ? sanitizeSvg(raw.svgAsset) : null;
    // Real path: the worker already stored researched bytes in the shared
    // per-profile blob store and ships a validated ScreenAssetRef. Accept
    // and verify it instead of discarding — no external browser download.
    let verifiedAsset: CandidatePage["asset"] = null;
    if (raw.asset) {
      const issues = validateAssetRef(raw.asset);
      if (issues.length === 0 && raw.asset.lessonId === lessonId && raw.asset.status === "ready") {
        try {
          const record = await blobStore.get(raw.asset.id);
          if (
            record &&
            record.hash.toLowerCase() === raw.asset.hash.toLowerCase() &&
            record.meta.mimeType === raw.asset.mimeType
          ) {
            verifiedAsset = raw.asset;
          }
        } catch {
          // treat lookup failures as unverified below
        }
      }
      if (!verifiedAsset && !sanitizedSvg && !researchImage) {
        if (getIntentOutcome(registry, intentId)?.status === "pending") {
          settle(intentId, lessonId, { status: "failed", reason: "asset-invalid" });
        }
        return;
      }
      // Invalid ref with an SVG fallback keeps the SVG; legacy image path
      // below still applies when a researchImage was supplied.
      if (!verifiedAsset) {
        // fall through: keep svgAsset, try legacy researchImage if present
      }
    }

    let candidate: CandidatePage = {
      ...raw,
      id: raw.id || newId("p"),
      revision: raw.revision || newId("r"),
      body: [...raw.body],
      sources: [...(raw.sources ?? [])],
      svgAsset: sanitizedSvg,
      asset: verifiedAsset,
      revealed: false,
      status: "ready",
      receivedAt: now(),
    };

    // Legacy compat path: a raw image URL the main thread downloads,
    // verifies and stores. The real asset-ref path above needs no download.
    if (!verifiedAsset && researchImage) {
      try {
        const bytes = await downloadAssetBytes(researchImage.url, options.accessCode);
        const mimeType = sniffMimeType(bytes) ?? "image/png";
        const assetId = newId("b");
        await blobStore.put(assetId, bytes, {
          mimeType,
          provenance: researchImage.attribution,
          lessonId,
        });
        const record = await blobStore.get(assetId);
        if (!record) throw new Error("blob-store-missing");
        const ref = {
          id: assetId,
          hash: record.hash,
          mimeType,
          provenance: researchImage.attribution,
          lessonId,
          status: "ready" as const,
          attribution: researchImage.attribution,
        };
        if (validateAssetRef(ref).length > 0 || !isAssetRefUsable(ref, lessonId)) {
          throw new Error("asset-ref-invalid");
        }
        candidate = { ...candidate, asset: ref, svgAsset: null };
      } catch {
        if (!candidate.svgAsset) {
          if (getIntentOutcome(registry, intentId)?.status === "pending") {
            settle(intentId, lessonId, { status: "failed", reason: "asset-download-failed" });
          }
          return;
        }
        // Keep the generated-SVG fallback; the researched image failed.
      }
    }

    if (need !== undefined && !gate.isCurrent(need, seq)) {
      candidate.status = "superseded";
    } else {
      candidate.status = "ready";
    }
    addCandidate(candidates, candidate, needOfStored);

    if (candidate.status !== "ready") {
      // A newer intent won: the candidate is kept for audit but can never
      // promote. Settle the older prepare honestly instead of hanging it.
      if (getIntentOutcome(registry, intentId)?.status === "pending") {
        settle(intentId, lessonId, { status: "rejected", reason: "superseded" });
      }
      return;
    }

    // Ready-gating: only prepare intents settle ready at invisible commit.
    // A show must settle exactly once after promote+render (via the
    // outstanding-show path below), never at candidate commit — otherwise
    // ready would fire before actual pixels and could emit twice.
    const outcome = getIntentOutcome(registry, intentId);
    if (outcome?.status === "pending" && opByIntent.get(intentId) === "prepare") {
      settle(intentId, lessonId, { status: "ready", page: { id: candidate.id, revision: candidate.revision } });
    }

    // An outstanding show satisfied by this candidate promotes without a
    // second request. Matches the show itself, its auto-prepare child, or
    // any candidate with the same normalised need.
    const showIndex = outstandingShows.findIndex(
      (show) =>
        show.lessonId === lessonId &&
        (candidate.intentId === show.intentId ||
          (show.prepIntentId !== undefined && candidate.intentId === show.prepIntentId) ||
          (need !== undefined && need === show.need && show.need !== "\n")),
    );
    if (showIndex !== -1) {
      const [show] = outstandingShows.splice(showIndex, 1);
      if (show) {
        if (show.timer) clearTimeout(show.timer);
        promoteForShow(show.intentId, show);
      }
    }
  }

  function promoteForShow(intentId: string, show: OutstandingShow): void {
    const intent: ScreenIntent = {
      intentId,
      lessonId,
      op: "show",
      need: show.needText,
      background: show.backgroundText,
      viewport,
    };
    const match = findPromotionCandidate(candidates, intent, needByIntent);
    if (!match) {
      settle(intentId, lessonId, { status: "rejected", reason: "no-matching-candidate" });
      return;
    }
    try {
      deck = promoteCandidate(deck, match, now());
    } catch (err) {
      settle(intentId, lessonId, {
        status: "failed",
        reason: err instanceof Error ? err.message : String(err),
      });
      return;
    }
    void persist();
    publish();
    scheduleRender(intentId, match.id, match.revision);
  }

  async function runPrepare(intent: ScreenIntent, seq: number): Promise<void> {
    // 1. Explicit authoring seam (tests, local-only).
    if (options.prepareHandler) {
      try {
        const produced = await options.prepareHandler(intent, seq);
        if (produced) {
          await ingestCandidate({ ...produced, intentId: intent.intentId, requestSeq: seq });
        } else if (getIntentOutcome(registry, intent.intentId)?.status === "pending") {
          settle(intent.intentId, lessonId, { status: "failed", reason: "prepare-handler-empty" });
        }
      } catch (err) {
        if (getIntentOutcome(registry, intent.intentId)?.status === "pending") {
          settle(intent.intentId, lessonId, {
            status: "failed",
            reason: err instanceof Error ? err.message : String(err),
          });
        }
      }
      return;
    }
    // 2. Durable Harness worker (queued until harness-ready, worker-side
    // boot promise is the second fence — no rootHandle-null race).
    ensureWorker();
    if (worker && !workerFailed) {
      if (!harnessReady) {
        queuedPrepares.push({ intent, seq });
        return;
      }
      try {
        worker.post({ kind: "prepare", intent, seq });
        return;
      } catch {
        workerFailed = true;
        harnessReady = false;
        worker = null;
      }
    }
    // 3. Local-only background research seam.
    if (options.researchRunner) {
      try {
        const bundle: ResearchBundle | null = await options.researchRunner.startGeographyResearch({
          requestId: `${intent.intentId}-${seq}`,
          intentId: intent.intentId,
          requestSeq: seq,
          lessonId,
          query: intent.need ?? "",
          background: intent.background,
        });
        if (bundle) {
          await ingestCandidate({ ...bundle.candidate, intentId: intent.intentId, requestSeq: seq });
        } else if (getIntentOutcome(registry, intent.intentId)?.status === "pending") {
          settle(intent.intentId, lessonId, { status: "failed", reason: "research-empty" });
        }
      } catch (err) {
        if (getIntentOutcome(registry, intent.intentId)?.status === "pending") {
          settle(intent.intentId, lessonId, {
            status: "failed",
            reason: err instanceof Error ? err.message : String(err),
          });
        }
      }
      return;
    }
    // 4. No preparation path: honest failure, never fabricated pages.
    settle(intent.intentId, lessonId, { status: "failed", reason: "screen-unavailable" });
  }

  async function handleIntent(intent: ScreenIntent): Promise<ScreenIntentAck> {
    if (closed) return { accepted: false, intentId: intent.intentId, reason: "closed" };
    if (!intent || typeof intent.intentId !== "string" || !intent.intentId) {
      return { accepted: false, intentId: "", reason: "bad-intent" };
    }
    if (intent.lessonId !== lessonId) {
      return { accepted: false, intentId: intent.intentId, reason: "lesson-mismatch" };
    }

    const existing = getIntentOutcome(registry, intent.intentId);
    if (existing && existing.status !== "pending") {
      const replay = eventForOutcome(
        existing.status === "ready" ? "ready" : existing.status === "rejected" ? "rejected" : "failed",
        intent.intentId,
        lessonId,
        existing,
      );
      if (replay) emit(replay);
      return { accepted: true, intentId: intent.intentId };
    }
    if (existing?.status === "pending") {
      return { accepted: true, intentId: intent.intentId };
    }

    if (intent.op === "reveal") {
      if (!intent.target?.pageId || !intent.target?.revision) {
        settle(intent.intentId, lessonId, { status: "rejected", reason: "reveal-needs-target" });
        return { accepted: false, intentId: intent.intentId, reason: "reveal-needs-target" };
      }
      registerIntent(registry, intent.intentId);
      needByIntent.set(intent.intentId, needKey(intent));
      opByIntent.set(intent.intentId, "reveal");
      const { deck: next, outcome } = applyReveal(deck, intent.target.pageId, intent.target.revision, now());
      if (outcome.kind === "stale") {
        settle(intent.intentId, lessonId, { status: "rejected", reason: outcome.reason });
        return { accepted: true, intentId: intent.intentId };
      }
      deck = next;
      await persist();
      publish();
      if (outcome.kind === "duplicate") {
        if (lastRendered?.pageId === outcome.page.id && lastRendered?.revision === outcome.page.revision) {
          settle(intent.intentId, lessonId, { status: "ready", page: outcome.page });
        } else {
          scheduleRender(intent.intentId, outcome.page.id, outcome.page.revision);
        }
        return { accepted: true, intentId: intent.intentId };
      }
      scheduleRender(intent.intentId, outcome.page.id, outcome.page.revision);
      return { accepted: true, intentId: intent.intentId };
    }

    if (intent.op === "show") {
      registerIntent(registry, intent.intentId);
      const want = needKey(intent);
      needByIntent.set(intent.intentId, want);
      opByIntent.set(intent.intentId, "show");
      const match = findPromotionCandidate(candidates, intent, needByIntent);
      if (match) {
        try {
          deck = promoteCandidate(deck, match, now());
        } catch (err) {
          settle(intent.intentId, lessonId, {
            status: "failed",
            reason: err instanceof Error ? err.message : String(err),
          });
          return { accepted: true, intentId: intent.intentId };
        }
        await persist();
        publish();
        scheduleRender(intent.intentId, match.id, match.revision);
        return { accepted: true, intentId: intent.intentId };
      }
      // No ready candidate yet: hold as an outstanding request AND start
      // preparation for this show intent immediately, so the hold does not
      // wait 60s for work that was never started. Prepare-only behaviour is
      // preserved: without an outstanding show, prepare stays invisible.
      const timer = setTimeout(() => {
        const index = outstandingShows.findIndex((s) => s.intentId === intent.intentId);
        if (index === -1) return;
        outstandingShows.splice(index, 1);
        if (getIntentOutcome(registry, intent.intentId)?.status === "pending") {
          settle(intent.intentId, lessonId, { status: "rejected", reason: "no-matching-candidate" });
        }
      }, outstandingShowTimeoutMs);
      const prepIntentId = `${intent.intentId}:auto-prepare`;
      needByIntent.set(prepIntentId, want);
      opByIntent.set(prepIntentId, "prepare");
      const prepSeq = gate.next();
      gate.noteSuperseded(want, prepSeq);
      outstandingShows.push({
        intentId: intent.intentId,
        lessonId,
        need: want,
        needText: intent.need,
        backgroundText: intent.background,
        prepIntentId,
        timer,
      });
      const prepIntent: ScreenIntent = { ...intent, op: "prepare", intentId: prepIntentId };
      void runPrepare(prepIntent, prepSeq);
      return { accepted: true, intentId: intent.intentId };
    }

    if (intent.op === "prepare") {
      registerIntent(registry, intent.intentId);
      const want = needKey(intent);
      needByIntent.set(intent.intentId, want);
      opByIntent.set(intent.intentId, "prepare");
      const seq = gate.next();
      gate.noteSuperseded(want, seq);
      void runPrepare(intent, seq);
      return { accepted: true, intentId: intent.intentId };
    }

    return { accepted: false, intentId: intent.intentId, reason: `unknown-op:${String((intent as { op?: unknown }).op)}` };
  }

  async function captureObservation(request: ScreenObservationRequest): Promise<ScreenObservationResult> {
    if (closed) throw new Error("closed");
    const validation = validateObservationRequest(deck, request);
    if (!validation.ok) throw new Error(validation.reason);
    const inFlight = inFlightObservations.get(request.observationId);
    if (inFlight) return inFlight;
    if (inFlightObservations.size > 0) throw new Error("observation-busy");
    const task = (async (): Promise<ScreenObservationResult> => {
      let dataUrl: string;
      if (canvas) {
        dataUrl = canvas.toDataURL("image/png");
      } else if (options.pixelReader) {
        dataUrl = await options.pixelReader();
      } else {
        throw new Error("no-canvas");
      }
      const pngBase64 = dataUrl.includes(",") ? dataUrl.slice(dataUrl.indexOf(",") + 1) : dataUrl;
      if (!pngBase64) throw new Error("empty-observation");
      const context: ScreenObservationContext = buildObservationContext(deck, request, viewport);
      return { pngBase64, context };
    })();
    inFlightObservations.set(request.observationId, task);
    try {
      return await task;
    } finally {
      inFlightObservations.delete(request.observationId);
    }
  }

  async function setAnswerDraft(pageId: string, revision: string, text: string): Promise<void> {
    if (closed) throw new Error("closed");
    const { deck: next, outcome } = applyDraft(deck, pageId, revision, text, now());
    if (outcome.kind === "stale") throw new Error(outcome.reason);
    deck = next;
    await persist();
    publish();
    refreshPixels();
  }

  async function submitAnswer(pageId: string, revision: string): Promise<void> {
    if (closed) throw new Error("closed");
    const page = currentPage(deck);
    if (!page || page.id !== pageId || page.revision !== revision) {
      throw new Error("stale-page");
    }
    const answer = readDraft(deck, pageId, revision);
    emit({ type: "answer-submitted", lessonId, page: { id: pageId, revision }, answer });
    await persist();
  }

  async function goTo(index: number): Promise<void> {
    if (closed) throw new Error("closed");
    const next = goToIndex(deck, index, now());
    if (next === deck) return;
    deck = next;
    await persist();
    publish();
    refreshPixels();
  }

  const MAX_HOMEWORK_IMAGES = 10;
  const MAX_HOMEWORK_TITLE_CHARS = 140;
  const MAX_HOMEWORK_TEXT_CHARS = 8000;

  function splitHomeworkBody(text: string | undefined): string[] {
    if (typeof text !== "string") return [];
    const trimmed = text.trim();
    if (!trimmed) return [];
    return trimmed
      .slice(0, MAX_HOMEWORK_TEXT_CHARS)
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => line.slice(0, 1000))
      .slice(0, 30);
  }

  /**
   * Lead-owned child homework intake. MAIN controller only — never a
   * subagent/worker path. The explicit upload authorises immediate
   * visibility, so pages commit directly to the visible deck (no
   * candidate store, no fox ready/answer event).
   */
  async function addHomeworkPage(input: AddHomeworkPageInput): Promise<ScreenDeckSnapshot> {
    if (closed) throw new Error("closed");
    const title = typeof input?.title === "string" ? input.title.trim().slice(0, MAX_HOMEWORK_TITLE_CHARS) : "";
    if (!title) throw new Error("homework-title-required");
    const bodyLines = splitHomeworkBody(input.text);
    const images = input.images ?? [];
    if (!Array.isArray(images)) throw new Error("homework-bad-images");
    if (images.length > MAX_HOMEWORK_IMAGES) throw new Error("homework-too-many-images");
    if (images.length === 0 && bodyLines.length === 0) throw new Error("homework-needs-content");
    for (const image of images) {
      if (!(image?.bytes instanceof Uint8Array)) throw new Error("homework-bad-image-bytes");
      if (image.bytes.byteLength === 0) throw new Error("homework-empty-image");
      if (image.bytes.byteLength > MAX_BLOB_BYTES) throw new Error("blob-too-large");
      if (typeof image.mimeType !== "string" || !image.mimeType) throw new Error("mime-not-allowed");
      if (typeof image.provenance !== "string" || !image.provenance.trim()) {
        throw new Error("homework-provenance-required");
      }
      if (image.provenance.length > 300) throw new Error("homework-provenance-too-long");
      const sniffed = sniffMimeType(image.bytes);
      if (sniffed && sniffed !== image.mimeType) {
        throw new Error("mime-mismatch:" + image.mimeType + "/" + sniffed);
      }
    }
    const storedIds: string[] = [];
    try {
      const refs: ScreenAssetRef[] = [];
      for (const image of images) {
        const provenance = image.provenance.trim().slice(0, 300);
        const assetId = newId("b");
        await blobStore.put(assetId, image.bytes, {
          mimeType: image.mimeType,
          provenance,
          lessonId,
          ...(image.label ? { label: image.label.slice(0, 120) } : {}),
        });
        storedIds.push(assetId);
        const record = await blobStore.get(assetId);
        if (!record) throw new Error("homework-blob-missing");
        const verified = await verifyBlobBytes(image.bytes, { hash: record.hash, mimeType: image.mimeType });
        if (!verified.ok) throw new Error(verified.reason);
        const ref: ScreenAssetRef = {
          id: assetId,
          hash: record.hash.toLowerCase(),
          mimeType: image.mimeType,
          provenance,
          lessonId,
          status: "ready",
          ...(image.label ? { label: image.label.slice(0, 120) } : {}),
          attribution: (image.attribution ?? provenance).slice(0, 300),
        };
        const issues = validateAssetRef(ref);
        if (issues.length > 0 || !isAssetRefUsable(ref, lessonId)) {
          throw new Error("homework-asset-invalid:" + (issues.join(",") || "unusable"));
        }
        refs.push(ref);
      }
      const stamped = now();
      const created: ScreenPage[] = [];
      if (refs.length > 0) {
        for (const ref of refs) {
          created.push({
            id: newId("p"),
            revision: newId("r"),
            lessonId,
            kind: "homework",
            subject: "Läxa",
            title,
            body: [...bodyLines],
            asset: ref,
            svgAsset: null,
            answerLabel: "",
            solution: "",
            sources: [ref.provenance],
            revealed: false,
            createdAt: stamped,
          });
        }
      } else {
        created.push({
          id: newId("p"),
          revision: newId("r"),
          lessonId,
          kind: "homework",
          subject: "Läxa",
          title,
          body: [...bodyLines],
          asset: null,
          svgAsset: null,
          answerLabel: "",
          solution: "",
          sources: [],
          revealed: false,
          createdAt: stamped,
        });
      }
      const pages = [...deck.pages, ...created];
      deck = { ...deck, pages, current: pages.length - 1, updatedAt: now() };
      await persist();
      publish();
      refreshPixels();
      return deck;
    } catch (err) {
      for (const id of storedIds) {
        try {
          if (!deck.pages.some((p) => p.asset?.id === id)) await blobStore.remove(id);
        } catch {
          // best-effort cleanup
        }
      }
      throw err;
    }
  }

  async function startNewLesson(nextLessonId: string): Promise<ScreenDeckSnapshot> {

    if (closed) throw new Error("closed");
    const { deck: next, archived } = startNewLessonDeck(deck, nextLessonId, options.learnerName, now());
    if (archived) {
      const summary: LessonSummary = archived;
      try {
        await store.saveSummary(summary);
      } catch {
        // best-effort
      }
    }
    lessonId = nextLessonId;
    deck = next;
    candidates.clear();
    for (const show of outstandingShows) if (show.timer) clearTimeout(show.timer);
    outstandingShows.length = 0;
    queuedPrepares.length = 0;
    harnessReady = false;
    for (const pending of pendingRenders) if (pending.timer) clearTimeout(pending.timer);
    pendingRenders.length = 0;
    lastRendered = null;
    resumePage = null;
    try {
      worker?.terminate();
    } catch {
      // ignore
    }
    worker = null;
    await persist();
    publish();
    return deck;
  }

  function getSnapshot(): ScreenDeckSnapshot {
    return deck;
  }

  async function init(): Promise<ScreenDeckSnapshot> {
    if (initialized) return deck;
    initialized = true;
    let persisted: ScreenDeckSnapshot | null = null;
    try {
      persisted = await store.loadDeck(options.profileId, lessonId);
    } catch {
      persisted = null;
    }
    if (shouldResumeDeck(persisted, lessonId)) {
      deck = persisted;
      const restored = currentPage(deck);
      resumePage = restored ? { id: restored.id, revision: restored.revision } : null;
    } else {
      deck = createEmptyDeck(options.profileId, lessonId, now());
      await persist();
    }
    publish();
    return deck;
  }

  async function close(): Promise<void> {
    if (closed) return;
    closed = true;
    for (const show of outstandingShows) if (show.timer) clearTimeout(show.timer);
    outstandingShows.length = 0;
    queuedPrepares.length = 0;
    for (const pending of pendingRenders) if (pending.timer) clearTimeout(pending.timer);
    pendingRenders.length = 0;
    try {
      worker?.terminate();
    } catch {
      // ignore
    }
    worker = null;
    await persist();
  }

  return {
    init,
    handleIntent,
    captureObservation,
    setAnswerDraft,
    submitAnswer,
    goTo,
    addHomeworkPage,
    startNewLesson,
    getSnapshot,
    attachCanvas,
    notifyRendered,
    close,
  };
}

export type { ScreenDeckSnapshot };
export { draftKey };
