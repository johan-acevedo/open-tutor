import { describe, expect, it, vi } from 'vitest';
import {
  createDiagLog,
  DIAG_MAX_BATCH,
  initialVisibilityState,
  observeMicTrack,
  type DiagBatch,
  type DiagTransport,
} from './callDiagnostics';

function harness(overrides?: Partial<DiagTransport> & { sent?: string[] }) {
  const sent: string[] = overrides?.sent ?? [];
  let ready = false;
  const transport: DiagTransport = {
    send: async (text: string) => {
      sent.push(text);
    },
    isReady: () => ready,
    now: (() => {
      let t = 1000;
      return () => (t += 10);
    })(),
    ...overrides,
  };
  const log = createDiagLog(transport);
  return { log, sent, setReady: (v: boolean) => (ready = v) };
}

function batches(sent: string[]): DiagBatch[] {
  return sent.map((s) => JSON.parse(s) as DiagBatch);
}

describe('callDiagnostics', () => {
  it('records native capture interruption and recovery, and detaches old track listeners', async () => {
    class Mic extends EventTarget {
      readyState: MediaStreamTrackState = 'live';
      muted = false;
      enabled = true;
    }
    const media = new Mic();
    const { log, sent, setReady } = harness();
    const stop = observeMicTrack(media, log, () => true);
    media.muted = true;
    media.dispatchEvent(new Event('mute'));
    media.muted = false;
    media.dispatchEvent(new Event('unmute'));
    media.readyState = 'ended';
    media.dispatchEvent(new Event('ended'));
    stop();
    media.dispatchEvent(new Event('mute'));
    setReady(true);
    await log.flush();
    const events = batches(sent).flatMap((b) => b.events);
    expect(events.map((e) => e.change)).toEqual(['observed', 'muted', 'unmuted', 'ended']);
    expect(events[0]).toMatchObject({ ready: 'live', muted: false, enabled: true, wanted: true });
    expect(events[1]).toMatchObject({ ready: 'live', muted: true });
    expect(events[3]).toMatchObject({ ready: 'ended', muted: false });
  });
  it('sends immediately while the room is up', async () => {
    const { log, sent, setReady } = harness();
    setReady(true);
    log.note('visibility', { state: 'hidden', via: 'visibilitychange' });
    await log.flush();
    expect(sent).toHaveLength(1);
    const [batch] = batches(sent);
    expect(batch.type).toBe('diag');
    expect(batch.v).toBe(1);
    expect(batch.seq).toBe(1);
    expect(batch.dropped).toBe(0);
    expect(batch.events).toHaveLength(1);
    expect(batch.events[0]).toMatchObject({ k: 'visibility', state: 'hidden', via: 'visibilitychange' });
    expect(typeof batch.events[0].t).toBe('number');
    expect(typeof batch.tClient).toBe('number');
  });

  it('queues while the agent is not there and flushes in order on recovery', async () => {
    const { log, sent, setReady } = harness();
    log.note('connection', { kind: 'reconnecting' });
    log.note('mic-track', { change: 'muted', wanted: true, via: 'track' });
    await log.flush();
    expect(sent).toHaveLength(0);

    setReady(true);
    await log.flush();
    expect(sent).toHaveLength(1);
    const [batch] = batches(sent);
    expect(batch.events.map((e) => e.seq)).toEqual([1, 2]);
    expect(batch.events.map((e) => e.k)).toEqual(['connection', 'mic-track']);
    expect(batch.seq).toBe(1);
  });

  it('requeues a failed send and retries it on recovery', async () => {
    let fail = true;
    const { log, sent, setReady } = harness({
      send: async (text: string) => {
        if (fail) throw new Error('room down');
        sent.push(text);
      },
    });
    setReady(true);
    log.note('playback', { allowed: false, ctx: 'suspended', via: 'event' });
    await log.flush();
    expect(sent).toHaveLength(0);
    expect(log.pending()).toBe(1);

    fail = false;
    await log.flush();
    expect(sent).toHaveLength(1);
    expect(batches(sent)[0].events[0]).toMatchObject({ k: 'playback', allowed: false });
    expect(log.pending()).toBe(0);
  });

  it('bounds the queue, drops the oldest first, and reports the count', async () => {
    const { log, sent, setReady } = harness({ maxQueue: 3 });
    for (let i = 0; i < 5; i++) {
      log.note('resume', { step: 'audio', ok: true, code: i === 4 ? 'ok' : 'attempt' });
    }
    await log.flush();
    expect(log.dropped()).toBe(2);
    expect(log.pending()).toBe(3);

    setReady(true);
    await log.flush();
    const [batch] = batches(sent);
    expect(batch.dropped).toBe(2);
    // Oldest two (seq 1, 2) were dropped; the survivors keep their seq.
    expect(batch.events.map((e) => e.seq)).toEqual([3, 4, 5]);
  });

  it('caps a batch so a reconnect storm still fits one message', async () => {
    const { log, sent, setReady } = harness({ maxBatch: 25, maxQueue: 1000 });
    for (let i = 0; i < DIAG_MAX_BATCH + 5; i++) {
      log.note('connection', { kind: 'state', state: 'reconnecting' });
    }
    setReady(true);
    await log.flush();
    expect(sent).toHaveLength(2);
    const [first, second] = batches(sent);
    expect(first.events).toHaveLength(DIAG_MAX_BATCH);
    expect(first.seq).toBe(1);
    expect(second.seq).toBe(DIAG_MAX_BATCH + 1);
    expect(second.events).toHaveLength(5);
  });

  it('rejects unknown kinds and trims hostile fields', async () => {
    const { log, sent, setReady } = harness();
    setReady(true);
    log.note('visibility', {
      state: 'hidden'.padEnd(500, 'x'),
      via: 'visibilitychange',
      // Unknown fields and wrong types never go on the wire:
      evil: 'drop me',
      precise: 'not-a-bool',
    });
    // `as never`: a kind the type system forbids must still die at runtime.
    log.note('totally-new-kind' as never, { state: 'hidden' });
    await log.flush();
    expect(sent).toHaveLength(1);
    const [batch] = batches(sent);
    expect(batch.events).toHaveLength(1);
    const [event] = batch.events;
    expect(event).toMatchObject({ k: 'visibility', via: 'visibilitychange' });
    expect((event.state as string).length).toBeLessThanOrEqual(16);
    expect(event).not.toHaveProperty('evil');
    expect(event).not.toHaveProperty('precise');
  });

  it('never throws or rejects, however hostile the transport', async () => {
    const { log } = harness({
      send: async () => {
        throw new Error('down');
      },
      isReady: () => {
        throw new Error('no room');
      },
      now: () => {
        throw new Error('no clock');
      },
    });
    expect(() => {
      log.note('resume', { step: 'attempt', ok: true, code: 'attempt' });
      log.wakeLock('acquired');
    }).not.toThrow();
    await expect(log.flush()).resolves.toBeUndefined();
  });

  it('offers the wake-lock hook without touching the Wake Lock API', async () => {
    const { log, sent, setReady } = harness();
    setReady(true);
    log.wakeLock('acquired');
    await log.flush();
    expect(batches(sent)[0].events[0]).toMatchObject({ k: 'wakelock', status: 'acquired' });
  });

  it('keeps client time monotonic across a batch', async () => {
    const { log, sent, setReady } = harness();
    setReady(true);
    log.note('visibility', { state: 'hidden', via: 'pagehide' });
    log.note('visibility', { state: 'visible', via: 'pageshow' });
    await log.flush();
    const times = batches(sent).flatMap((b) => b.events.map((e) => e.t));
    expect(times).toHaveLength(2);
    expect(times[1]).toBeGreaterThan(times[0] as number);
  });
});

describe('initialVisibilityState', () => {
  it('reads the latest state when a lesson starts after page load', () => {
    const spy = vi.spyOn(performance, 'getEntriesByType').mockReturnValue([
      { name: 'hidden' }, { name: 'visible' },
    ] as never);
    try {
      expect(initialVisibilityState()).toEqual({ state: 'visible', precise: true });
    } finally {
      spy.mockRestore();
    }
  });
  it('prefers the performance timeline when the browser keeps one', () => {
    const spy = vi.spyOn(performance, 'getEntriesByType').mockReturnValue([{ name: 'hidden' }] as never);
    try {
      expect(initialVisibilityState()).toEqual({ state: 'hidden', precise: true });
    } finally {
      spy.mockRestore();
    }
  });

  it('falls back to the synchronous read (Safari keeps no timeline)', () => {
    const spy = vi.spyOn(performance, 'getEntriesByType').mockReturnValue([]);
    try {
      const { state, precise } = initialVisibilityState();
      expect(precise).toBe(false);
      expect(typeof state).toBe('string');
    } finally {
      spy.mockRestore();
    }
  });
});
