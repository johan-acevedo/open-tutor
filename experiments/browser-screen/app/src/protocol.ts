// Shared message protocol between the page (main thread) and the screen
// worker. The worker owns the Pi Durable Harness; the page owns pixels.
export type DeckPage = {
  id: string;
  revision: string;
  topic: string;
  question: string;
  solution: string;
  input: string;
  revealed: boolean;
  createdAt: number;
};

export type DeckSnapshot = {
  conversationId: string;
  pages: DeckPage[];
  current: number;
  readOnly: boolean;
};

export type MainToWorker =
  | { kind: "init"; token: string }
  | { kind: "prepare"; topic: string; level: string }
  | { kind: "input"; pageId: string; revision: string; text: string }
  | { kind: "goto"; index: number }
  | { kind: "fox"; command: string; pageId: string; revision: string }
  | { kind: "observe"; pngBase64: string }
  | { kind: "close" };

export type WorkerToMain =
  | { kind: "ready"; snapshot: DeckSnapshot }
  | { kind: "deck"; snapshot: DeckSnapshot }
  | { kind: "status"; busy: boolean; text: string }
  | { kind: "fox"; text: string }
  | { kind: "observed"; text: string }
  | { kind: "error"; message: string };
