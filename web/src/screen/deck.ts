/**
 * Pure deck / revision / duplicate / stale logic for the Screen.
 *
 * No DOM, no Pi imports, no I/O: every function here is a deterministic
 * state transition covered by focused Vitest tests. The controller owns the
 * mutable registries and persists the results; the Web Worker proposes
 * candidates but never writes the visible deck directly.
 */
import type {
  CandidatePage,
  LessonSummary,
  ScreenDeckSnapshot,
  ScreenIntent,
  ScreenPage,
} from "./types";

export const DRAFT_KEY_SEPARATOR = ":";
export const MAX_DRAFT_CHARS = 500;

export function draftKey(pageId: string, revision: string): string {
  return `${pageId}${DRAFT_KEY_SEPARATOR}${revision}`;
}

/** Normalised need string used to match `show` intents to candidates. */
export function needKey(intent: Pick<ScreenIntent, "need" | "background">): string {
  return `${(intent.need ?? "").trim().toLowerCase()}\n${(intent.background ?? "").trim().toLowerCase()}`;
}

export function createEmptyDeck(profileId: string, lessonId: string, now: number): ScreenDeckSnapshot {
  return { profileId, lessonId, pages: [], current: 0, drafts: {}, updatedAt: now };
}

export function currentPage(deck: ScreenDeckSnapshot): ScreenPage | undefined {
  if (deck.pages.length === 0) return undefined;
  return deck.pages[Math.min(Math.max(deck.current, 0), deck.pages.length - 1)];
}

export type IntentOutcome =
  | { status: "pending" }
  | { status: "ready"; page: { id: string; revision: string } }
  | { status: "rejected"; reason: string }
  | { status: "failed"; reason: string };

/** Duplicate-intent registry: intentId → outcome. */
export type IntentRegistry = Map<string, IntentOutcome>;

export function getIntentOutcome(registry: IntentRegistry, intentId: string): IntentOutcome | undefined {
  return registry.get(intentId);
}

export function registerIntent(registry: IntentRegistry, intentId: string): boolean {
  if (registry.has(intentId)) return false;
  registry.set(intentId, { status: "pending" });
  return true;
}

export function settleIntent(registry: IntentRegistry, intentId: string, outcome: IntentOutcome): void {
  registry.set(intentId, outcome);
}

// ---------------------------------------------------------------------------
// Candidates (invisible until promoted by `show`)
// ---------------------------------------------------------------------------

export type CandidateStore = Map<string, CandidatePage>;

export function candidateId(intentId: string, pageId: string): string {
  return `${intentId}:${pageId}`;
}

/**
 * Store an invisible candidate. Candidates from an older request sequence
 * for the same need are marked superseded so a newer intent wins over stale
 * background results. Never touches the visible deck. The normalised need
 * for a candidate comes from `needOf` (the controller tracks
 * intentId → needKey; candidates themselves carry no need text).
 */
export function addCandidate(
  store: CandidateStore,
  candidate: CandidatePage,
  needOf: (candidate: CandidatePage) => string,
): { supersededIds: string[] } {
  const supersededIds: string[] = [];
  const want = needOf(candidate);
  for (const existing of store.values()) {
    if (
      existing.status !== "promoted" &&
      existing.lessonId === candidate.lessonId &&
      needOf(existing) === want &&
      existing.requestSeq < candidate.requestSeq
    ) {
      existing.status = "superseded";
      supersededIds.push(candidateId(existing.intentId, existing.id));
    }
  }
  store.set(candidateId(candidate.intentId, candidate.id), candidate);
  return { supersededIds };
}

/**
 * Find the newest ready candidate that a `show` intent authorises for
 * promotion: same lesson, still ready (not superseded/discarded/promoted),
 * and either produced for this intent or for the same normalised need.
 */
export function findPromotionCandidate(
  store: CandidateStore,
  intent: ScreenIntent,
  intentNeedById: ReadonlyMap<string, string>,
): CandidatePage | undefined {
  const want = needKey(intent);
  let best: CandidatePage | undefined;
  for (const c of store.values()) {
    if (c.status !== "ready") continue;
    if (c.lessonId !== intent.lessonId) continue;
    const sameIntent = c.intentId === intent.intentId;
    const sameNeed = !sameIntent && (intentNeedById.get(c.intentId) ?? "") === want && want !== "\n";
    if (!sameIntent && !sameNeed) continue;
    if (!best || c.requestSeq > best.requestSeq) best = c;
  }
  return best;
}

/**
 * Promote a ready candidate into the visible deck. Returns the new deck with
 * the promoted page appended and selected. Marks the candidate promoted.
 */
export function promoteCandidate(
  deck: ScreenDeckSnapshot,
  candidate: CandidatePage,
  now: number,
): ScreenDeckSnapshot {
  if (candidate.status !== "ready") {
    throw new Error(`cannot promote candidate in status ${candidate.status}`);
  }
  if (candidate.lessonId !== deck.lessonId) {
    throw new Error("candidate lesson does not match visible deck lesson");
  }
  candidate.status = "promoted";
  const page: ScreenPage = {
    id: candidate.id,
    revision: candidate.revision,
    lessonId: candidate.lessonId,
    kind: candidate.kind,
    subject: candidate.subject,
    title: candidate.title,
    body: [...candidate.body],
    asset: candidate.asset,
    svgAsset: candidate.svgAsset,
    answerLabel: candidate.answerLabel,
    solution: candidate.solution,
    sources: [...candidate.sources],
    revealed: false,
    createdAt: candidate.createdAt,
  };
  const pages = [...deck.pages, page];
  return { ...deck, pages, current: pages.length - 1, updatedAt: now };
}

// ---------------------------------------------------------------------------
// Reveal: deterministic, id + revision gated, never a model turn
// ---------------------------------------------------------------------------

export type RevealOutcome =
  | { kind: "revealed"; page: { id: string; revision: string } }
  | { kind: "duplicate"; page: { id: string; revision: string } }
  | { kind: "stale"; reason: string };

export function applyReveal(
  deck: ScreenDeckSnapshot,
  pageId: string,
  revision: string,
  now: number,
): { deck: ScreenDeckSnapshot; outcome: RevealOutcome } {
  const page = currentPage(deck);
  if (!page) {
    return { deck, outcome: { kind: "stale", reason: "no-visible-page" } };
  }
  if (page.id !== pageId || page.revision !== revision) {
    return {
      deck,
      outcome: { kind: "stale", reason: `stale-reveal: visible is ${page.id} ${page.revision}` },
    };
  }
  if (page.revealed) {
    return { deck, outcome: { kind: "duplicate", page: { id: page.id, revision: page.revision } } };
  }
  const pages = deck.pages.map((p) => (p === page ? { ...p, revealed: true } : p));
  return {
    deck: { ...deck, pages, updatedAt: now },
    outcome: { kind: "revealed", page: { id: page.id, revision: page.revision } },
  };
}

// ---------------------------------------------------------------------------
// Child drafts: local only, shared solely through explicit submission
// ---------------------------------------------------------------------------

export type DraftOutcome = { kind: "saved" } | { kind: "stale"; reason: string };

export function applyDraft(
  deck: ScreenDeckSnapshot,
  pageId: string,
  revision: string,
  text: string,
  now: number,
): { deck: ScreenDeckSnapshot; outcome: DraftOutcome } {
  const page = deck.pages.find((p) => p.id === pageId && p.revision === revision);
  if (!page) {
    return { deck, outcome: { kind: "stale", reason: "unknown-page-revision" } };
  }
  const drafts = { ...deck.drafts, [draftKey(pageId, revision)]: text.slice(0, MAX_DRAFT_CHARS) };
  return { deck: { ...deck, drafts, updatedAt: now }, outcome: { kind: "saved" } };
}

export function readDraft(deck: ScreenDeckSnapshot, pageId: string, revision: string): string {
  return deck.drafts[draftKey(pageId, revision)] ?? "";
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

export function goToIndex(deck: ScreenDeckSnapshot, index: number, now: number): ScreenDeckSnapshot {
  if (deck.pages.length === 0) return deck;
  const clamped = Math.min(Math.max(index, 0), deck.pages.length - 1);
  if (clamped === deck.current) return deck;
  return { ...deck, current: clamped, updatedAt: now };
}

// ---------------------------------------------------------------------------
// Lesson continuity: intentional new lesson vs interrupted resume
// ---------------------------------------------------------------------------

/**
 * Start an intentional new lesson: archive a summary of the old deck and
 * return an empty visible deck for the new lesson. Referenced blobs stay in
 * the blob store; speculative candidates are dropped by the caller.
 */
export function startNewLesson(
  deck: ScreenDeckSnapshot,
  newLessonId: string,
  learnerName: string,
  now: number,
): { deck: ScreenDeckSnapshot; archived: LessonSummary | null } {
  if (newLessonId === deck.lessonId) {
    return { deck, archived: null };
  }
  const archived: LessonSummary | null =
    deck.pages.length === 0
      ? null
      : {
          lessonId: deck.lessonId,
          profileId: deck.profileId,
          pageCount: deck.pages.length,
          titles: deck.pages.map((p) => p.title).slice(0, 8),
          endedAt: now,
          greetingHint:
            deck.pages.length === 1
              ? `${learnerName} jobbade senast med “${deck.pages[0]?.title ?? "en uppgift"}”.`
              : `${learnerName} jobbade senast med ${deck.pages.length} sidor, bland annat “${deck.pages[0]?.title ?? "en uppgift"}”.`,
        };
  return { deck: createEmptyDeck(deck.profileId, newLessonId, now), archived };
}

/**
 * Reopening the same lesson after an interruption resumes the persisted deck
 * untouched; anything else is a fresh start for the lead to confirm.
 */
export function shouldResumeDeck(
  persisted: ScreenDeckSnapshot | null,
  lessonId: string,
): persisted is ScreenDeckSnapshot {
  return !!persisted && persisted.lessonId === lessonId && persisted.pages.length > 0;
}
