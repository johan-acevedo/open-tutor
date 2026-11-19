import { describe, expect, it } from 'vitest';
import {
  createProfile,
  enqueueProfileGrade,
  enqueueProfileName,
  enqueueProfileSwitch,
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

describe('serialized profile writes', () => {
  it('drops a grade write that lost its race with a switch', async () => {
    const a = await createProfile('RaceOld');
    let active: string | null = a.id;
    const graded = enqueueProfileGrade(a.id, 6, () => active);
    const switched = enqueueProfileSwitch('RaceNew');
    const [g, b] = await Promise.all([graded, switched]);
    // FIFO: the grade landed on the still-active old profile first.
    expect(g?.grade).toBe(6);
    // After the restart the old target is stale and dropped.
    active = b.id;
    await expect(enqueueProfileGrade(a.id, 8, () => active)).resolves.toBeUndefined();
    expect((await listProfiles()).find((p) => p.id === a.id)?.grade).toBe(6);
  });

  it('switching twice to the same new name creates one profile', async () => {
    const before = (await listProfiles()).length;
    const [first, second] = await Promise.all([
      enqueueProfileSwitch('RaceDup'),
      enqueueProfileSwitch('racedup'),
    ]);
    expect(second.id).toBe(first.id);
    const dups = (await listProfiles()).filter((p) => p.name.toLowerCase() === 'racedup');
    expect(dups).toHaveLength(1);
    expect((await listProfiles()).length).toBe(before + 1);
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

describe('voice-first naming (enqueueProfileName)', () => {
  it('creates the local profile for the spoken name', async () => {
    const named = await enqueueProfileName('temp-1', '  Noa ', () => 'temp-1');
    expect(named?.name).toBe('Noa');
    expect(named?.grade).toBeNull();
    expect((await listProfiles()).find((p) => p.id === named?.id)?.name).toBe('Noa');
  });
  it('attaches to an existing local profile with the same name', async () => {
    const existing = await createProfile('Moa');
    await updateProfile(existing.id, { grade: 5 });
    const named = await enqueueProfileName('temp-2', 'moa', () => 'temp-2');
    expect(named?.id).toBe(existing.id);
    expect(named?.grade).toBe(5);
    expect((await listProfiles()).filter((p) => p.name.toLowerCase() === 'moa')).toHaveLength(1);
  });
  it('drops a naming that lost its race with a switch', async () => {
    const before = (await listProfiles()).length;
    const named = await enqueueProfileName('temp-3', 'StaleNamn', () => 'other-id');
    expect(named).toBeUndefined();
    expect((await listProfiles()).length).toBe(before);
  });
  it('rejects a blank name without creating anything', async () => {
    const before = (await listProfiles()).length;
    await expect(enqueueProfileName('temp-4', '   ', () => 'temp-4')).resolves.toBeUndefined();
    expect((await listProfiles()).length).toBe(before);
  });
});
