import { describe, expect, it } from 'vitest';
import { promoteCandidate, createEmptyDeck } from './deck';
import {
  buildObservationContext,
  publicRecordLeaksSolution,
  toPublicObservationRecord,
  validateObservationRequest,
} from './observation';
import type { CandidatePage } from './types';

const NOW = 1_700_000_000_000;

function deckWithDraft() {
  const candidate: CandidatePage = {
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
    solution: 'Svaret är 3/4, hemligt',
    sources: ['Matteboken s. 12'],
    revealed: false,
    createdAt: NOW,
    intentId: 'i1',
    requestSeq: 1,
    status: 'ready',
    receivedAt: NOW,
  };
  const deck = promoteCandidate(createEmptyDeck('profil', 'lektion-1', NOW), candidate, NOW);
  return { ...deck, drafts: { 'p1:r1': '3/4' } };
}

describe('validateObservationRequest', () => {
  it('accepts the current page and rejects stale or missing pages', () => {
    const deck = deckWithDraft();
    expect(validateObservationRequest(deck, { observationId: 'o1', pageId: 'p1', revision: 'r1' })).toEqual({
      ok: true,
    });
    expect(
      validateObservationRequest(deck, { observationId: 'o1', pageId: 'p1', revision: 'r0' }),
    ).toEqual({ ok: false, reason: 'stale-observation' });
    expect(validateObservationRequest(createEmptyDeck('p', 'l', NOW), { observationId: 'o', pageId: 'p', revision: 'r' })).toEqual({
      ok: false,
      reason: 'no-visible-page',
    });
  });
});

describe('observation context privacy', () => {
  it('splits private teaching from public state', () => {
    const deck = deckWithDraft();
    const context = buildObservationContext(
      deck,
      { observationId: 'o1', pageId: 'p1', revision: 'r1' },
      { w: 1280, h: 800 },
    );
    expect(context.privateTeaching).toBe('Svaret är 3/4, hemligt');
    expect(context.answerState).toEqual({ hasDraft: true, draftLength: 3, revealed: false });
    expect(context.sources).toEqual(['Matteboken s. 12']);
    const pub = toPublicObservationRecord(context);
    expect('privateTeaching' in pub).toBe(false);
    expect(JSON.stringify(pub)).not.toContain('hemligt');
  });

  it('flags leaks of the hidden solution in public records', () => {
    const deck = deckWithDraft();
    const context = buildObservationContext(
      deck,
      { observationId: 'o1', pageId: 'p1', revision: 'r1' },
      { w: 1280, h: 800 },
    );
    const pub = toPublicObservationRecord(context);
    expect(publicRecordLeaksSolution(pub, context.privateTeaching, false)).toBe(false);
    const leaked = { ...pub, viewport: { w: 1, h: 2 }, note: 'Svaret är 3/4, hemligt' };
    expect(publicRecordLeaksSolution(leaked as never, context.privateTeaching, false)).toBe(true);
    // Revealed solutions are legitimately visible; the guard only applies while hidden.
    expect(publicRecordLeaksSolution(leaked as never, context.privateTeaching, true)).toBe(false);
  });
});
