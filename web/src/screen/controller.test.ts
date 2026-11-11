import { afterEach, describe, expect, it, vi } from 'vitest';
import { createMemoryBlobStore } from './assets';
import { createScreenController, type ScreenControllerOptions } from './controller';
import { createMemoryScreenStore } from './persistence';
import type { CandidatePage, ScreenIntent, ScreenOutboundEvent } from './types';
import type { ScreenWorkerPort, ScreenWorkerToMain } from './worker-protocol';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function waitFor(cond: () => boolean, ms = 2000): Promise<void> {
  const start = Date.now();
  while (!cond()) {
    if (Date.now() - start > ms) throw new Error('waitFor timeout');
    await sleep(5);
  }
}

function candidate(overrides: Partial<CandidatePage> = {}): CandidatePage {
  return {
    id: `p-${overrides.requestSeq ?? 1}`,
    revision: `r${overrides.requestSeq ?? 1}`,
    lessonId: 'lektion-1',
    kind: 'exercise',
    subject: 'Matte',
    title: `Sida ${overrides.requestSeq ?? 1}`,
    body: ['Vad är 1 + 1?'],
    asset: null,
    svgAsset: null,
    answerLabel: 'Ditt svar',
    solution: 'Facit 2',
    sources: [],
    revealed: false,
    createdAt: 1,
    intentId: 'prep-1',
    requestSeq: 1,
    status: 'ready',
    receivedAt: 1,
    ...overrides,
  };
}

function intent(overrides: Partial<ScreenIntent> = {}): ScreenIntent {
  return {
    intentId: 'i1',
    lessonId: 'lektion-1',
    op: 'prepare',
    need: 'bråk',
    viewport: { w: 1280, h: 800, device: 'desktop' },
    ...overrides,
  };
}

interface Fixture {
  events: ScreenOutboundEvent[];
  renders: { pageId: string; draftText: string; pageLabel: string }[];
  store: ReturnType<typeof createMemoryScreenStore>;
  controller: ReturnType<typeof createScreenController>;
  snapshotCount: () => number;
}

function setup(overrides: Partial<ScreenControllerOptions> = {}): Fixture {
  const events: ScreenOutboundEvent[] = [];
  const renders: Fixture['renders'] = [];
  let snapshots = 0;
  let counter = 0;
  const store = createMemoryScreenStore();
  const controller = createScreenController({
    profileId: 'profil',
    learnerName: 'Alicia',
    grade: 'åk 3',
    priorNotes: [],
    room: 'rum',
    accessCode: 'kod',
    lessonId: 'lektion-1',
    createWorker: () => null,
    prepareHandler: async (i, seq) => candidate({ intentId: i.intentId, requestSeq: seq }),
    renderPage: async (_canvas, page, opts) => {
      renders.push({ pageId: page.id, draftText: opts.draftText, pageLabel: opts.pageLabel });
    },
    pixelReader: async () => 'data:image/png;base64,QUJD',
    store,
    blobStore: createMemoryBlobStore(),
    now: () => 1_700_000_000_000,
    newId: (prefix) => `${prefix}-t${(counter += 1)}`,
    renderAckTimeoutMs: 500,
    outstandingShowTimeoutMs: 100,
    onDeckChange: () => {
      snapshots += 1;
    },
    onScreenEvent: (event) => {
      events.push(event);
    },
    ...overrides,
  });
  return { events, renders, store, controller, snapshotCount: () => snapshots };
}

function fakeWorker() {
  const posted: unknown[] = [];
  const port: ScreenWorkerPort = {
    post: (message) => {
      posted.push(message);
    },
    onmessage: null,
    terminate: () => {},
  };
  return { port, posted, emit: (message: ScreenWorkerToMain) => port.onmessage?.(message) };
}

function eventsFor(fixture: Pick<Fixture, 'events'>, intentId: string) {
  return fixture.events.filter((e) => e.intentId === intentId);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('init and resume', () => {
  it('announces a restored page once after rendering so a restarted fox can observe and reveal it', async () => {
    const store = createMemoryScreenStore();
    await store.saveDeck({
      profileId: 'profil', lessonId: 'lektion-1', pages: [candidate()], current: 0,
      drafts: { 'p-1:r1': 'mitt svar' }, updatedAt: 1,
    });
    const h = setup({ store });
    await h.controller.init();
    expect(h.events).toEqual([]);
    h.controller.notifyRendered('p-1', 'r1');
    expect(h.events).toHaveLength(1);
    expect(h.events[0]).toMatchObject({
      type: 'ready', lessonId: 'lektion-1', page: { id: 'p-1', revision: 'r1' },
    });
    h.controller.notifyRendered('p-1', 'r1');
    expect(h.events).toHaveLength(1);
    const observed = await h.controller.captureObservation({
      observationId: 'resume-observe', lessonId: 'lektion-1', pageId: 'p-1', revision: 'r1',
    });
    expect(observed.context.visibleText).toContain('mitt svar');
    expect(observed.context.visibleText).not.toContain('Facit 2');
    expect(observed.context.privateTeaching).toBe('Facit 2');
    await h.controller.handleIntent(intent({
      intentId: 'resume-reveal', op: 'reveal', target: { pageId: 'p-1', revision: 'r1' },
    }));
    h.controller.notifyRendered('p-1', 'r1');
    expect(h.controller.getSnapshot().pages[0].revealed).toBe(true);
    expect(eventsFor(h, 'resume-reveal')).toHaveLength(1);
    await h.controller.close();
  });

  it('starts empty and resumes the interrupted lesson from the same store', async () => {
    const first = setup();
    await first.controller.init();
    await first.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare' }));
    await waitFor(() => eventsFor(first, 'prep-1').length === 1);
    // No canvas attached: show stays held until the external render ack.
    await first.controller.handleIntent(intent({ intentId: 'show-1', op: 'show' }));
    first.controller.notifyRendered('p-1', 'r1');
    await waitFor(() => eventsFor(first, 'show-1').length === 1);
    await first.controller.setAnswerDraft('p-1', 'r1', 'mitt svar');
    await first.controller.close();

    const second = setup({ store: first.store });
    const snapshot = await second.controller.init();
    expect(snapshot.pages).toHaveLength(1);
    expect(snapshot.drafts['p-1:r1']).toBe('mitt svar');
    await second.controller.close();
  });
});

describe('prepare and show', () => {
  it('prepare commits an invisible candidate; the deck stays empty', async () => {
    const h = setup();
    await h.controller.init();
    const ack = await h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare' }));
    expect(ack).toEqual({ accepted: true, intentId: 'prep-1' });
    await waitFor(() => eventsFor(h, 'prep-1').length === 1);
    expect(eventsFor(h, 'prep-1')[0]).toMatchObject({ type: 'ready', page: { id: 'p-1', revision: 'r1' } });
    expect(h.controller.getSnapshot().pages).toHaveLength(0);
    await h.controller.close();
  });

  it('does not emit show-ready at commit time; notifyRendered completes it', async () => {
    const h = setup();
    await h.controller.init();
    await h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare' }));
    await waitFor(() => eventsFor(h, 'prep-1').length === 1);

    const ack = await h.controller.handleIntent(intent({ intentId: 'show-1', op: 'show' }));
    expect(ack.accepted).toBe(true);
    await sleep(30);
    expect(eventsFor(h, 'show-1')).toHaveLength(0); // held: no canvas, no ack yet
    expect(h.controller.getSnapshot().pages).toHaveLength(1); // committed, but not ready

    h.controller.notifyRendered('p-1', 'r1');
    await waitFor(() => eventsFor(h, 'show-1').length === 1);
    expect(eventsFor(h, 'show-1')[0]).toMatchObject({
      type: 'ready',
      page: { id: 'p-1', revision: 'r1' },
    });
    await h.controller.close();
  });

  it('renders into the attached canvas and readies automatically', async () => {
    const h = setup();
    await h.controller.init();
    h.controller.attachCanvas({} as HTMLCanvasElement);
    await h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare' }));
    await waitFor(() => eventsFor(h, 'prep-1').length === 1);
    await h.controller.handleIntent(intent({ intentId: 'show-1', op: 'show' }));
    await waitFor(() => eventsFor(h, 'show-1').length === 1);
    expect(h.renders.length).toBeGreaterThan(0);
    expect(h.renders[h.renders.length - 1]).toMatchObject({
      pageId: 'p-1',
      draftText: '',
      pageLabel: 'Sida 1 av 1',
    });
    await h.controller.close();
  });

  it('an outstanding show promotes when a later candidate arrives', async () => {
    let release!: (c: CandidatePage | null) => void;
    const gate = new Promise<CandidatePage | null>((resolve) => {
      release = resolve;
    });
    const h = setup({
      prepareHandler: () => gate,
    });
    await h.controller.init();
    const run = h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare' }));
    await h.controller.handleIntent(intent({ intentId: 'show-1', op: 'show' }));
    await run;
    await sleep(20);
    expect(eventsFor(h, 'show-1')).toHaveLength(0); // outstanding, no candidate yet
    release(candidate({ intentId: 'prep-1', requestSeq: 1 }));
    await waitFor(() => eventsFor(h, 'prep-1').length === 1);
    await sleep(20); // let the outstanding show promote and hold for render proof
    expect(eventsFor(h, 'show-1')).toHaveLength(0);
    h.controller.notifyRendered('p-1', 'r1');
    await waitFor(() => eventsFor(h, 'show-1').length === 1);
    expect(eventsFor(h, 'show-1')[0]?.type).toBe('ready');
    await h.controller.close();
  });

  it('a show with no candidate lapses into rejected', async () => {
    const h = setup({ prepareHandler: async () => null });
    await h.controller.init();
    await h.controller.handleIntent(intent({ intentId: 'show-1', op: 'show' }));
    await waitFor(() => eventsFor(h, 'show-1').length === 1);
    expect(eventsFor(h, 'show-1')[0]).toMatchObject({ type: 'rejected' });
    await h.controller.close();
  });
});

describe('render failure paths', () => {
  it('failed render settles the intent as failed, never ready', async () => {
    const h = setup({
      renderPage: async () => {
        throw new Error('no-2d');
      },
    });
    await h.controller.init();
    h.controller.attachCanvas({} as HTMLCanvasElement);
    await h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare' }));
    await waitFor(() => eventsFor(h, 'prep-1').length === 1);
    await h.controller.handleIntent(intent({ intentId: 'show-1', op: 'show' }));
    await waitFor(() => eventsFor(h, 'show-1').length === 1);
    expect(eventsFor(h, 'show-1')[0]).toMatchObject({ type: 'failed', reason: 'render-failed' });
    await h.controller.close();
  });

  it('held ready without render proof times out as failed', async () => {
    const h = setup({ renderAckTimeoutMs: 30 });
    await h.controller.init();
    await h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare' }));
    await waitFor(() => eventsFor(h, 'prep-1').length === 1);
    await h.controller.handleIntent(intent({ intentId: 'show-1', op: 'show' }));
    await waitFor(() => eventsFor(h, 'show-1').length === 1);
    expect(eventsFor(h, 'show-1')[0]).toMatchObject({ type: 'failed', reason: 'render-timeout' });
    await h.controller.close();
  });
});

describe('reveal', () => {
  it('reveals, dedupes duplicates and rejects stale targets without touching other pages', async () => {
    const h = setup();
    await h.controller.init();
    h.controller.attachCanvas({} as HTMLCanvasElement);
    await h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare' }));
    await waitFor(() => eventsFor(h, 'prep-1').length === 1);
    await h.controller.handleIntent(intent({ intentId: 'show-1', op: 'show' }));
    await waitFor(() => eventsFor(h, 'show-1').length === 1);

    await h.controller.handleIntent(
      intent({ intentId: 'rev-1', op: 'reveal', target: { pageId: 'p-1', revision: 'r1' } }),
    );
    await waitFor(() => eventsFor(h, 'rev-1').length === 1);
    expect(eventsFor(h, 'rev-1')[0]).toMatchObject({ type: 'ready' });
    expect(h.controller.getSnapshot().pages[0]?.revealed).toBe(true);

    await h.controller.handleIntent(
      intent({ intentId: 'rev-2', op: 'reveal', target: { pageId: 'p-1', revision: 'r1' } }),
    );
    await waitFor(() => eventsFor(h, 'rev-2').length === 1);
    expect(eventsFor(h, 'rev-2')[0]?.type).toBe('ready');

    await h.controller.handleIntent(
      intent({ intentId: 'rev-3', op: 'reveal', target: { pageId: 'p-1', revision: 'r0' } }),
    );
    await waitFor(() => eventsFor(h, 'rev-3').length === 1);
    expect(eventsFor(h, 'rev-3')[0]).toMatchObject({ type: 'rejected' });
    await h.controller.close();
  });
});

describe('drafts and submission', () => {
  it('shares drafts only through answer-submitted and survives navigation', async () => {
    const h = setup();
    await h.controller.init();
    h.controller.attachCanvas({} as HTMLCanvasElement);
    await h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare', need: 'ett' }));
    await h.controller.handleIntent(intent({ intentId: 'prep-2', op: 'prepare', need: 'två' }));
    await waitFor(() => eventsFor(h, 'prep-2').length === 1);
    await h.controller.handleIntent(intent({ intentId: 'show-1', op: 'show', need: 'ett' }));
    await waitFor(() => eventsFor(h, 'show-1').length === 1);
    await h.controller.setAnswerDraft('p-1', 'r1', 'mitt svar');
    await h.controller.goTo(0);
    expect(h.controller.getSnapshot().drafts['p-1:r1']).toBe('mitt svar');
    await h.controller.submitAnswer('p-1', 'r1');
    const submitted = h.events.filter((e) => e.type === 'answer-submitted');
    expect(submitted).toHaveLength(1);
    expect(submitted[0]).toMatchObject({ answer: 'mitt svar', page: { id: 'p-1', revision: 'r1' } });
    await expect(h.controller.submitAnswer('p-1', 'r9')).rejects.toThrow('stale-page');
    await h.controller.close();
  });
});

describe('observation', () => {
  it('reads pixels without persisting them and rejects overlaps', async () => {
    let release!: (v: string) => void;
    const gate = new Promise<string>((resolve) => {
      release = resolve;
    });
    const h = setup({ pixelReader: () => gate });
    await h.controller.init();
    await h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare' }));
    await waitFor(() => eventsFor(h, 'prep-1').length === 1);
    await h.controller.handleIntent(intent({ intentId: 'show-1', op: 'show' }));
    await waitFor(() => eventsFor(h, 'show-1').length === 1);
    await h.controller.setAnswerDraft('p-1', 'r1', 'abc');

    // Observation PNGs are transient: capturing must not touch the deck store.
    let saveCalls = 0;
    const originalSave = h.store.saveDeck.bind(h.store);
    h.store.saveDeck = async (snapshot) => {
      saveCalls += 1;
      return originalSave(snapshot);
    };
    const pending = h.controller.captureObservation({
      observationId: 'o1',
      lessonId: 'lektion-1',
      pageId: 'p-1',
      revision: 'r1',
    });
    await expect(
      h.controller.captureObservation({ observationId: 'o2', lessonId: 'lektion-1', pageId: 'p-1', revision: 'r1' }),
    ).rejects.toThrow('observation-busy');
    release('data:image/png;base64,QUJD');
    const result = await pending;
    expect(saveCalls).toBe(0);
    expect(result.pngBase64).toBe('QUJD');
    expect(result.context.page).toEqual({ id: 'p-1', revision: 'r1' });
    expect(result.context.lessonId).toBe('lektion-1');
    expect(result.context.viewport).toMatchObject({ w: 1280, h: 800, device: 'desktop' });
    expect(result.context.answerState).toMatchObject({ hasDraft: true, draftLength: 3 });
    expect(result.context.visibleText).toContain('Sida');
    await expect(
      h.controller.captureObservation({ observationId: 'o3', lessonId: 'lektion-1', pageId: 'p-1', revision: 'r0' }),
    ).rejects.toThrow('stale-observation');
    await expect(
      h.controller.captureObservation({ observationId: 'o4', lessonId: 'annan-lektion', pageId: 'p-1', revision: 'r1' }),
    ).rejects.toThrow('lesson-mismatch');
    await h.controller.close();
  });
});

describe('intent registry', () => {
  it('replays duplicate intents and rejects foreign lessons', async () => {
    const h = setup();
    await h.controller.init();
    await h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare' }));
    await waitFor(() => eventsFor(h, 'prep-1').length === 1);
    const ack = await h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare' }));
    expect(ack.accepted).toBe(true);
    expect(eventsFor(h, 'prep-1')).toHaveLength(2);
    const foreign = await h.controller.handleIntent(intent({ intentId: 'x', lessonId: 'annan' }));
    expect(foreign).toMatchObject({ accepted: false, reason: 'lesson-mismatch' });
    const unknown = await h.controller.handleIntent(intent({ intentId: 'u', op: 'focus' as never }));
    expect(unknown.accepted).toBe(false);
    await h.controller.close();
  });
});

describe('supersession', () => {
  it('a newer intent supersedes an older pending background result', async () => {
    const resolvers = new Map<number, (c: CandidatePage | null) => void>();
    const h = setup({
      prepareHandler: (_intent, seq) =>
        new Promise<CandidatePage | null>((resolve) => {
          resolvers.set(seq, resolve);
        }),
    });
    await h.controller.init();
    void h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare', need: 'sverige' }));
    void h.controller.handleIntent(intent({ intentId: 'prep-2', op: 'prepare', need: 'sverige' }));
    await sleep(10);
    // Newer (seq 2) finishes first, older (seq 1) second and must lose.
    resolvers.get(2)?.(candidate({ intentId: 'prep-2', requestSeq: 2, title: 'Ny' }));
    await waitFor(() => eventsFor(h, 'prep-2').length === 1);
    resolvers.get(1)?.(candidate({ intentId: 'prep-1', requestSeq: 1, title: 'Gammal' }));
    await waitFor(() => eventsFor(h, 'prep-1').length === 1);
    expect(eventsFor(h, 'prep-1')[0]).toMatchObject({ type: 'rejected', reason: 'superseded' });
    await h.controller.handleIntent(intent({ intentId: 'show-1', op: 'show', need: 'sverige' }));
    h.controller.notifyRendered('p-2', 'r2');
    await waitFor(() => eventsFor(h, 'show-1').length === 1);
    expect(h.controller.getSnapshot().pages[0]?.title).toBe('Ny');
    await h.controller.close();
  });
});

describe('new lessons', () => {
  it('archives, clears candidates and never promotes across lessons', async () => {
    const h = setup();
    await h.controller.init();
    await h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare' }));
    await waitFor(() => eventsFor(h, 'prep-1').length === 1);
    await h.controller.handleIntent(intent({ intentId: 'show-1', op: 'show' }));
    h.controller.notifyRendered('p-1', 'r1');
    await waitFor(() => eventsFor(h, 'show-1').length === 1);

    await h.controller.startNewLesson('lektion-2');
    expect(h.controller.getSnapshot().pages).toHaveLength(0);
    expect(await h.store.loadSummaries('profil')).toHaveLength(1);

    // Stale intents for the old lesson are rejected; new-lesson shows find nothing.
    const stale = await h.controller.handleIntent(intent({ intentId: 'old', lessonId: 'lektion-1' }));
    expect(stale.accepted).toBe(false);
    await h.controller.handleIntent(intent({ intentId: 'show-2', lessonId: 'lektion-2', op: 'show' }));
    await waitFor(() => eventsFor(h, 'show-2').length === 1);
    expect(eventsFor(h, 'show-2')[0]?.type).toBe('rejected');
    await h.controller.close();
  });
});

describe('worker candidates with researched images', () => {
  it('downloads, verifies and stores the researched bytes; the doc keeps only the ref', async () => {
    const worker = fakeWorker();
    const blobStore = createMemoryBlobStore();
    const h = setup({
      prepareHandler: undefined,
      createWorker: () => worker.port,
      blobStore,
    });
    await h.controller.init();
    await h.controller.handleIntent(intent({ intentId: 'prep-geo', op: 'prepare', need: 'Sveriges landskap' }));
    expect(worker.posted[0]).toMatchObject({ kind: 'init' });
    // Worker prepares queue until Harness boot completes (no rootHandle race).
    expect(worker.posted).toHaveLength(1);
    worker.emit({ kind: 'harness-ready' });
    await waitFor(() => worker.posted.length >= 2);
    expect(worker.posted[1]).toMatchObject({ kind: 'prepare' });

    const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x99]);
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(png, { status: 200, headers: { 'Content-Type': 'image/png' } })),
    );
    worker.emit({
      kind: 'candidate',
      candidate: candidate({
        id: 'geo-1',
        revision: 'rg1',
        kind: 'geography',
        subject: 'Geografi',
        intentId: 'prep-geo',
        requestSeq: 1,
      }),
      artifacts: [],
      researchImage: { url: 'https://upload.wikimedia.org/map.png', attribution: 'Wikimedia' },
    });
    await waitFor(() => eventsFor(h, 'prep-geo').length === 1);
    await h.controller.handleIntent(intent({ intentId: 'show-geo', op: 'show', need: 'Sveriges landskap' }));
    h.controller.notifyRendered('geo-1', 'rg1');
    await waitFor(() => eventsFor(h, 'show-geo').length === 1);
    const promoted = h.controller.getSnapshot().pages[0];
    expect(promoted?.asset?.status).toBe('ready');
    expect(promoted?.asset?.provenance).toBe('Wikimedia');
    expect(await blobStore.has(promoted?.asset?.id ?? '')).toBe(true);
    await h.controller.close();
  });
});

describe('show starts preparation', () => {
  it('a show with no candidate starts prepare itself and auto-promotes the match', async () => {
    const seen: Array<{ intentId: string; seq: number }> = [];
    const h = setup({
      prepareHandler: async (i, seq) => {
        seen.push({ intentId: i.intentId, seq });
        // prepareHandler runs for the synthetic auto-prepare; produce a candidate
        return candidate({ intentId: i.intentId, requestSeq: seq, title: `Auto ${seq}` });
      },
      outstandingShowTimeoutMs: 2000,
    });
    await h.controller.init();
    // No prior prepare: show alone must kick off preparation using its need.
    await h.controller.handleIntent(intent({ intentId: 'show-only', op: 'show', need: 'bråk' }));
    await waitFor(() => seen.length >= 1, 2000);
    expect(seen[0]?.intentId).toContain('show-only');
    // The matching candidate auto-promotes without a second show request.
    // No canvas is attached, so the commit lands first and ready follows the
    // external render ack (no 60s wait for work that was never started).
    await waitFor(() => h.controller.getSnapshot().pages.length === 1, 2000);
    expect(eventsFor(h, 'show-only')).toHaveLength(0);
    const page = h.controller.getSnapshot().pages[0];
    expect(page).toBeDefined();
    h.controller.notifyRendered(page!.id, page!.revision);
    await waitFor(() => eventsFor(h, 'show-only').length === 1, 2000);
    // The synthetic prepare itself stays invisible (no extra ready for it).
    expect(h.events.filter((e) => e.intentId?.endsWith(':auto-prepare'))).toHaveLength(0);
    expect(eventsFor(h, 'show-only')[0]).toMatchObject({ type: 'ready' });
    await h.controller.close();
  });

  it('prepare-only stays invisible (no auto-promotion without an outstanding show)', async () => {
    const h = setup();
    await h.controller.init();
    await h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare' }));
    await waitFor(() => eventsFor(h, 'prep-1').length === 1);
    expect(h.controller.getSnapshot().pages).toHaveLength(0);
    expect(eventsFor(h, 'prep-1')[0]).toMatchObject({ type: 'ready' });
    await h.controller.close();
  });

  it('show settles exactly once after promote+render, never at commit (canvas ordering)', async () => {
    let releaseRender!: () => void;
    const renderGate = new Promise<void>((resolve) => {
      releaseRender = resolve;
    });
    const h = setup({
      prepareHandler: async (i, seq) => candidate({ intentId: i.intentId, requestSeq: seq }),
      renderPage: async () => {
        await renderGate;
      },
    });
    await h.controller.init();
    h.controller.attachCanvas({} as HTMLCanvasElement);
    await h.controller.handleIntent(intent({ intentId: 'show-canvas', op: 'show', need: 'bråk' }));
    // Candidate commit promotes the page but must NOT settle show ready yet:
    // actual-pixels ready fires only after the canvas render completes.
    await waitFor(() => h.controller.getSnapshot().pages.length === 1, 2000);
    await sleep(30);
    expect(eventsFor(h, 'show-canvas')).toHaveLength(0);
    releaseRender();
    await waitFor(() => eventsFor(h, 'show-canvas').length === 1, 2000);
    await sleep(30);
    // Exactly one ready — no premature commit-ready plus a second render-ready.
    expect(eventsFor(h, 'show-canvas')).toHaveLength(1);
    expect(eventsFor(h, 'show-canvas')[0]).toMatchObject({ type: 'ready' });
    await h.controller.close();
  });
});

describe('worker boot ordering', () => {
  it('queues worker prepares until harness-ready, then flushes in order', async () => {
    const worker = fakeWorker();
    const h = setup({
      prepareHandler: undefined,
      createWorker: () => worker.port,
    });
    await h.controller.init();
    await h.controller.handleIntent(intent({ intentId: 'prep-1', op: 'prepare', need: 'ett' }));
    await h.controller.handleIntent(intent({ intentId: 'prep-2', op: 'prepare', need: 'två' }));
    await sleep(20);
    // Nothing leaves the main thread before the worker signals readiness.
    expect(worker.posted.filter((m) => (m as { kind: string }).kind === 'prepare')).toHaveLength(0);
    worker.emit({ kind: 'harness-ready' });
    await waitFor(
      () => worker.posted.filter((m) => (m as { kind: string }).kind === 'prepare').length === 2,
    );
    const prepares = worker.posted.filter((m) => (m as { kind: string }).kind === 'prepare') as Array<{
      kind: string;
      intent: ScreenIntent;
      seq: number;
    }>;
    expect(prepares[0]?.seq).toBeLessThan(prepares[1]?.seq ?? 99);
    await h.controller.close();
  });
});

describe('asset candidate ingestion (real geography path)', () => {
  it('accepts and verifies a raw candidate.asset with no external download', async () => {
    const blobStore = createMemoryBlobStore();
    const fetchSpy = vi.fn(async () => {
      throw new Error('must not fetch for the real asset path');
    });
    vi.stubGlobal('fetch', fetchSpy);
    const h = setup({ prepareHandler: undefined, createWorker: () => null, blobStore });
    await h.controller.init();
    // Pre-store researched bytes as the worker would (shared per-profile blob store).
    const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x42]);
    const assetId = 'b-real-1';
    await blobStore.put(assetId, png, {
      mimeType: 'image/png',
      provenance: 'Wikimedia:File:Sverige.png',
      lessonId: 'lektion-1',
    });
    const record = await blobStore.get(assetId);
    const ref = {
      id: assetId,
      hash: record!.hash,
      mimeType: 'image/png',
      provenance: 'Wikimedia:File:Sverige.png',
      lessonId: 'lektion-1',
      status: 'ready' as const,
      attribution: 'Wikimedia Commons',
    };
    // Inject the worker-produced candidate directly with its validated ref.
    const { createScreenController: _unused } = await import('./controller');
    void _unused;
    // Simulate ingestion via a prepare handler that returns the asset-bearing candidate.
    const h2 = setup({
      prepareHandler: async (i, seq) => ({
        id: 'geo-real',
        revision: 'rgeo1',
        lessonId: 'lektion-1',
        kind: 'geography' as const,
        subject: 'Geografi',
        title: 'Sverige',
        body: ['Var ligger Sverige?'],
        asset: ref,
        svgAsset: '<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>',
        answerLabel: 'Ditt svar',
        solution: 'I Norden',
        sources: ['Wikimedia Commons'],
        revealed: false,
        createdAt: 1,
        intentId: i.intentId,
        requestSeq: seq,
      }),
      createWorker: () => null,
      blobStore,
    });
    await h2.controller.init();
    await h2.controller.handleIntent(intent({ intentId: 'prep-real', op: 'prepare', need: 'Sverige' }));
    await waitFor(() => eventsFor(h2, 'prep-real').length === 1);
    await h2.controller.handleIntent(intent({ intentId: 'show-real', op: 'show', need: 'Sverige' }));
    h2.controller.notifyRendered('geo-real', 'rgeo1');
    await waitFor(() => eventsFor(h2, 'show-real').length === 1);
    const promoted = h2.controller.getSnapshot().pages[0];
    expect(promoted?.asset?.id).toBe(assetId);
    expect(promoted?.asset?.hash).toBe(record!.hash);
    expect(fetchSpy).not.toHaveBeenCalled();
    await h.controller.close();
    await h2.controller.close();
  });

  it('rejects an invalid asset ref and keeps the SVG fallback', async () => {
    const blobStore = createMemoryBlobStore();
    const h = setup({
      prepareHandler: async (i, seq) => ({
        id: 'geo-bad',
        revision: 'rbad1',
        lessonId: 'lektion-1',
        kind: 'geography' as const,
        subject: 'Geografi',
        title: 'Norden',
        body: ['Vilka länder ingår?'],
        asset: {
          id: 'missing-blob',
          hash: 'a'.repeat(64),
          mimeType: 'image/png',
          provenance: 'bogus',
          lessonId: 'lektion-1',
          status: 'ready' as const,
        },
        svgAsset: '<svg xmlns=\"http://www.w3.org/2000/svg\"><circle cx=\"5\" cy=\"5\" r=\"4\"/></svg>',
        answerLabel: 'Ditt svar',
        solution: 'Sverige, Norge, Danmark',
        sources: [],
        revealed: false,
        createdAt: 1,
        intentId: i.intentId,
        requestSeq: seq,
      }),
      createWorker: () => null,
      blobStore,
    });
    await h.controller.init();
    await h.controller.handleIntent(intent({ intentId: 'prep-bad', op: 'prepare', need: 'Norden' }));
    await waitFor(() => eventsFor(h, 'prep-bad').length === 1);
    // Invalid ref without a stored blob must not promote an asset; SVG fallback survives.
    await h.controller.handleIntent(intent({ intentId: 'show-bad', op: 'show', need: 'Norden' }));
    h.controller.notifyRendered('geo-bad', 'rbad1');
    await waitFor(() => eventsFor(h, 'show-bad').length === 1);
    const promoted = h.controller.getSnapshot().pages[0];
    expect(promoted?.asset).toBeNull();
    expect(promoted?.svgAsset).toContain('<circle');
    await h.controller.close();
  });
});
