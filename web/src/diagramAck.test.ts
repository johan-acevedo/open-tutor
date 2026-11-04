import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createDiagramAcks } from './diagramAck';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

const settle = async (p: Promise<void>) => p.then(() => 'ok', (e: Error) => e.message);

describe('diagram acknowledgements', () => {
  it('answers only after the revision is drawn', async () => {
    const acks = createDiagramAcks(1000);
    let state = 'pending';
    void acks.wait('b1', 2).then(() => (state = 'ok'));
    acks.rendered('b1', 1);
    await Promise.resolve();
    expect(state).toBe('pending'); // an older revision does not count
    acks.rendered('b1', 2);
    await Promise.resolve();
    expect(state).toBe('ok');
  });

  it('a later revision answers every earlier waiter, other diagrams are untouched', async () => {
    const acks = createDiagramAcks(1000);
    const first = settle(acks.wait('b1', 2));
    const second = settle(acks.wait('b1', 3));
    const other = settle(acks.wait('b2', 1));
    acks.rendered('b1', 3);
    expect(await first).toBe('ok');
    expect(await second).toBe('ok');
    acks.failAll('stop');
    expect(await other).toBe('stop');
  });

  it('reports a failure to every waiter at or below that revision, with the reason', async () => {
    const acks = createDiagramAcks(1000);
    const early = settle(acks.wait('b1', 1));
    const late = settle(acks.wait('b1', 5));
    acks.rendered('b1', 3, 'Ritprogrammet kunde inte laddas.');
    expect(await early).toBe('Ritprogrammet kunde inte laddas.');
    vi.advanceTimersByTime(1000);
    expect(await late).toBe('Diagrammet ritades inte i tid.'); // revision 5 was never reported
  });

  it('never claims success on silence: it times out', async () => {
    const acks = createDiagramAcks(500);
    const waiting = settle(acks.wait('b1', 1));
    vi.advanceTimersByTime(499);
    acks.rendered('b2', 1);
    vi.advanceTimersByTime(2);
    expect(await waiting).toBe('Diagrammet ritades inte i tid.');
  });

  it('a session reset rejects what is waiting and leaves no timers behind', async () => {
    const acks = createDiagramAcks(500);
    const waiting = settle(acks.wait('b1', 1));
    acks.failAll('Sessionen startade om.');
    expect(await waiting).toBe('Sessionen startade om.');
    expect(vi.getTimerCount()).toBe(0);
  });
});
