import { describe, expect, it } from 'vitest';
import {
  createProfile,
  enqueueNote,
  enqueueProfileGrade,
  enqueueProfileName,
  enqueueProfileSwitch,
  getLastProfileId,
  getProfile,
  listProfiles,
  rememberLastProfileId,
  resolveProfileSwitch,
  updateProfile,
} from './db';
import type { NamingSession } from './db';

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

describe('voice-first naming generation gate', () => {
  // Finding 1: a name RPC from an ended or previous session writes nothing.
  // The generation is checked before the write is enqueued and again inside
  // the queue (it may turn while the write waits).
  it('writes nothing once the session already ended', async () => {
    const before = (await listProfiles()).length;
    const named = await enqueueProfileName('temp-g1', 'Svala', () => 'temp-g1', {
      isCurrentSession: () => false,
    });
    expect(named).toBeUndefined();
    expect((await listProfiles()).length).toBe(before);
  });

  it('drops a naming whose session ends while it is queued', async () => {
    let current = true;
    const before = (await listProfiles()).length;
    const pending = enqueueProfileName('temp-g2', 'Svala', () => 'temp-g2', {
      isCurrentSession: () => current,
    });
    current = false; // the room ended before the serialized write ran
    await expect(pending).resolves.toBeUndefined();
    expect((await listProfiles()).length).toBe(before);
  });
});

describe('voice-first naming corrections', () => {
  // Finding 2: a correction of a name learned earlier in this session renames
  // that profile in place, keeping the grade and notes learned meanwhile.
  it('renames this session’s profile in place, keeping grade and notes', async () => {
    let active: string | null = 'temp-c1';
    const naming: NamingSession = { createdId: null };
    const first = await enqueueProfileName('temp-c1', 'Svala', () => active, {
      isCurrentSession: () => true,
      naming,
    });
    expect(first?.name).toBe('Svala');
    active = first!.id;
    await updateProfile(first!.id, { grade: 5 });
    await enqueueNote(first!.id, { at: '2026-11-19', topic: 'Bråk' });
    const corrected = await enqueueProfileName(first!.id, 'Tindra', () => active, {
      isCurrentSession: () => true,
      naming,
    });
    expect(corrected?.id).toBe(first!.id);
    expect(corrected?.name).toBe('Tindra');
    expect(corrected?.grade).toBe(5);
    expect(corrected?.notes.map((n) => n.topic)).toContain('Bråk');
  });

  it('attaching elsewhere moves notes, keeps that grade, and drops the temp', async () => {
    const existing = await createProfile('Vanja');
    await updateProfile(existing.id, { grade: 3 });
    let active: string | null = 'temp-c2';
    const naming: NamingSession = { createdId: null };
    const first = await enqueueProfileName('temp-c2', 'Zelda', () => active, {
      isCurrentSession: () => true,
      naming,
    });
    active = first!.id;
    await updateProfile(first!.id, { grade: 5 });
    await enqueueNote(first!.id, { at: '2026-11-19', topic: 'Ekvationer' });
    const attached = await enqueueProfileName(first!.id, 'Vanja', () => active, {
      isCurrentSession: () => true,
      naming,
    });
    expect(attached?.id).toBe(existing.id);
    expect(attached?.grade).toBe(3);
    expect(attached?.notes.map((n) => n.topic)).toContain('Ekvationer');
    expect(await getProfile(first!.id)).toBeUndefined();
    expect((await listProfiles()).filter((p) => p.name === 'Zelda')).toHaveLength(0);
  });

  it('an attached profile without a grade takes the temporary one’s', async () => {
    const existing = await createProfile('Kim');
    let active: string | null = 'temp-c3';
    const naming: NamingSession = { createdId: null };
    const first = await enqueueProfileName('temp-c3', 'Juni', () => active, {
      isCurrentSession: () => true,
      naming,
    });
    active = first!.id;
    await updateProfile(first!.id, { grade: 4 });
    const attached = await enqueueProfileName(first!.id, 'Kim', () => active, {
      isCurrentSession: () => true,
      naming,
    });
    expect(attached?.id).toBe(existing.id);
    expect(attached?.grade).toBe(4);
    expect(await getProfile(first!.id)).toBeUndefined();
  });
});

describe('notes during naming', () => {
  // Finding 4: the note target is resolved inside the serialized queue at
  // execution time, so a note that arrived while the naming was in flight
  // lands on the named profile.
  it('a note that arrives during naming lands on the named profile', async () => {
    let active: string | null = 'temp-n1';
    const naming: NamingSession = { createdId: null };
    let target = 'temp-n1';
    const nameP = enqueueProfileName('temp-n1', 'Alva', () => active, {
      isCurrentSession: () => true,
      naming,
    });
    const noteP = enqueueNote(() => target, { at: '2026-11-19', topic: 'Bråk' });
    const named = await nameP;
    // useSession adopts the naming once the write lands.
    target = named!.id;
    active = named!.id;
    const saved = await noteP;
    expect(saved?.id).toBe(named!.id);
    expect(saved?.notes.map((n) => n.topic)).toContain('Bråk');
  });
});

describe('invalid names are never stored', () => {
  // Finding 6: digits and markup are rejected before anything is persisted.
  it('rejects names that are not names without creating anything', async () => {
    const before = (await listProfiles()).length;
    for (const bad of ['Moa2', '<b>Moa</b>', 'Hej hej hej hej', 'x'.repeat(41), 'Erik!', '  ']) {
      await expect(enqueueProfileName('temp-v1', bad, () => 'temp-v1')).resolves.toBeUndefined();
    }
    expect((await listProfiles()).length).toBe(before);
  });
});
