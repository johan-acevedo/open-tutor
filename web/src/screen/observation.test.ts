import { describe, expect, it } from 'vitest';
import { promoteCandidate, createEmptyDeck } from './deck';
import {
  buildObservationContext,
  buildVisibleText,
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
    expect(
      validateObservationRequest(deck, { observationId: 'o1', lessonId: 'lektion-1', pageId: 'p1', revision: 'r1' }),
    ).toEqual({
      ok: true,
    });
    expect(
      validateObservationRequest(deck, { observationId: 'o1', lessonId: 'lektion-1', pageId: 'p1', revision: 'r0' }),
    ).toEqual({ ok: false, reason: 'stale-observation' });
    expect(
      validateObservationRequest(createEmptyDeck('p', 'l', NOW), {
        observationId: 'o',
        lessonId: 'l',
        pageId: 'p',
        revision: 'r',
      }),
    ).toEqual({
      ok: false,
      reason: 'no-visible-page',
    });
  });

  it('rejects stale lessons (lesson binding)', () => {
    const deck = deckWithDraft();
    expect(
      validateObservationRequest(deck, { observationId: 'o1', lessonId: 'lektion-2', pageId: 'p1', revision: 'r1' }),
    ).toEqual({ ok: false, reason: 'lesson-mismatch' });
  });
});

describe('observation context privacy', () => {
  it('splits private teaching from public state', () => {
    const deck = deckWithDraft();
    const context = buildObservationContext(
      deck,
      { observationId: 'o1', lessonId: 'lektion-1', pageId: 'p1', revision: 'r1' },
      { w: 1280, h: 800, device: 'desktop' },
    );
    expect(context.privateTeaching).toBe('Svaret är 3/4, hemligt');
    expect(context.lessonId).toBe('lektion-1');
    expect(context.viewport).toEqual({ w: 1280, h: 800, device: 'desktop' });
    expect(context.answerState).toEqual({ hasDraft: true, draftLength: 3, revealed: false });
    expect(context.sources).toEqual(['Matteboken s. 12']);
    // visibleText carries the question + draft but never the hidden solution
    expect(context.visibleText).toContain('Bråk');
    expect(context.visibleText).toContain('Vad är 1/2 + 1/4?');
    expect(context.visibleText).not.toContain('hemligt');
    const pub = toPublicObservationRecord(context);
    expect('privateTeaching' in pub).toBe(false);
    expect(JSON.stringify(pub)).not.toContain('hemligt');
  });

  it('includes the solution in visibleText only after reveal', () => {
    const hidden = deckWithDraft();
    const hiddenCtx = buildObservationContext(
      hidden,
      { observationId: 'o1', lessonId: 'lektion-1', pageId: 'p1', revision: 'r1' },
      { w: 390, h: 700, device: 'phone' },
    );
    expect(hiddenCtx.viewport.device).toBe('phone');
    expect(hiddenCtx.visibleText).not.toContain('hemligt');

    const revealed = {
      ...hidden,
      pages: hidden.pages.map((p) => ({ ...p, revealed: true })),
    };
    const revealedCtx = buildObservationContext(
      revealed,
      { observationId: 'o2', lessonId: 'lektion-1', pageId: 'p1', revision: 'r1' },
      { w: 390, h: 700, device: 'phone' },
    );
    expect(revealedCtx.visibleText).toContain('hemligt');
    expect(revealedCtx.answerState.revealed).toBe(true);
  });

  it('buildVisibleText never leaks hidden solutions', () => {
    expect(
      buildVisibleText({ title: 'T', body: ['B'], solution: 'Hemlig 42', revealed: false }, 'draft'),
    ).not.toContain('Hemlig');
    expect(
      buildVisibleText({ title: 'T', body: ['B'], solution: 'Hemlig 42', revealed: true }, ''),
    ).toContain('Hemlig 42');
  });

  it('rejects context builds for stale lessons', () => {
    const deck = deckWithDraft();
    expect(() =>
      buildObservationContext(
        deck,
        { observationId: 'o1', lessonId: 'annan-lektion', pageId: 'p1', revision: 'r1' },
        { w: 1280, h: 800 },
      ),
    ).toThrow('lesson-mismatch');
  });

  it('flags leaks of the hidden solution in public records', () => {
    const deck = deckWithDraft();
    const context = buildObservationContext(
      deck,
      { observationId: 'o1', lessonId: 'lektion-1', pageId: 'p1', revision: 'r1' },
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
