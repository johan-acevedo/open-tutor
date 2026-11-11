/**
 * Browser-owned Screen core — public API.
 *
 * The lead integrates this module into the React/LiveKit surface:
 * - `createScreenController(options)` owns the deck, drafts, candidates,
 *   render/ready gating and observation capture (see `API.md`).
 * - `renderScreenPage(canvas, page, assets?)` draws the visible page when the
 *   lead owns the canvas instead of `attachCanvas`.
 * - Shared protocol/types below are the same shapes the fox RPC adapter
 *   (`screen.intent` / `screen.observe`, `screen-event`) speaks.
 */
export { createScreenController } from "./controller";
export type {
  PrepareHandler,
  ScreenController,
  ScreenControllerOptions,
  ScreenRenderPageFn,
} from "./controller";
export {
  decodeSvgDrawable,
  drawContain,
  drawCover,
  drawScreenPage,
  renderScreenPage,
  resolveScreenAssets,
  sanitizeSvg,
  wrapText,
  type ScreenRenderAssets,
  type ScreenRenderSize,
} from "./renderer";
export {
  addCandidate,
  applyDraft,
  applyReveal,
  createEmptyDeck,
  currentPage,
  draftKey,
  DRAFT_KEY_SEPARATOR,
  findPromotionCandidate,
  goToIndex,
  MAX_DRAFT_CHARS,
  needKey,
  promoteCandidate,
  readDraft,
  startNewLesson,
  shouldResumeDeck,
  type CandidateStore,
  type DraftOutcome,
  type IntentOutcome,
  type IntentRegistry,
  type RevealOutcome,
} from "./deck";
export {
  createBlobStore,
  createMemoryBlobStore,
  isAssetRefUsable,
  MAX_BLOB_BYTES,
  sha256Hex,
  sniffMimeType,
  validateAssetRef,
  verifyBlobBytes,
  type BlobMeta,
  type BlobRecord,
  type ScreenBlobStore,
} from "./assets";
export {
  buildObservationContext,
  buildVisibleText,
  publicRecordLeaksSolution,
  toPublicObservationRecord,
  validateObservationRequest,
  type PublicObservationRecord,
} from "./observation";
export {
  createIndexedDbScreenStore,
  createMemoryScreenStore,
  type ScreenStore,
} from "./persistence";
export {
  createSupersessionGate,
  type ResearchBundle,
  type ResearchRunner,
  type SupersessionGate,
} from "./childTasks";
export {
  decodeDataUrl,
  downloadAssetBytes,
  fetchGeographyResearch,
  normalizeFeature,
  normalizeMap,
  normalizeResearchResult,
  selectGeographyVisual,
  type GeographyFeature,
  type GeographyGatewayResponse,
  type GeographyMap,
  type GeographyPlace,
  type GeographyResearchQuery,
  type GeographyResearchResult,
  type GeographyVisual,
} from "./research";
export { postScreenChat, SCREEN_CHAT_PATH, SCREEN_MODEL_ID } from "./modelClient";
export { createPiScreenWorker, type ScreenWorkerPort } from "./worker-protocol";
export type {
  CandidatePage,
  LessonSummary,
  PriorNote,
  ScreenArtifact,
  ScreenAssetRef,
  ScreenDeckSnapshot,
  ScreenEventType,
  ScreenIntent,
  ScreenIntentAck,
  ScreenObservationContext,
  ScreenObservationRequest,
  ScreenObservationResult,
  ScreenOp,
  ScreenOutboundEvent,
  ScreenPage,
  ScreenPageKind,
  ScreenViewport,
} from "./types";
