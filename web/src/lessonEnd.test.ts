import { describe, expect, it } from 'vitest';
import { createEndGate, routeAfterDisconnect, routeAfterEnd } from './lessonEnd';

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

describe('routeAfterDisconnect', () => {
  it('routes an idle timeout to the end card with its reason, never the banner', () => {
    expect(
      routeAfterDisconnect({ prefillId: null, goProfiles: false, intentional: false, endReason: 'idle_timeout' }),
    ).toEqual({ kind: 'end', reason: 'idle_timeout' });
  });
  it('routes an idle timeout during a menu leave to the open name entry', () => {
    expect(
      routeAfterDisconnect({ prefillId: null, goProfiles: true, intentional: false, endReason: 'idle_timeout' }),
    ).toEqual({ kind: 'open' });
  });
  it('lets a switch prefill win over an idle timeout', () => {
    expect(
      routeAfterDisconnect({ prefillId: 'pB', goProfiles: false, intentional: false, endReason: 'idle_timeout' }),
    ).toEqual({ kind: 'prefill', id: 'pB' });
  });
  it('stands down when our own end path already handled the landing', () => {
    expect(
      routeAfterDisconnect({ prefillId: null, goProfiles: false, intentional: true, endReason: null }),
    ).toEqual({ kind: 'ignore' });
  });
  it('keeps the reconnect banner for any other unexpected disconnect', () => {
    expect(
      routeAfterDisconnect({ prefillId: null, goProfiles: false, intentional: false, endReason: null }),
    ).toEqual({ kind: 'banner' });
    // An unknown worker reason is not trusted: still the banner.
    expect(
      routeAfterDisconnect({ prefillId: null, goProfiles: false, intentional: false, endReason: 'boom' }),
    ).toEqual({ kind: 'banner' });
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
