import { describe, expect, it } from 'vitest';
import {
  createProfile,
  getLastProfileId,
  listProfiles,
  rememberLastProfileId,
  resolveProfileSwitch,
  updateProfile,
} from './db';

describe('resolveProfileSwitch', () => {
  const profiles = [
    { id: 'a', name: 'Elsa', grade: 4 as number | null, notes: [], createdAt: 0 },
    { id: 'b', name: 'Leo', grade: null, notes: [], createdAt: 1 },
  ];
  it('matches by first name, case-insensitively', () => {
    expect(resolveProfileSwitch(profiles, 'leo')?.id).toBe('b');
    expect(resolveProfileSwitch(profiles, ' ELSA ')?.id).toBe('a');
  });
  it('returns nothing for unknown or blank names', () => {
    expect(resolveProfileSwitch(profiles, 'Noa')).toBeUndefined();
    expect(resolveProfileSwitch(profiles, '  ')).toBeUndefined();
  });
});

describe('last profile', () => {
  it('remembers the assumed student across visits', () => {
    localStorage.clear();
    expect(getLastProfileId()).toBeNull();
    rememberLastProfileId('p9');
    expect(getLastProfileId()).toBe('p9');
  });
});

describe('profiles without a grade', () => {
  it('creates name-only profiles and learns the grade later', async () => {
    localStorage.clear();
    const created = await createProfile('Leo');
    expect(created.grade).toBeNull();
    const updated = await updateProfile(created.id, { grade: 8 });
    expect(updated?.grade).toBe(8);
    expect((await listProfiles()).find((p) => p.id === created.id)?.grade).toBe(8);
  });
});
