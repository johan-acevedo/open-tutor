/**
 * Background research seam.
 *
 * Geography preparation runs outside the main Screen turn so the main
 * conversation stays reactive to newer intents: the worker spawns a
 * Durable-native child conversation for the research (see
 * `screen.worker.ts`), while the main thread uses a `ResearchRunner` for the
 * local-only path and tests. Both sides gate on request sequences: when a
 * newer intent arrives for the same need, older background results are
 * discarded as superseded instead of reaching the visible deck.
 */
import type { CandidatePage, ScreenArtifact } from "./types";

export interface GeographyResearchRequest {
  requestId: string;
  intentId: string;
  /** Controller sequence of the prepare intent that spawned the work. */
  requestSeq: number;
  lessonId: string;
  query: string;
  background?: string;
}

export interface ResearchBundle {
  candidate: Omit<CandidatePage, "status" | "receivedAt">;
  artifacts: ScreenArtifact[];
}

export interface ResearchRunner {
  startGeographyResearch(request: GeographyResearchRequest): Promise<ResearchBundle | null>;
  cancel?(requestId: string): void;
}

/**
 * Monotonic sequence gate. Hands out request sequences and reports whether
 * a finished background result is still current for its need.
 */
export interface SupersessionGate {
  next(): number;
  isCurrent(needKey: string, seq: number): boolean;
  noteSuperseded(needKey: string, seq: number): void;
}

export function createSupersessionGate(): SupersessionGate {
  let counter = 0;
  const latestByNeed = new Map<string, number>();
  return {
    next() {
      counter += 1;
      return counter;
    },
    isCurrent(need, seq) {
      return (latestByNeed.get(need) ?? 0) <= seq;
    },
    noteSuperseded(need, seq) {
      if ((latestByNeed.get(need) ?? 0) < seq) latestByNeed.set(need, seq);
    },
  };
}
