import { describe, expect, it, vi } from 'vitest';
import { RpcError } from 'livekit-client';
import { handleCancelSwitch, handleSetGrade, handleSwitch, type LearnerRpcDeps } from './learnerRpc';
import type { Profile } from './db';

function profile(over: Partial<Profile> = {}): Profile {
  return { id: 'p1', name: 'Leo', grade: null, notes: [], createdAt: 0, ...over };
}

function deps(over: Partial<LearnerRpcDeps> = {}): LearnerRpcDeps {
  return {
    applyGrade: vi.fn() as LearnerRpcDeps['applyGrade'],
    resolveStudent: vi.fn() as LearnerRpcDeps['resolveStudent'],
    rememberLast: vi.fn() as LearnerRpcDeps['rememberLast'],
    armSwitch: vi.fn() as LearnerRpcDeps['armSwitch'],
    ...over,
  };
}

const rpc = (payload: string) => ({ payload }) as never;

describe('handleSetGrade', () => {
  it('applies the acknowledged grade and replies with it', async () => {
    const d = deps();
    vi.mocked(d.applyGrade).mockResolvedValue(profile({ grade: 8 }));
    const reply = await handleSetGrade(rpc(JSON.stringify({ profileId: 'p1', grade: 8 })), d);
    expect(JSON.parse(reply)).toEqual({ ok: true, grade: 8 });
    expect(d.applyGrade).toHaveBeenCalledWith('p1', 8);
  });
  it('rejects a stale or invalid target so the tool leaves the call as-is', async () => {
    const d = deps();
    vi.mocked(d.applyGrade).mockResolvedValue(undefined);
    await expect(handleSetGrade(rpc(JSON.stringify({ profileId: 'old', grade: 8 })), d)).rejects.toBeInstanceOf(
      RpcError,
    );
  });
  it('rejects malformed payloads', async () => {
    const d = deps();
    await expect(handleSetGrade(rpc('not json'), d)).rejects.toBeInstanceOf(RpcError);
    await expect(handleSetGrade(rpc(JSON.stringify({ grade: 'eight' })), d)).rejects.toBeInstanceOf(RpcError);
  });
});

describe('handleSwitch', () => {
  it('resolves the student, remembers them, arms the restart, and acks with the profile id', async () => {
    const next = profile({ id: 'p2', name: 'Noa', grade: 3 });
    const d = deps();
    vi.mocked(d.resolveStudent).mockResolvedValue(next);
    const reply = await handleSwitch(rpc(JSON.stringify({ name: '  Noa ' })), d);
    expect(d.resolveStudent).toHaveBeenCalledWith('Noa');
    expect(d.rememberLast).toHaveBeenCalledWith('p2');
    expect(d.armSwitch).toHaveBeenCalledWith(next);
    expect(JSON.parse(reply)).toEqual({ ok: true, profile: { id: 'p2', name: 'Noa', grade: 3 } });
  });
  it('rejects a missing name so no restart is armed', async () => {
    const d = deps();
    await expect(handleSwitch(rpc(JSON.stringify({ name: '  ' })), d)).rejects.toBeInstanceOf(RpcError);
    expect(d.armSwitch).not.toHaveBeenCalled();
  });
  it('rejects malformed payloads', async () => {
    const d = deps();
    await expect(handleSwitch(rpc('nope'), d)).rejects.toBeInstanceOf(RpcError);
  });
});

describe('handleCancelSwitch', () => {
  it('disarms the pending switch so a later disconnect cannot restart wrongly', async () => {
    const d = deps();
    await expect(handleCancelSwitch(d)).resolves.toBe('{"ok":true}');
    expect(d.armSwitch).toHaveBeenCalledWith(null);
  });
});
