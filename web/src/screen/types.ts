/**
 * Shared Screen types for the browser-owned Open Tutor Screen.
 *
 * The Screen is a browser-resident Pi Durable session that owns the visible
 * page deck. Räven (voice) sends intents; the Screen answers immediately with
 * an ack and later with a correlated async event. Observation pixels always
 * come from the actually rendered visible canvas.
 */

/** Learner note kept against the browser profile (device-local). */
export interface PriorNote {
  text: string;
  createdAt?: number;
}

/** Fox-to-browser visual operations (protocol v1). */
export type ScreenOp = "prepare" | "show" | "reveal";

/** Viewport the fox reports so the Screen can compose for it. */
export interface ScreenViewport {
  w: number;
  h: number;
  device: string;
}

/** RPC `screen.intent` payload (fox → browser). */
export interface ScreenIntent {
  intentId: string;
  lessonId: string;
  op: ScreenOp;
  /** What the fox needs, e.g. "bråkräkning åk 3" or "Sveriges landskap". */
  need?: string;
  /** Extra background for preparation, e.g. homework text. */
  background?: string;
  /** Required for `reveal`: binds the operation to one page + revision. */
  target?: { pageId: string; revision: string };
  viewport: ScreenViewport;
}

/** Immediate RPC answer. Never waits for model work, rendering or assets. */
export type ScreenIntentAck =
  | { accepted: true; intentId: string }
  | { accepted: false; intentId: string; reason: string };

/** Browser-to-fox stream `screen-event` payload. */
export type ScreenEventType = "ready" | "rejected" | "failed" | "answer-submitted" | "page-changed";

export interface ScreenOutboundEvent {
  type: ScreenEventType;
  intentId?: string;
  lessonId: string;
  page?: { id: string; revision: string };
  reason?: string;
  /** `answer-submitted` only. The sole path that shares child input. */
  answer?: string;
}

/** Visible page kinds rendered by the first-slice canvas renderer. */
export type ScreenPageKind = "exercise" | "geography" | "homework";

/** One uploaded homework image (child upload or PDF-rendered page). */
export interface HomeworkImageInput {
  bytes: Uint8Array;
  mimeType: string;
  provenance: string;
  label?: string;
  attribution?: string;
}

/** Lead-owned child homework intake. Title required; text and/or images carry the content. */
export interface AddHomeworkPageInput {
  title: string;
  text?: string;
  images?: HomeworkImageInput[];
}

/**
 * Reference to a binary asset. Durable docs and page records carry only this
 * reference — never the bytes. Bytes live in the separate IndexedDB blob
 * store (see `assets.ts`).
 */
export interface ScreenAssetRef {
  id: string;
  /** Lowercase hex sha-256 of the exact bytes. */
  hash: string;
  mimeType: string;
  /** Where the bytes came from, e.g. "wikimedia:File:…", "generated-svg". */
  provenance: string;
  lessonId: string;
  status: "staged" | "ready" | "discarded";
  label?: string;
  attribution?: string;
}

/** One durable, revisioned, visible page. Immutable except via deck ops. */
export interface ScreenPage {
  id: string;
  revision: string;
  lessonId: string;
  kind: ScreenPageKind;
  /** Short chip label, e.g. "Matte" or "Geografi". */
  subject: string;
  title: string;
  /** Question / content lines, rendered wrapped. */
  body: string[];
  /** Researched image asset (bytes in the blob store). */
  asset?: ScreenAssetRef | null;
  /** Generated SVG markup chosen instead of a researched image. */
  svgAsset?: string | null;
  /** Label of the child answer area, e.g. "Ditt svar". */
  answerLabel: string;
  /**
   * Private solution / teacher notes. Rendered into pixels only after a
   * fox-gated reveal; otherwise carried only in `privateTeaching`.
   */
  solution: string;
  sources: string[];
  revealed: boolean;
  createdAt: number;
}

/**
 * Invisible page composition. Only the main Screen may promote a candidate
 * into the visible deck — subagents never receive a visible-deck write tool.
 */
export interface CandidatePage extends ScreenPage {
  intentId: string;
  /** Controller sequence of the prepare intent that spawned the work. */
  requestSeq: number;
  status: "ready" | "superseded" | "discarded" | "promoted";
  receivedAt: number;
}

/** Raw or derived material behind a candidate (search result, SVG, …). */
export interface ScreenArtifact {
  id: string;
  lessonId: string;
  intentId: string;
  kind: "search-result" | "source-text" | "downloaded-image" | "generated-svg" | "map-data" | "calculation" | "caption";
  /** Small JSON-safe payload; binary bytes stay in the blob store. */
  payload: Record<string, string>;
  /** Blob-store ids referenced by this artifact, if any. */
  blobIds: string[];
  provenance: string;
  createdAt: number;
}

/** Lesson-scoped visible deck with page-local child drafts. */
export interface ScreenDeckSnapshot {
  profileId: string;
  lessonId: string;
  pages: ScreenPage[];
  current: number;
  /** Child drafts keyed `${pageId}:${revision}`. Local only, never shared. */
  drafts: Record<string, string>;
  updatedAt: number;
}

/** Short summary kept when an intentional new lesson archives the old deck. */
export interface LessonSummary {
  lessonId: string;
  profileId: string;
  pageCount: number;
  titles: string[];
  endedAt: number;
  /** One-line hint so Räven can greet a returning learner warmly. */
  greetingHint: string;
}

/** RPC `screen.observe` payload (fox → browser). Mirrors protocol `screen.observe`. */
export interface ScreenObservationRequest {
  observationId: string;
  lessonId: string;
  pageId: string;
  revision: string;
}

/**
 * `screen-context` payload (browser → fox). `privateTeaching` is the narrow
 * teacher field (e.g. the hidden solution); everything else is public and
 * must never contain the solution while it is hidden.
 */
export interface ScreenObservationContext {
  observationId: string;
  lessonId: string;
  page: { id: string; revision: string };
  /** What is visibly on the page; solution text only when revealed. */
  visibleText: string;
  viewport: { w: number; h: number; device: string };
  answerState: { hasDraft: boolean; draftLength: number; revealed: boolean };
  sources: string[];
  privateTeaching: string;
}

/** Result of `captureObservation`: transient PNG + split context. */
export interface ScreenObservationResult {
  /** Raw base64 PNG bytes (no data-URL prefix). Never persisted. */
  pngBase64: string;
  context: ScreenObservationContext;
}
