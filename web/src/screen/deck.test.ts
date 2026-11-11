import { describe, expect, it } from 'vitest';
import {
  addCandidate,
  applyDraft,
  applyReveal,
  createEmptyDeck,
  currentPage,
  findPromotionCandidate,
  getIntentOutcome,
  goToIndex,
  needKey,
  promoteCandidate,
  registerIntent,
  settleIntent,
  shouldResumeDeck,
  startNewLesson,
  type CandidateStore,
} from './deck';
import type { CandidatePage, ScreenIntent } from './types';

const NOW = 1_700_000_000_000;

function page(overrides: Partial<CandidatePage> = {}): CandidatePage {
  return {
    id: 'p1',
    revision: 'r1',
    lessonId: 'lektion-1',
    kind: 'exercise',
    subject: 'Matte',
    title: 'Bråk',
    body: ['Vad är 1/2 + 1/4?'],
    asset: null,
    svgAsset: null,
    answerLabel: 'Ditt svar',
    solution: '3/4',
    sources: [],
    revealed: false,
    createdAt: NOW,
    intentId: 'i1',
    requestSeq: 1,
    status: 'ready',
    receivedAt: NOW,
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

describe('needKey', () => {
  it('normalises need and background for matching', () => {
    expect(needKey({ need: ' Bråk ', background: 'ÅK 3' })).toBe('bråk\nåk 3');
    expect(needKey({})).toBe('\n');
  });
});

describe('candidate store', () => {
  it('a newer candidate for the same need supersedes the older one', () => {
    const store: CandidateStore = new Map();
    addCandidate(store, page({ id: 'p1', intentId: 'i1', requestSeq: 1 }), () => 'bråk\n');
    const { supersededIds } = addCandidate(store, page({ id: 'p2', intentId: 'i2', requestSeq: 2 }), () => 'bråk\n');
    expect(store.get('i1:p1')?.status).toBe('superseded');
    expect(store.get('i2:p2')?.status).toBe('ready');
    expect(supersededIds).toEqual(['i1:p1']);
  });

  it('candidates for other needs or lessons are left alone', () => {
    const store: CandidateStore = new Map();
    addCandidate(store, page({ id: 'p1', intentId: 'i1', requestSeq: 1, lessonId: 'lektion-1' }), () => 'bråk\n');
    addCandidate(store, page({ id: 'p2', intentId: 'i2', requestSeq: 2, lessonId: 'lektion-2' }), () => 'bråk\n');
    expect(store.get('i1:p1')?.status).toBe('ready');
    expect(store.get('i2:p2')?.status).toBe('ready');
  });
});

describe('findPromotionCandidate', () => {
  it('prefers the newest ready candidate for the same intent', () => {
    const store: CandidateStore = new Map();
    addCandidate(store, page({ id: 'p1', intentId: 'i1', requestSeq: 1 }), () => 'bråk\n');
    const show = intent({ intentId: 'show-1', op: 'show', need: 'bråk' });
    const needs = new Map([['i1', needKey(intent({ need: 'bråk' }))]]);
    expect(findPromotionCandidate(store, show, needs)?.id).toBe('p1');
  });

  it('matches by normalised need across intents', () => {
    const store: CandidateStore = new Map();
    addCandidate(store, page({ id: 'p1', intentId: 'prep-9', requestSeq: 1 }), () => 'bråk\n');
    const show = intent({ intentId: 'show-1', op: 'show', need: 'BRÅK' });
    const needs = new Map([['prep-9', 'bråk\n']]);
    expect(findPromotionCandidate(store, show, needs)?.id).toBe('p1');
  });

  it('ignores superseded, discarded, promoted and foreign-lesson candidates', () => {
    const store: CandidateStore = new Map();
    addCandidate(store, page({ id: 'old', intentId: 'i0', requestSeq: 1 }), () => 'bråk\n');
    addCandidate(store, page({ id: 'new', intentId: 'i1', requestSeq: 2 }), () => 'bråk\n');
    const old = store.get('i0:old');
    if (old) old.status = 'discarded';
    const other = page({ id: 'foreign', intentId: 'i2', requestSeq: 5, lessonId: 'lektion-2' });
    other.status = 'ready';
    store.set('i2:foreign', other);
    const show = intent({ intentId: 'show-1', op: 'show', need: 'bråk' });
    const needs = new Map([
      ['i0', 'bråk\n'],
      ['i1', 'bråk\n'],
      ['i2', 'bråk\n'],
    ]);
    // i0:old was superseded by i1:new, i2:foreign is another lesson
    expect(findPromotionCandidate(store, show, needs)?.id).toBe('new');
  });
});

describe('promoteCandidate', () => {
  it('appends the candidate as a hidden visible page', () => {
    const deck = createEmptyDeck('profil', 'lektion-1', NOW);
    const produced = page();
    const next = promoteCandidate(deck, produced, NOW + 1);
    expect(next.pages).toHaveLength(1);
    expect(next.pages[0]?.revealed).toBe(false);
    expect(next.current).toBe(0);
    expect(produced.status).toBe('promoted');
  });

  it('refuses non-ready candidates and lesson mismatches', () => {
    const deck = createEmptyDeck('profil', 'lektion-1', NOW);
    expect(() => promoteCandidate(deck, page({ status: 'superseded' }), NOW)).toThrow();
    expect(() => promoteCandidate(deck, page({ lessonId: 'annan' }), NOW)).toThrow();
  });
});

describe('applyReveal', () => {
  it('reveals the current page and reports duplicates and stale targets', () => {
    let deck = promoteCandidate(createEmptyDeck('profil', 'lektion-1', NOW), page(), NOW);
    const first = applyReveal(deck, 'p1', 'r1', NOW + 1);
    expect(first.outcome.kind).toBe('revealed');
    deck = first.deck;
    const duplicate = applyReveal(deck, 'p1', 'r1', NOW + 2);
    expect(duplicate.outcome.kind).toBe('duplicate');
    expect(duplicate.deck).toBe(deck); // no mutation on duplicate
    const stale = applyReveal(deck, 'p1', 'r0', NOW + 3);
    expect(stale.outcome.kind).toBe('stale');
    const empty = applyReveal(createEmptyDeck('profil', 'lektion-1', NOW), 'p1', 'r1', NOW);
    expect(empty.outcome).toEqual({ kind: 'stale', reason: 'no-visible-page' });
  });
});

describe('drafts', () => {
  it('saves page-local drafts capped at 500 chars and rejects unknown revisions', () => {
    let deck = promoteCandidate(createEmptyDeck('profil', 'lektion-1', NOW), page(), NOW);
    const saved = applyDraft(deck, 'p1', 'r1', 'x'.repeat(600), NOW + 1);
    expect(saved.outcome).toEqual({ kind: 'saved' });
    expect(saved.deck.drafts['p1:r1']).toHaveLength(500);
    deck = saved.deck;
    expect(currentPage(deck)?.id).toBe('p1');
    const stale = applyDraft(deck, 'p1', 'r9', 'hej', NOW + 2);
    expect(stale.outcome.kind).toBe('stale');
  });
});

describe('goToIndex', () => {
  it('clamps navigation into range', () => {
    let deck = createEmptyDeck('profil', 'lektion-1', NOW);
    deck = promoteCandidate(deck, page({ id: 'p1' }), NOW);
    deck = promoteCandidate(deck, page({ id: 'p2' }), NOW);
    expect(goToIndex(deck, 5, NOW).current).toBe(1);
    expect(goToIndex(deck, -3, NOW).current).toBe(0);
    expect(goToIndex(deck, 1, NOW).current).toBe(1);
  });
});

describe('lesson continuity', () => {
  it('archives the old deck and starts empty on an intentional new lesson', () => {
    let deck = promoteCandidate(createEmptyDeck('profil', 'lektion-1', NOW), page({ title: 'Bråk' }), NOW);
    const { deck: next, archived } = startNewLesson(deck, 'lektion-2', 'Alicia', NOW + 1);
    expect(next.pages).toHaveLength(0);
    expect(next.lessonId).toBe('lektion-2');
    expect(archived?.greetingHint).toContain('Alicia');
    expect(archived?.titles).toEqual(['Bråk']);
  });

  it('same lesson and empty decks produce no archive', () => {
    const deck = createEmptyDeck('profil', 'lektion-1', NOW);
    expect(startNewLesson(deck, 'lektion-1', 'Alicia', NOW).archived).toBeNull();
    expect(startNewLesson(deck, 'lektion-2', 'Alicia', NOW).archived).toBeNull();
  });

  it('interrupted lessons resume only for the same lesson with pages', () => {
    const deck = promoteCandidate(createEmptyDeck('profil', 'lektion-1', NOW), page(), NOW);
    expect(shouldResumeDeck(deck, 'lektion-1')).toBe(true);
    expect(shouldResumeDeck(deck, 'lektion-2')).toBe(false);
    expect(shouldResumeDeck(createEmptyDeck('profil', 'lektion-1', NOW), 'lektion-1')).toBe(false);
    expect(shouldResumeDeck(null, 'lektion-1')).toBe(false);
  });
});

describe('intent registry', () => {
  it('rejects duplicate registration and replays settled outcomes', () => {
    const registry = new Map();
    expect(registerIntent(registry, 'i1')).toBe(true);
    expect(registerIntent(registry, 'i1')).toBe(false);
    settleIntent(registry, 'i1', { status: 'ready', page: { id: 'p1', revision: 'r1' } });
    expect(getIntentOutcome(registry, 'i1')).toEqual({
      status: 'ready',
      page: { id: 'p1', revision: 'r1' },
    });
  });
});
