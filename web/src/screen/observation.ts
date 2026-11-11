/**
 * Observation context: what Räven receives alongside the PNG pixels.
 *
 * Two deliberately separate things leave the browser per observation:
 *   1. `pngBase64` — the actual pixels of the rendered visible canvas.
 *   2. `context` — a small JSON record with interaction state, sources and
 *      `privateTeaching` (e.g. the hidden solution).
 *
 * The solution must never appear in any public field while hidden. Use
 * `toPublicObservationRecord()` whenever the context is logged, streamed or
 * asserted on; only the fox `screen-context` stream carries the full record.
 */
import { readDraft } from "./deck";
import type {
  ScreenDeckSnapshot,
  ScreenObservationContext,
  ScreenObservationRequest,
} from "./types";

export type ObservationValidation =
  | { ok: true }
  | { ok: false; reason: "no-visible-page" | "stale-observation" };

export function validateObservationRequest(
  deck: ScreenDeckSnapshot,
  req: ScreenObservationRequest,
): ObservationValidation {
  const page = deck.pages[Math.min(Math.max(deck.current, 0), deck.pages.length - 1)];
  if (!page) return { ok: false, reason: "no-visible-page" };
  if (page.id !== req.pageId || page.revision !== req.revision) {
    return { ok: false, reason: "stale-observation" };
  }
  return { ok: true };
}

export function buildObservationContext(
  deck: ScreenDeckSnapshot,
  req: ScreenObservationRequest,
  viewport: { w: number; h: number },
): ScreenObservationContext {
  const page = deck.pages.find((p) => p.id === req.pageId && p.revision === req.revision);
  if (!page) throw new Error("stale-observation");
  const draft = readDraft(deck, page.id, page.revision);
  return {
    observationId: req.observationId,
    lessonId: deck.lessonId,
    page: { id: page.id, revision: page.revision },
    viewport: { w: viewport.w, h: viewport.h },
    answerState: {
      hasDraft: draft.length > 0,
      draftLength: draft.length,
      revealed: page.revealed,
    },
    sources: [...page.sources],
    privateTeaching: page.solution,
  };
}

export type PublicObservationRecord = Omit<ScreenObservationContext, "privateTeaching">;

/** Strip the fox-only field before logging, streaming or asserting. */
export function toPublicObservationRecord(
  context: ScreenObservationContext,
): PublicObservationRecord {
  const { privateTeaching: _private, ...rest } = context;
  return rest;
}

/**
 * Test/CI guard: the serialised public record must not contain the hidden
 * solution. Callers pass the page's `revealed` flag so the check only
 * applies while the solution is hidden.
 */
export function publicRecordLeaksSolution(
  publicRecord: PublicObservationRecord,
  solution: string,
  revealed: boolean,
): boolean {
  if (revealed) return false;
  const needle = solution.trim();
  if (needle.length < 2) return false;
  return JSON.stringify(publicRecord).includes(needle);
}
