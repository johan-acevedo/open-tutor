import { describe, expect, it } from 'vitest';
import { createMemoryBlobStore, isAssetRefUsable, validateAssetRef, verifyBlobBytes } from './assets';
import { createScreenController, type ScreenControllerOptions } from './controller';
import { createMemoryScreenStore } from './persistence';
import { drawScreenPage } from './renderer';
import type { ScreenOutboundEvent, ScreenPage } from './types';

function mockContext() {
  const texts: { text: string; font: string }[] = [];
  const draws: string[] = [];
  let font = '400 16px sans-serif';
  const ctx = new Proxy(
    {},
    {
      get(_target, prop) {
        if (prop === 'font') return font;
        if (prop === 'measureText') return (text: string) => ({ width: text.length * 10 });
        if (prop === 'createLinearGradient') return () => ({ addColorStop() {} });
        if (prop === 'fillText') {
          return (text: string) => {
            texts.push({ text, font });
          };
        }
        if (prop === 'drawImage') {
          return (..._args: unknown[]) => {
            draws.push('drawImage');
          };
        }
        return (..._args: unknown[]) => undefined;
      },
      set(_target, prop, value) {
        if (prop === 'font') font = value as string;
        return true;
      },
    },
  );
  return { ctx: ctx as unknown as CanvasRenderingContext2D, texts, draws };
}

function setup(overrides: Partial<ScreenControllerOptions> = {}) {
  const events: ScreenOutboundEvent[] = [];
  const renders: { pageId: string }[] = [];
  let snapshots = 0;
  let counter = 0;
  const store = createMemoryScreenStore();
  const blobStore = createMemoryBlobStore();
  const controller = createScreenController({
    profileId: 'profil',
    learnerName: 'Alicia',
    grade: 'åk 3',
    priorNotes: [],
    room: 'rum',
    accessCode: 'kod',
    lessonId: 'lektion-1',
    createWorker: () => null,
    renderPage: async (_canvas, page) => {
      renders.push({ pageId: page.id });
    },
    pixelReader: async () => 'data:image/png;base64,QUJD',
    store,
    blobStore,
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
  return { events, renders, store, blobStore, controller, snapshotCount: () => snapshots };
}

const PNG = (extra = 0x99) =>
  new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, extra]);

describe('addHomeworkPage: image homework', () => {
  it('becomes immediately visible, persists, verifies blobs and fabricates no fox event', async () => {
    const h = setup();
    await h.controller.init();
    h.controller.attachCanvas({} as HTMLCanvasElement);
    const beforeEvents = h.events.length;
    const beforeSnapshots = h.snapshotCount();

    const snapshot = await h.controller.addHomeworkPage({
      title: 'Läxa matte',
      text: 'Räkna 7 + 5',
      images: [{ bytes: PNG(), mimeType: 'image/png', provenance: 'upload:foto.jpg' }],
    });

    // Visible immediately as ordinary homework page, latest selected.
    expect(snapshot.pages).toHaveLength(1);
    expect(h.controller.getSnapshot().pages).toHaveLength(1);
    const page = snapshot.pages[0]!;
    expect(page.kind).toBe('homework');
    expect(page.title).toBe('Läxa matte');
    expect(page.lessonId).toBe('lektion-1');
    expect(page.id).toBeTruthy();
    expect(page.revision).toBeTruthy();
    expect(page.body.join('\n')).toContain('Räkna 7 + 5');
    expect(page.solution).toBe('');
    expect(page.asset?.status).toBe('ready');
    expect(page.asset?.lessonId).toBe('lektion-1');
    expect(page.asset?.provenance).toBe('upload:foto.jpg');
    expect(h.controller.getSnapshot().current).toBe(0);
    // Persists + publishes + renders.
    expect(h.snapshotCount()).toBeGreaterThan(beforeSnapshots);
    expect(h.renders.length).toBeGreaterThan(0);
    // Blob bytes verified: stored, hashed, usable.
    const record = await h.blobStore.get(page.asset!.id);
    expect(record).not.toBeNull();
    expect(Array.from(record!.bytes)).toEqual(Array.from(PNG()));
    expect(record!.hash).toBe(page.asset!.hash);
    expect(validateAssetRef(page.asset!).length).toBe(0);
    expect(isAssetRefUsable(page.asset!, 'lektion-1')).toBe(true);
    expect(await verifyBlobBytes(PNG(), { hash: record!.hash, mimeType: 'image/png' })).toMatchObject({ ok: true });
    // No fox ready / answer-submitted event is fabricated.
    expect(h.events.length).toBe(beforeEvents);
    expect(h.events.filter((e) => e.type === 'ready')).toHaveLength(0);
    expect(h.events.filter((e) => e.type === 'answer-submitted')).toHaveLength(0);
    // Deck store actually persisted the visible page.
    const stored = await h.store.loadDeck('profil', 'lektion-1');
    expect(stored?.pages).toHaveLength(1);
    expect(stored?.pages[0]?.kind).toBe('homework');
    await h.controller.close();
  });

  it('multiple images produce navigable pages with the latest selected', async () => {
    const h = setup();
    await h.controller.init();
    // Attach a canvas so navigation re-renders silently.
    h.controller.attachCanvas({} as HTMLCanvasElement);
    await h.controller.addHomeworkPage({
      title: 'Läxa sidor',
      images: [
        { bytes: PNG(0x01), mimeType: 'image/png', provenance: 'pdf:sida-1' },
        { bytes: PNG(0x02), mimeType: 'image/png', provenance: 'pdf:sida-2' },
      ],
    });
    const snap = h.controller.getSnapshot();
    expect(snap.pages).toHaveLength(2);
    expect(snap.pages[0]?.kind).toBe('homework');
    expect(snap.pages[1]?.kind).toBe('homework');
    expect(snap.pages[0]?.asset?.provenance).toBe('pdf:sida-1');
    expect(snap.pages[1]?.asset?.provenance).toBe('pdf:sida-2');
    expect(snap.current).toBe(1);
    expect(snap.pages[0]?.id).not.toBe(snap.pages[1]?.id);
    // Navigable.
    await h.controller.goTo(0);
    expect(h.controller.getSnapshot().current).toBe(0);
    await h.controller.goTo(1);
    expect(h.controller.getSnapshot().current).toBe(1);
    // Blobs for both pages.
    for (const page of snap.pages) {
      expect(await h.blobStore.has(page.asset!.id)).toBe(true);
    }
    // Still no fabricated fox events.
    expect(h.events.filter((e) => e.type === 'ready')).toHaveLength(0);
    expect(h.events.filter((e) => e.type === 'answer-submitted')).toHaveLength(0);
    await h.controller.close();
  });

  it('pasted text produces a text-only homework page', async () => {
    const h = setup();
    await h.controller.init();
    const snapshot = await h.controller.addHomeworkPage({
      title: 'Läxa text',
      text: 'Läs sidan 12\nSvara på fråga 3',
    });
    expect(snapshot.pages).toHaveLength(1);
    const page = snapshot.pages[0]!;
    expect(page.kind).toBe('homework');
    expect(page.asset).toBeNull();
    expect(page.svgAsset).toBeNull();
    expect(page.body.join('\n')).toContain('Läs sidan 12');
    expect(page.body.join('\n')).toContain('Svara på fråga 3');
    expect(h.events).toHaveLength(0);
    await h.controller.close();
  });

  it('resumes homework on the same lesson after a restart', async () => {
    const first = setup();
    await first.controller.init();
    await first.controller.addHomeworkPage({
      title: 'Läxa resume',
      text: 'Kom ihåg boken',
      images: [{ bytes: PNG(0x07), mimeType: 'image/png', provenance: 'upload:resume.jpg' }],
    });
    await first.controller.close();
    // Same profile+lesson store, fresh controller + fresh blob view of same store.
    const second = setup({ store: first.store, blobStore: first.blobStore });
    const resumed = await second.controller.init();
    expect(resumed.pages).toHaveLength(1);
    expect(resumed.pages[0]?.kind).toBe('homework');
    expect(resumed.pages[0]?.title).toBe('Läxa resume');
    await second.controller.close();
  });

  it('rejects empty input without touching the deck', async () => {
    const h = setup();
    await h.controller.init();
    await expect(h.controller.addHomeworkPage({ title: '   ' })).rejects.toThrow('homework-title-required');
    await expect(h.controller.addHomeworkPage({ title: 'Ok', text: '   ' })).rejects.toThrow('homework-needs-content');
    expect(h.controller.getSnapshot().pages).toHaveLength(0);
    await h.controller.close();
  });
});

describe('homework renderer', () => {
  it('shows the uploaded image contain-fit with attribution and no answer/facit areas', () => {
    const { ctx, texts, draws } = mockContext();
    const page: ScreenPage = {
      id: 'hw1',
      revision: 'hr1',
      lessonId: 'lektion-1',
      kind: 'homework',
      subject: 'Läxa',
      title: 'Min läxa',
      body: ['Räkna 7 + 5 och visa hur du tänkte.'],
      asset: {
        id: 'b1',
        hash: 'a'.repeat(64),
        mimeType: 'image/png',
        provenance: 'upload:foto.jpg',
        lessonId: 'lektion-1',
        status: 'ready',
        attribution: 'Mammas foto',
      },
      svgAsset: null,
      answerLabel: '',
      solution: '',
      sources: ['upload:foto.jpg'],
      revealed: false,
      createdAt: 1,
    };
    const fakeDrawable = { width: 400, height: 200 } as unknown as CanvasImageSource;
    drawScreenPage(ctx, { w: 1280, h: 800 }, page, {
      images: new Map([['b1', fakeDrawable]]),
      pageLabel: 'Sida 1 av 1',
    });
    const drawn = texts.map((t) => t.text).join('\n');
    expect(drawn).toContain('Min läxa');
    expect(drawn).toContain('Räkna 7 + 5');
    expect(drawn).toContain('Mammas foto');
    expect(draws).toContain('drawImage');
    // No exercise answer box or hidden facit.
    expect(drawn).not.toContain('Ditt svar');
    expect(drawn).not.toContain('Skriv ditt svar');
    expect(drawn).not.toContain('Facit är dolt');
    expect(drawn).not.toContain('Facit');
    expect(drawn).not.toMatch(/laddas/);
  });

  it('never shows a permanent loading placeholder when the drawable is missing', () => {
    const { ctx, texts, draws } = mockContext();
    const page: ScreenPage = {
      id: 'hw2',
      revision: 'hr2',
      lessonId: 'lektion-1',
      kind: 'homework',
      subject: 'Läxa',
      title: 'Läxa utan drawable',
      body: ['Texten syns ändå.'],
      asset: {
        id: 'b-missing',
        hash: 'b'.repeat(64),
        mimeType: 'image/png',
        provenance: 'upload:foto2.jpg',
        lessonId: 'lektion-1',
        status: 'ready',
        attribution: 'Pappas foto',
      },
      svgAsset: null,
      answerLabel: '',
      solution: '',
      sources: [],
      revealed: false,
      createdAt: 1,
    };
    drawScreenPage(ctx, { w: 1280, h: 800 }, page, { images: new Map(), pageLabel: 'Sida 1 av 1' });
    const drawn = texts.map((t) => t.text).join('\n');
    expect(drawn).toContain('Texten syns ändå.');
    expect(drawn).not.toMatch(/laddas/);
    expect(draws).not.toContain('drawImage');
    expect(drawn).not.toContain('Facit är dolt');
    expect(drawn).not.toContain('Ditt svar');
  });

  it('text-only homework draws content with no answer/facit areas', () => {
    const { ctx, texts } = mockContext();
    const page: ScreenPage = {
      id: 'hw3',
      revision: 'hr3',
      lessonId: 'lektion-1',
      kind: 'homework',
      subject: 'Läxa',
      title: 'Läs läxa',
      body: ['Läs sidan 12.', 'Svara på fråga 3.'],
      asset: null,
      svgAsset: null,
      answerLabel: '',
      solution: '',
      sources: [],
      revealed: false,
      createdAt: 1,
    };
    drawScreenPage(ctx, { w: 1280, h: 800 }, page, { pageLabel: 'Sida 1 av 1' });
    const drawn = texts.map((t) => t.text).join('\n');
    expect(drawn).toContain('Läs sidan 12.');
    expect(drawn).not.toContain('Ditt svar');
    expect(drawn).not.toContain('Facit är dolt');
  });
});
