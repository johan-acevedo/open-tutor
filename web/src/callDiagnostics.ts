/** Browser call events, sent through the existing authenticated session stream.
 * The outbox retries on recovery and reports overflow. It lives in memory:
 * a closed tab or permanently broken connection can lose its entire tail.
 * Hidden does not identify screen lock; playback permission does not prove audibility.
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
  'mic-track': {
    change: ['str', 16], wanted: ['bool', 0], via: ['str', 24],
    ready: ['str', 16], muted: ['bool', 0], enabled: ['bool', 0],
  },
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

type ObservedMicTrack = EventTarget & Pick<MediaStreamTrack, 'readyState' | 'muted' | 'enabled'>;

export function observeMicTrack(media: ObservedMicTrack, log: DiagLog, wanted: () => boolean): () => void {
  const record = (change: string) => log.note('mic-track', {
    change, wanted: wanted(), via: 'track', ready: media.readyState,
    muted: media.muted, enabled: media.enabled,
  });
  const changes: Array<[string, () => void]> = [
    ['mute', () => record('muted')],
    ['unmute', () => record('unmuted')],
    ['ended', () => record('ended')],
  ];
  for (const [name, fn] of changes) media.addEventListener(name, fn);
  record('observed');
  return () => {
    for (const [name, fn] of changes) media.removeEventListener(name, fn);
  };
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
 * Visibility when this lesson starts, using the latest timeline entry where
 * supported and a current synchronous read on Safari.
 */
export function initialVisibilityState(): { state: string; precise: boolean } {
  try {
    if (typeof performance !== 'undefined' && typeof performance.getEntriesByType === 'function') {
      const entries = performance.getEntriesByType('visibility-state');
      if (entries && entries.length > 0) {
        const name = entries[entries.length - 1]?.name;
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
