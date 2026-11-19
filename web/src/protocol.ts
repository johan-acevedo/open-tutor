// Browser ↔ tutor protocol types.
// Mirrors docs/protocol.md. Change together with server/open_tutor/board.py.

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
};

export type SessionLearner = {
  /** Browser profile id, so the worker's learner RPCs can name their target. */
  id?: string;
  name: string;
  /** School year 1-12, or null when the tutor has not learned it yet. */
  grade: number | null;
  notes: Note[];
  /** Age band for this page load (primary | middle | upper). */
  band?: string;
};

export type SessionRequest = {
  learner: SessionLearner;
  board: { w: number; h: number; device: string };
  /** Random per-browser id (localStorage) so one device's sessions link up. */
  device_id: string;
};

export type SessionResponse = {
  url: string;
  token: string;
  room: string;
};

/** One browser-side diagnostic event: allowlisted kind + client seq/time. */
export type DiagWireEvent = {
  k: 'visibility' | 'connection' | 'mic-track' | 'playback' | 'resume' | 'wakelock';
  t: number;
  seq: number;
  [field: string]: string | number | boolean;
};

export type SessionEvent =
  | { type: 'end' }
  | { type: 'resource-closed'; id: string }
  | { type: 'board-size'; w: number; h: number; device: string }
  | { type: 'quiet'; on: boolean }
  | { type: 'page-answer'; page: string; part: string; value: string; kind: string }
  | { type: 'diag'; v: 1; seq: number; tClient: number; dropped: number; events: DiagWireEvent[] };

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
export const BOARD_RPC_PATCH = 'board.patch';
export const BOARD_RPC_REVEAL = 'board.reveal';
export const BOARD_RPC_POINT = 'board.point';
export const BOARD_RPC_LOADING = 'board.loading';

export const TOPIC_CHAT = 'lk.chat';
export const TOPIC_TRANSCRIPTION = 'lk.transcription';
export const TOPIC_HOMEWORK = 'homework';
export const TOPIC_HOMEWORK_TEXT = 'homework-text';
export const TOPIC_SESSION_EVENT = 'session-event';
export const TOPIC_NOTE = 'note';
/** Worker → browser RPCs for the tutor's learner tools. Acknowledged
 *  request/response (the tool returns only after the browser answers):
 *
 *  - learner.setName { profileId, name }: the browser creates the local
 *    profile for the name (or attaches to an existing one with the same
 *    name), remembers it as the assumed student, and replies
 *    { ok, profile: { id, name, grade } }. A repeat call with a corrected
 *    name is the same path again; a failed call saves nothing.
 *
 *  - learner.setGrade { profileId, grade }: the browser applies the grade
 *    only when profileId is still the active profile, else rejects as stale.
 *    Replies { ok, grade }.
 *  - learner.switch { name }: the browser resolves or creates that student's
 *    profile (serialized; one profile per name), arms a post-lesson prefill
 *    with it, and replies { ok, profile: { id, name, grade } }. The worker then
 *    ends this lesson exactly like Avsluta; afterwards the browser shows the
 *    start page prefilled for the new student \u2014 no automatic reconnect, no
 *    continuation session. A failed call never arms anything.
 */
export const LEARNER_RPC_SET_NAME = 'learner.setName';
export const LEARNER_RPC_SET_GRADE = 'learner.setGrade';
export const LEARNER_RPC_SWITCH = 'learner.switch';

export const ATTR_AGENT_STATE = 'lk.agent.state';
export const ATTR_TUTOR_MODE = 'tutor.mode';
