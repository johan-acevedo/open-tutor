// Browser ↔ tutor protocol types.
// Mirrors docs/protocol.md. Change together with server/open_tutor/board.py.

export type Step = {
  /** KaTeX display equation, e.g. "3x = 15" */
  tex: string;
  /** Optional spoken hint shown under the step */
  note?: string;
  /** Balance operation shown between rows, e.g. "−5" or "÷3" */
  op?: string;
};

export type Note = {
  /** ISO timestamp when the note was written */
  at: string;
  /** What the session was about */
  topic: string;
  /** What clicked for the learner */
  clicked?: string;
  /** What is still tricky */
  tricky?: string;
  /** What to try next time */
  next?: string;
};

export type BoardItem =
  | { id: string; kind: 'text'; title?: string; markdown: string }
  | { id: string; kind: 'steps'; title?: string; steps: Step[] }
  | { id: string; kind: 'mindmap'; title?: string; center: string; ideas: string[] }
  | { id: string; kind: 'svg'; title?: string; svg: string }
  | { id: string; kind: 'html'; title?: string; html: string; height?: number; width?: number }
  | { id: string; kind: 'image'; title?: string; url: string; alt: string }
  | { id: string; kind: 'page'; title: string; body: string }
  | { id: string; kind: 'pending'; title: string; height?: number }
  | {
      id: string;
      kind: 'resource';
      title: string;
      url: string;
      embedUrl?: string;
      source?: string;
      prompt?: string;
    }
  // Browser-created only: homework the child brought in.
  | { id: string; kind: 'homework'; title: string; images?: string[]; text?: string };

/** Payload for the board.focus RPC method. */
export type BoardFocusPayload = {
  id: string;
  step?: number;
};

export type SessionLearner = {
  name: string;
  grade: number;
  notes: Note[];
};

export type SessionRequest = {
  learner: SessionLearner;
  board: { w: number; h: number; device: string };
};

export type SessionResponse = {
  url: string;
  token: string;
  room: string;
};

export type SessionEvent =
  | { type: 'end' }
  | { type: 'resource-closed'; id: string }
  | { type: 'board-size'; w: number; h: number; device: string }
  | { type: 'quiet'; on: boolean }
  | { type: 'page-answer'; page: string; part: string; value: string; kind: string };

/** Byte-stream attributes for topic 'homework'. */
export type HomeworkAttributes = {
  kind: 'photo' | 'screenshot' | 'pdf-page';
  source: string;
  page?: string;
  pages?: string;
  itemId: string;
};

export type AgentState = 'initializing' | 'listening' | 'thinking' | 'speaking';

export type TutorMode = 'talking' | 'quiet' | 'resource' | 'ending';

export const BOARD_RPC_SHOW = 'board.show';
export const BOARD_RPC_UPDATE = 'board.update';
export const BOARD_RPC_FOCUS = 'board.focus';
export const BOARD_RPC_REMOVE = 'board.remove';
export const BOARD_RPC_PATCH = 'board.patch';
export const BOARD_RPC_REVEAL = 'board.reveal';
export const BOARD_RPC_POINT = 'board.point';

export const TOPIC_CHAT = 'lk.chat';
export const TOPIC_TRANSCRIPTION = 'lk.transcription';
export const TOPIC_HOMEWORK = 'homework';
export const TOPIC_HOMEWORK_TEXT = 'homework-text';
export const TOPIC_SESSION_EVENT = 'session-event';
export const TOPIC_NOTE = 'note';

export const ATTR_AGENT_STATE = 'lk.agent.state';
export const ATTR_TUTOR_MODE = 'tutor.mode';
