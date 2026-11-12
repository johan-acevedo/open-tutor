/**
 * Main-thread ↔ Screen worker protocol.
 *
 * The Pi Durable Harness lives in a module Web Worker (`screen.worker.ts`);
 * the page owns the pixels. The worker proposes invisible candidates and
 * reports failures; the main-thread controller validates, commits and
 * promotes them. There is no visible-deck write path from worker to page —
 * promotion happens only through the controller's pure deck functions.
 */
import type { CandidatePage, PriorNote, ScreenArtifact, ScreenIntent } from "./types";

export interface ScreenWorkerInit {
  profileId: string;
  room: string;
  lessonId: string;
  learnerName: string;
  grade?: string;
  priorNotes: PriorNote[];
  accessCode: string;
}

export type MainToScreenWorker =
  | { kind: "init"; init: ScreenWorkerInit }
  | { kind: "prepare"; intent: ScreenIntent; seq: number }
  | { kind: "close" };

export type ScreenWorkerToMain =
  | { kind: "harness-ready" }
  | {
      kind: "candidate";
      candidate: CandidatePage;
      artifacts: ScreenArtifact[];
      /** Researched image for the main thread to download, verify and store. */
      researchImage?: { url: string; attribution: string };
    }
  | { kind: "worker-failed"; intentId: string; reason: string }
  | { kind: "worker-log"; text: string };

/** Minimal port the controller needs; real Worker or an injected fake. */
export interface ScreenWorkerPort {
  post(message: MainToScreenWorker): void;
  onmessage: ((message: ScreenWorkerToMain) => void) | null;
  terminate(): void;
}

function wrapNative(worker: Worker): ScreenWorkerPort {
  const port: ScreenWorkerPort = {
    post(message) {
      worker.postMessage(message);
    },
    onmessage: null,
    terminate() {
      worker.terminate();
    },
  };
  worker.onmessage = (event: MessageEvent<ScreenWorkerToMain>) => {
    port.onmessage?.(event.data);
  };
  return port;
}

/**
 * Construct the real Pi Harness worker, or null when Workers are
 * unavailable (SSR, old browsers, jsdom tests). Null means the controller
 * runs in local-only mode: deck/reveal/draft/observation stay fully
 * functional, while `prepare` needs an injected `prepareHandler` or reports
 * `failed` honestly instead of fabricating pages.
 */
export function createPiScreenWorker(): ScreenWorkerPort | null {
  if (typeof Worker === "undefined") return null;
  try {
    const worker = new Worker(new URL("./screen.worker.ts", import.meta.url), {
      type: "module",
    });
    return wrapNative(worker);
  } catch {
    return null;
  }
}
