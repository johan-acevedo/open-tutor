import { describe, expect, it, vi } from 'vitest';
import { RpcError } from 'livekit-client';
import { handleNote, handleSetGrade, handleSetName, handleSwitch, type LearnerRpcDeps, type NoteDeps } from './learnerRpc';
import type { Profile } from './db';

function profile(over: Partial<Profile> = {}): Profile {
  return { id: 'p1', name: 'Leo', grade: null, notes: [], createdAt: 0, ...over };
}

function deps(over: Partial<LearnerRpcDeps> = {}): LearnerRpcDeps {
  return {
    applyName: vi.fn() as LearnerRpcDeps['applyName'],
      applyGrade: vi.fn() as LearnerRpcDeps['applyGrade'],
    resolveStudent: vi.fn() as LearnerRpcDeps['resolveStudent'],
    armPrefill: vi.fn() as LearnerRpcDeps['armPrefill'],
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
    expect(d.armPrefill).toHaveBeenCalledWith(next);
    expect(JSON.parse(reply)).toEqual({ ok: true, profile: { id: 'p2', name: 'Noa', grade: 3 } });
  });
  it('rejects a missing name so no restart is armed', async () => {
    const d = deps();
    await expect(handleSwitch(rpc(JSON.stringify({ name: '  ' })), d)).rejects.toBeInstanceOf(RpcError);
    expect(d.armPrefill).not.toHaveBeenCalled();
  });
  it('rejects malformed payloads', async () => {
    const d = deps();
    await expect(handleSwitch(rpc('nope'), d)).rejects.toBeInstanceOf(RpcError);
  });
});

describe('handleSetName', () => {
  it('creates or attaches the profile and acks with its id, name and grade', async () => {
    const d = deps();
    vi.mocked(d.applyName).mockResolvedValue(profile({ id: 'p9', name: 'Noa', grade: 3 }));
    const reply = await handleSetName(rpc(JSON.stringify({ profileId: 'temp-1', name: '  Noa ' })), d);
    expect(JSON.parse(reply)).toEqual({ ok: true, profile: { id: 'p9', name: 'Noa', grade: 3 } });
    expect(d.applyName).toHaveBeenCalledWith('temp-1', 'Noa');
  });
  it('rejects a stale target or a missing name so nothing is saved', async () => {
    const d = deps();
    vi.mocked(d.applyName).mockResolvedValue(undefined);
    await expect(handleSetName(rpc(JSON.stringify({ profileId: 'old', name: 'Noa' })), d)).rejects.toBeInstanceOf(
      RpcError,
    );
    await expect(handleSetName(rpc(JSON.stringify({ profileId: 'temp-1', name: '   ' })), d)).rejects.toBeInstanceOf(
      RpcError,
    );
  });
  it('rejects malformed payloads', async () => {
    const d = deps();
    await expect(handleSetName(rpc('not json'), d)).rejects.toBeInstanceOf(RpcError);
  });
});

describe('handleNote', () => {
  const saved = (over = {}) => ({ id: 'pA', name: 'Leo', grade: null as number | null, notes: [], createdAt: 0, ...over });
  function noteDeps(over: Partial<NoteDeps> = {}) {
    return {
      getSessionProfileId: () => 'pA',
      isCurrentSession: () => true,
      getActiveId: () => 'pA',
      onNote: vi.fn(),
      saveNote: vi.fn(async () => saved()),
      ...over,
    };
  }
  it('follows a voice-first naming: notes land on the named profile', async () => {
    let bound = 'temp-1';
    const d = noteDeps({ getSessionProfileId: () => bound });
    bound = 'p9';
    await handleNote(wire('Ekvationer'), d);
    expect(vi.mocked(d.saveNote)).toHaveBeenCalledWith('p9', expect.objectContaining({ topic: 'Ekvationer' }));
  });
  const wire = (text: string) => JSON.stringify({ at: '2026-11-18', topic: text });

  it('stores the note under the session profile and shows it', async () => {
    const d = noteDeps();
    await handleNote(wire('Ekvationer'), d);
    expect(vi.mocked(d.saveNote)).toHaveBeenCalledWith('pA', expect.objectContaining({ topic: 'Ekvationer' }));
    expect(vi.mocked(d.onNote)).toHaveBeenCalledTimes(1);
  });
  it('stores a delayed note under A but never touches the new session', async () => {
    // Lesson A saved slowly; B already started: the note lands on A, B is untouched.
    let release!: () => void;
    const gate = new Promise<ReturnType<typeof saved>>((resolve) => {
      release = () => resolve(saved());
    });
    const d = noteDeps({ saveNote: vi.fn(async () => gate), isCurrentSession: () => false });
    const pending = handleNote(wire('Bråk'), d);
    release();
    await pending;
    expect(vi.mocked(d.saveNote)).toHaveBeenCalledWith('pA', expect.objectContaining({ topic: 'Bråk' }));
    expect(vi.mocked(d.onNote)).not.toHaveBeenCalled();
  });
  it('drops the UI update when the live profile is no longer the target', async () => {
    const d = noteDeps({ getActiveId: () => 'pB' });
    await handleNote(wire('Ekvationer'), d);
    expect(vi.mocked(d.saveNote)).toHaveBeenCalled();
    expect(vi.mocked(d.onNote)).not.toHaveBeenCalled();
  });
  it('ignores malformed or empty notes', async () => {
    const d = noteDeps();
    await handleNote('not json', d);
    await handleNote(JSON.stringify({ topic: '' }), d);
    await handleNote(JSON.stringify({ nope: 1 }), d);
    expect(vi.mocked(d.saveNote)).not.toHaveBeenCalled();
    expect(vi.mocked(d.onNote)).not.toHaveBeenCalled();
  });
});
