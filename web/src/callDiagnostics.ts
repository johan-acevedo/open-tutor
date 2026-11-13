/**
 * Bounded, sequenced call diagnostics over the existing session-event channel.
 *
 * Problem: when a call goes quiet on a mobile browser (screen sleep, app
 * switch, playback block, network drop), today's server log cannot tell a
 * capture interruption apart from blocked playback, a room/network loss, or a
 * quiet child. This module records the browser-side half of that story as
 * small structured events and delivers them on the already-authenticated
 * `session-event` text stream the page uses for everything else.
 *
 * What is recorded (all from native browser / upstream LiveKit events, never
 * inferred): page visibility transitions, connection
 * reconnect/reconnect/disconnect (with the LiveKit reason), the actual local
 * microphone MediaStreamTrack mute/unmute/ended plus publication changes
 * alongside the *wanted* mic state, playback permission/AudioContext state,
 * and resumeMedia attempt/result codes. No exception messages, tokens, names,
 * utterances or audio ever enter these events.
 *
 * Delivery limits (read before diagnosing from a journal):
 * - Events are queued in memory (bounded, oldest dropped first with an
 *   explicit counter) and sent while the room is connected — never only at
 *   session end. A flush is attempted on every note, on agent presence, and
 *   on reconnect; a failed send is requeued and retried on recovery.
 * - Sequencing is explicit: every event carries a per-session `seq` and the
 *   client monotonic clock (`t`, `performance.now()`); the server stamps its
 *   own receive time on arrival. A gap in `seq` or a nonzero `dropped` count
 *   means evidence was lost — the journal shows what arrived, not everything
 *   that happened.
 * - The queue is in-memory only: a tab kill, reload or crash loses whatever
 *   was not yet delivered. Nothing here implies survival past the page.
 * - A `hidden` page is reported as hidden, never as a diagnosed cause: it
 *   cannot distinguish lock-screen from app-switch, and silence (or a
 *   `playbackAllowed` flag) is never treated as proof of audibility.
 * - LiveKit SDK internals (`setLogExtension` log forwarding) are deliberately
 *   not wired: only the allowlisted event shapes below are ever sent.
 *
 * Wake-lock note: the parallel wake-lock PR owns acquisition; if it wants its
 * status in this trail it can call `wakeLock(status)` on the log — this module
 * takes no dependency on the Wake Lock API itself.
 */

export type DiagKind =
  | 'visibility'
  | 'connection'
  | 'mic-track'
  | 'playback'
  | 'resume'
  | 'wakelock';

export interface DiagEvent {
  k: DiagKind;
  /** Client monotonic time (performance.now()) when the event was noted. */
  t: number;
  /** Per-session sequence number, starting at 1. Gaps mean loss. */
  seq: number;
  [field: string]: string | number | boolean;
}

export interface DiagBatch {
  type: 'diag';
  v: 1;
  /** First event seq in this batch; last is seq + events.length - 1. */
  seq: number;
  /** Client monotonic time when the batch was sent. */
  tClient: number;
  /** Cumulative queue-overflow drops so far this session. */
  dropped: number;
  events: DiagEvent[];
}

type FieldType = 'str' | 'num' | 'bool';

/** Allowlisted fields per event kind: [type, max string length]. */
const KNOWN_FIELDS: Record<DiagKind, Record<string, [FieldType, number]>> = {
  visibility: { state: ['str', 16], via: ['str', 24], precise: ['bool', 0] },
  connection: { kind: ['str', 16], state: ['str', 32], reason: ['str', 48] },
  'mic-track': { change: ['str', 16], wanted: ['bool', 0], via: ['str', 24] },
  playback: { allowed: ['bool', 0], ctx: ['str', 16], via: ['str', 16] },
  resume: { ok: ['bool', 0], step: ['str', 16], code: ['str', 24] },
  wakelock: { status: ['str', 24] },
};

const KNOWN_KINDS = new Set<string>(Object.keys(KNOWN_FIELDS));

export const DIAG_MAX_QUEUE = 100;
export const DIAG_MAX_BATCH = 25;

export interface DiagTransport {
  /** Authenticated send; may reject when the room is down. Never throws sync. */
  send: (text: string) => Promise<unknown>;
  /** True when a send has somewhere to go (agent present, room connected). */
  isReady: () => boolean;
  now?: () => number;
  maxQueue?: number;
  maxBatch?: number;
}

export interface DiagLog {
  /** Record one event and try to flush. Never throws, never rejects. */
  note: (kind: DiagKind, fields?: Record<string, unknown>) => void;
  /** Attempt delivery of everything queued. Resolves always. */
  flush: () => Promise<void>;
  /** Hook point for the parallel wake-lock PR; plain status string. */
  wakeLock: (status: string) => void;
  pending: () => number;
  dropped: () => number;
}

function safeString(value: unknown, max: number): string | null {
  if (typeof value !== 'string') return null;
  return value.length > max ? value.slice(0, max) : value;
}

function sanitize(kind: DiagKind, fields: Record<string, unknown> | undefined, t: number, seq: number): DiagEvent | null {
  if (!KNOWN_KINDS.has(kind)) return null;
  const spec = KNOWN_FIELDS[kind];
  const event: DiagEvent = { k: kind, t, seq };
  for (const [key, [type, max]] of Object.entries(spec)) {
    const value = fields?.[key];
    if (type === 'str') {
      const s = safeString(value, max);
      if (s !== null) event[key] = s;
    } else if (type === 'bool') {
      if (typeof value === 'boolean') event[key] = value;
    } else if (typeof value === 'number' && Number.isFinite(value)) {
      event[key] = value;
    }
  }
  return event;
}

/**
 * Initial page visibility, preferring the performance timeline where the
 * browser keeps one. `document.visibilityState` alone can lie when the script
 * runs after the user already foregrounded the page; only Chromium keeps
 * `visibility-state` entries (Safari does not), so `precise` tells the reader
 * how much to trust the initial state.
 */
export function initialVisibilityState(): { state: string; precise: boolean } {
  try {
    if (typeof performance !== 'undefined' && typeof performance.getEntriesByType === 'function') {
      const entries = performance.getEntriesByType('visibility-state') as Array<{ name?: unknown }>;
      if (entries && entries.length > 0) {
        const name = entries[0]?.name;
        if (name === 'visible' || name === 'hidden' || name === 'prerender') {
          return { state: name, precise: true };
        }
      }
    }
  } catch {
    /* fall through to the synchronous read */
  }
  try {
    if (typeof document !== 'undefined' && typeof document.visibilityState === 'string') {
      return { state: document.visibilityState, precise: false };
    }
  } catch {
    /* no DOM (tests without jsdom): fall through */
  }
  return { state: 'unknown', precise: false };
}

export function createDiagLog(transport: DiagTransport): DiagLog {
  const maxQueue = Math.max(1, transport.maxQueue ?? DIAG_MAX_QUEUE);
  const maxBatch = Math.max(1, transport.maxBatch ?? DIAG_MAX_BATCH);
  const now = () => {
    try {
      return transport.now?.() ?? (typeof performance !== 'undefined' ? performance.now() : Date.now());
    } catch {
      return Date.now();
    }
  };

  let queue: DiagEvent[] = [];
  let seq = 0;
  let dropped = 0;
  let flushing = false;

  function trimOverflow(): void {
    while (queue.length > maxQueue) {
      queue.shift();
      dropped += 1;
    }
  }

  async function flush(): Promise<void> {
    if (flushing) return;
    flushing = true;
    try {
      while (queue.length > 0) {
        let ready = false;
        try {
          ready = transport.isReady();
        } catch {
          ready = false;
        }
        if (!ready) return;
        const batch = queue.splice(0, maxBatch);
        const envelope: DiagBatch = {
          type: 'diag',
          v: 1,
          seq: batch[0].seq,
          tClient: now(),
          dropped,
          events: batch,
        };
        let payload: string;
        try {
          payload = JSON.stringify(envelope);
        } catch {
          // Sanitized events always stringify; if not, drop the batch loudly.
          dropped += batch.length;
          continue;
        }
        try {
          await transport.send(payload);
        } catch {
          // Room broken: keep the batch at the front, retry on recovery.
          queue.unshift(...batch);
          trimOverflow();
          return;
        }
      }
    } finally {
      flushing = false;
    }
  }

  function note(kind: DiagKind, fields?: Record<string, unknown>): void {
    try {
      seq += 1;
      const event = sanitize(kind, fields, now(), seq);
      if (event) {
        queue.push(event);
        trimOverflow();
      }
      void flush();
    } catch {
      /* diagnostics must never break the call */
    }
  }

  return {
    note,
    flush: () => flush().catch(() => undefined),
    wakeLock: (status: string) => note('wakelock', { status }),
    pending: () => queue.length,
    dropped: () => dropped,
  };
}
