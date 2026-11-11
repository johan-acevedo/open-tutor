import { describe, expect, it } from 'vitest';
import { layoutMode, mapAvatarState } from './avatarState';

describe('mapAvatarState', () => {
  const base = {
    agentState: 'listening' as const,
    tutorMode: 'talking' as const,
    hasPending: false,
    hasSpokenFirst: true,
    isTeaching: false,
    micBlocked: false,
  };

  it('maps speaking to Pratar with animated bars, pointing when teaching', () => {
    const idle = mapAvatarState({ ...base, agentState: 'speaking' });
    expect(idle.pose).toBe('speaking');
    expect(idle.pill.label).toBe('Pratar');
    expect(idle.pill.animateBars).toBe(true);

    const teaching = mapAvatarState({ ...base, agentState: 'speaking', isTeaching: true });
    expect(teaching.pose).toBe('pointing');
    expect(teaching.pill.label).toBe('Pratar');
  });

  it('maps listening to Lyssnar without bars', () => {
    const s = mapAvatarState({ ...base, agentState: 'listening' });
    expect(s.pose).toBe('listening');
    expect(s.pill.label).toBe('Lyssnar');
    expect(s.pill.animateBars).toBe(false);
  });

  it('maps thinking to Tänker… and pending to the working pose with Ritar…', () => {
    const t = mapAvatarState({ ...base, agentState: 'thinking' });
    expect(t.pill.label).toBe('Tänker…');
    expect(t.pill.animateBars).toBe(false);
    const p = mapAvatarState({ ...base, agentState: 'listening', hasPending: true });
    expect(p.pose).toBe('working');
    expect(p.pill.label).toBe('Ritar…');
    expect(p.pill.animateBars).toBe(false);
  });

  it('keeps speaking, quiet and resource ahead of pending', () => {
    // The tutor may say one short sentence while quiet work starts: spoken
    // words still show as speaking even with a board drawing in flight.
    expect(mapAvatarState({ ...base, agentState: 'speaking', hasPending: true }).pill.label).toBe('Pratar');
    expect(mapAvatarState({ ...base, agentState: 'speaking', hasPending: true }).pose).toBe('speaking');
    const quiet = mapAvatarState({ ...base, tutorMode: 'quiet', hasPending: true });
    expect(quiet.pose).toBe('waiting');
    expect(quiet.pill.label).toBe('Jag väntar');
    const resource = mapAvatarState({ ...base, tutorMode: 'resource', hasPending: true });
    expect(resource.pose).toBe('waiting');
    expect(resource.pill.label).toBe('Väntar medan du tittar');
  });

  it('leaves the working pose once the pending board is finished', () => {
    const drawing = mapAvatarState({ ...base, agentState: 'listening', hasPending: true });
    expect(drawing.pose).toBe('working');
    // board.update replaces the pending item in place: hasPending clears.
    const finished = mapAvatarState({ ...base, agentState: 'listening', hasPending: false });
    expect(finished.pose).toBe('listening');
    expect(finished.pill.label).toBe('Lyssnar');
  });

  it('maps quiet and resource modes to waiting poses', () => {
    const q = mapAvatarState({ ...base, agentState: 'listening', tutorMode: 'quiet' });
    expect(mapAvatarState({ ...base, agentState: 'speaking', tutorMode: 'quiet' }).pill.label).toBe('Pratar');
    expect(q.pose).toBe('waiting');
    expect(q.pill.label).toBe('Jag väntar');
    expect(q.pill.animateBars).toBe(false);
    const r = mapAvatarState({ ...base, tutorMode: 'resource' });
    expect(r.pill.label).toBe('Väntar medan du tittar');
  });

  it('uses greeting pose before the first agent speech', () => {
    const s = mapAvatarState({ ...base, agentState: 'listening', hasSpokenFirst: false });
    expect(s.pose).toBe('greeting');
  });
});

describe('layoutMode', () => {
  it('stays on arrival until the first board item', () => {
    expect(layoutMode(0)).toBe('arrival');
    expect(layoutMode(1)).toBe('teaching');
    expect(layoutMode(5)).toBe('teaching');
  });
});

describe('mic blocked', () => {
  it('shows waiting for text instead of listening', () => {
    const out = mapAvatarState({ agentState: 'listening', tutorMode: 'talking', hasPending: false, isTeaching: false, micBlocked: true, hasSpokenFirst: true });
    expect(out.pill.label).toBe('Väntar på text');
    expect(out.pill.animateBars).toBe(false);
  });
});
