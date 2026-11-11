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
    const pending = h.controller.captureObservation({ observationId: 'o1', pageId: 'p-1', revision: 'r1' });
    await expect(
      h.controller.captureObservation({ observationId: 'o2', pageId: 'p-1', revision: 'r1' }),
    ).rejects.toThrow('observation-busy');
    release('data:image/png;base64,QUJD');
    const result = await pending;
    expect(saveCalls).toBe(0);
    expect(result.pngBase64).toBe('QUJD');
    expect(result.context.page).toEqual({ id: 'p-1', revision: 'r1' });
    expect(result.context.answerState).toMatchObject({ hasDraft: true, draftLength: 3 });
    await expect(
      h.controller.captureObservation({ observationId: 'o3', pageId: 'p-1', revision: 'r0' }),
    ).rejects.toThrow('stale-observation');
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
