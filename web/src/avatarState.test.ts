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

  it('maps thinking to Tänker… and pending to Ritar…', () => {
    const t = mapAvatarState({ ...base, agentState: 'thinking' });
    expect(t.pill.label).toBe('Tänker…');
    expect(t.pill.animateBars).toBe(false);
    const p = mapAvatarState({ ...base, agentState: 'listening', hasPending: true });
    expect(p.pill.label).toBe('Ritar…');
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
