import { describe, expect, it } from 'vitest';
import { createEndGate, routeAfterEnd } from './lessonEnd';

describe('routeAfterEnd', () => {
  it('routes a switch prefill to the start page for B', () => {
    expect(routeAfterEnd({ prefillId: 'pB', goProfiles: false })).toEqual({ kind: 'prefill', id: 'pB' });
  });
  it('routes a menu leave to the open name entry', () => {
    expect(routeAfterEnd({ prefillId: null, goProfiles: true })).toEqual({ kind: 'open' });
  });
  it('routes a plain end to the end card', () => {
    expect(routeAfterEnd({ prefillId: null, goProfiles: false })).toEqual({ kind: 'end' });
  });
  it('lets a switch prefill win over a simultaneous menu leave', () => {
    // Tutor switch plus menu at once: one end, B's start page, no end card.
    expect(routeAfterEnd({ prefillId: 'pB', goProfiles: true })).toEqual({ kind: 'prefill', id: 'pB' });
  });
});

describe('createEndGate', () => {
  it('lets exactly one caller own the end transition', () => {
    const gate = createEndGate();
    expect(gate.claim()).toBe(true);
    // Double "Byt elev", or Avsluta during the goodbye: stand down.
    expect(gate.claim()).toBe(false);
    gate.release();
    expect(gate.claim()).toBe(true);
  });
});
