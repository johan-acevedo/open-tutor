// Learner profiles in IndexedDB (db `open-tutor`, store `profiles`).
// Tiny wrapper, no library. If IndexedDB fails, fall back to memory silently.

import type { Note } from './protocol';
import { cleanLearnerName, isValidLearnerName } from './learnerName';
import type { BandId } from './bands';

export type Profile = {
  id: string;
  name: string;
  /** School year (1-12), or null when not known yet. The tutor learns it
   *  naturally in the first call via the set_learner_grade tool; adults
   *  (band 3 adults) are never asked for one. */
  grade: number | null;
  /** Age band the learner last started a call in. Set when a call starts;
   *  older profiles predate it and stay valid without one. */
  band?: BandId;
  notes: Note[];
  createdAt: number;
};

const DB_NAME = 'open-tutor';
const STORE = 'profiles';
const MAX_NOTES = 20;

let memoryFallback = new Map<string, Profile>();
let idbBroken = false;

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('no indexedDB'));
      return;
    }
    let req: IDBOpenDBRequest;
    try {
      req = indexedDB.open(DB_NAME, 1);
    } catch (err) {
      reject(err);
      return;
    }
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'id' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error('indexedDB open failed'));
  });
}

function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        let done = false;
        try {
          const t = db.transaction(STORE, mode);
          t.oncomplete = () => {
            db.close();
          };
          t.onerror = () => {
            if (!done) {
              done = true;
              db.close();
              reject(t.error ?? new Error('indexedDB transaction failed'));
            }
          };
          const store = t.objectStore(STORE);
          const req = run(store);
          req.onsuccess = () => {
            if (!done) {
              done = true;
              resolve(req.result);
            }
          };
          req.onerror = () => {
            if (!done) {
              done = true;
              reject(req.error ?? new Error('indexedDB request failed'));
            }
          };
        } catch (err) {
          try {
            db.close();
          } catch {
            /* ignore */
          }
          reject(err);
        }
      }),
  );
}

function memList(): Profile[] {
  return [...memoryFallback.values()].sort((a, b) => a.createdAt - b.createdAt);
}

export async function listProfiles(): Promise<Profile[]> {
  if (idbBroken) return memList();
  try {
    const all = await tx<Profile[]>('readonly', (store) => store.getAll());
    return (all ?? []).sort((a, b) => a.createdAt - b.createdAt);
  } catch {
    idbBroken = true;
    return memList();
  }
}

export async function getProfile(id: string): Promise<Profile | undefined> {
  if (idbBroken) return memoryFallback.get(id);
  try {
    return await tx<Profile | undefined>('readonly', (store) => store.get(id));
  } catch {
    idbBroken = true;
    return memoryFallback.get(id);
  }
}

export function newProfileId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return `p-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}

export async function saveProfile(profile: Profile): Promise<void> {
  if (idbBroken) {
    memoryFallback.set(profile.id, profile);
    return;
  }
  try {
    await tx('readwrite', (store) => store.put(profile));
  } catch {
    idbBroken = true;
    memoryFallback.set(profile.id, profile);
  }
}

export async function createProfile(name: string, grade: number | null = null, band?: BandId): Promise<Profile> {
  const profile: Profile = {
    id: newProfileId(),
    name: name.trim(),
    grade,
    notes: [],
    createdAt: Date.now(),
    ...(band ? { band } : {}),
  };
  await saveProfile(profile);
  return profile;
}

/** Patch a profile (grade learned mid-call, name fix, band on start). Returns the updated profile. */
export async function updateProfile(profileId: string, patch: { grade?: number | null; name?: string; band?: BandId }): Promise<Profile | undefined> {
  let profile: Profile | undefined;
  if (idbBroken) {
    profile = memoryFallback.get(profileId);
  } else {
    try {
      profile = await tx<Profile | undefined>('readonly', (store) => store.get(profileId));
    } catch {
      idbBroken = true;
      profile = memoryFallback.get(profileId);
    }
  }
  if (!profile) return undefined;
  const updated: Profile = {
    ...profile,
    ...(patch.grade !== undefined ? { grade: patch.grade } : {}),
    ...(patch.name !== undefined ? { name: patch.name.trim() || profile.name } : {}),
    ...(patch.band !== undefined ? { band: patch.band } : {}),
  };
  await saveProfile(updated);
  return updated;
}

/** Per-lesson voice-naming state, owned by the session: the profile this
 *  session's naming created, if any. Reset when a session starts, so a
 *  correction can tell a temporary profile this session created (safe to
 *  rename in place, or to delete when attaching elsewhere) from a stored
 *  profile from an earlier visit (never renamed nor deleted). */
export type NamingSession = { createdId: string | null };

/** Delete a profile (the temporary one a correction supersedes). */
export async function deleteProfile(id: string): Promise<void> {
  if (idbBroken) {
    memoryFallback.delete(id);
    return;
  }
  try {
    await tx('readwrite', (store) => store.delete(id));
  } catch {
    idbBroken = true;
    memoryFallback.delete(id);
  }
}

/** Create the local profile for a voice-learned name, or attach to the stored
 *  profile with the same name — atomically within the queue, so a repeated
 *  name resolves the same profile and never duplicates it.
 *
 *  Correction rule: the session's first naming creates a temporary profile.
 *  Correcting it to another new name renames that profile in place, keeping
 *  the grade and notes learned meanwhile. Only when the corrected name
 *  matches a different existing profile do we attach to that profile
 *  instead: the temporary profile is then deleted, any notes it gained this
 *  session move onto the attached profile, and the attached profile keeps
 *  its own grade when it has one (else it takes the temporary one's). A
 *  stored profile from an earlier visit is never renamed nor deleted: a new
 *  name for it creates a fresh profile.
 *
 *  The session generation (`isCurrentSession`) is checked before the write
 *  is even enqueued and again inside the queue, so a name RPC from an ended
 *  or previous session writes nothing. The target check keeps a stale call
 *  (after a switch or a restart) from creating anything. Returns the
 *  profile, or undefined when stale/invalid. */
export function enqueueProfileName(
  profileId: string, name: string, getActiveId: () => string | null,
  opts?: {
    isCurrentSession?: () => boolean;
    naming?: NamingSession;
    /** Call band to stamp on the named profile, atomically inside the same
     *  serialized write: the band write never races another profile write
     *  and never delays the note binding with a second await outside. */
    stampBand?: BandId;
    /** Bound inside the queue the moment the named profile is known, before
     *  the operation's promise settles: a note enqueued behind the naming
     *  resolves its target (at execution time) to the named profile, never
     *  to the transient start id. Only fires on the success path. */
    bindNoteTarget?: (id: string) => void;
  },
): Promise<Profile | undefined> {
  const wanted = cleanLearnerName(name);
  if (!isValidLearnerName(wanted)) return Promise.resolve(undefined);
  if (opts?.isCurrentSession && !opts.isCurrentSession()) return Promise.resolve(undefined);
  return enqueue(async () => {
    if (opts?.isCurrentSession && !opts.isCurrentSession()) return undefined;
    const activeId = getActiveId();
    if (!profileId || !activeId || profileId !== activeId) return undefined;
    // Stamp the call band on the named profile before returning: the whole
    // naming (name + band) lands as one serialized write.
    const stamped = async (p: Profile | undefined): Promise<Profile | undefined> => {
      if (!p) return undefined;
      const band = opts?.stampBand;
      const done = !band || p.band === band ? p : ((await updateProfile(p.id, { band })) ?? p);
      opts?.bindNoteTarget?.(done.id);
      return done;
    };
    const stored = await listProfiles();
    // The generation may have turned while the read was in flight: nothing
    // has been written yet, so stand down.
    if (opts?.isCurrentSession && !opts.isCurrentSession()) return undefined;
    const markCreated = (id: string | null) => {
      if (opts?.naming && (!opts?.isCurrentSession || opts.isCurrentSession())) opts.naming.createdId = id;
    };
    const current = stored.find((p) => p.id === profileId);
    const match = resolveProfileSwitch(stored, wanted);
    if (match && match.id !== current?.id) {
      // The corrected name belongs to a different stored profile: attach to
      // it. A temporary profile this session created is superseded — move
      // its notes (all gained this session) onto the attached profile and
      // drop it, so no orphan profile is left behind.
      if (current && opts?.naming?.createdId === current.id) {
        let attached: Profile = {
          ...match,
          notes: [...match.notes, ...current.notes].slice(-MAX_NOTES),
        };
        if (attached.grade == null && current.grade != null) attached = { ...attached, grade: current.grade };
        await saveProfile(attached);
        await deleteProfile(current.id);
        markCreated(null);
        return stamped(attached);
      }
      markCreated(null);
      return stamped(match);
    }
    if (current) {
      if (match) {
        // Same profile, only the spelling changed: keep everything.
        if (current.name !== wanted) return stamped(await updateProfile(current.id, { name: wanted }));
        return stamped(current);
      }
      if (opts?.naming?.createdId === current.id) {
        // A correction of a name learned earlier in this session: rename in
        // place so the grade and notes learned meanwhile are kept.
        return stamped(await updateProfile(current.id, { name: wanted }));
      }
      // A stored profile from an earlier visit, corrected to a new name:
      // leave the stored one untouched and start a fresh profile.
      const created = await createProfile(wanted);
      markCreated(created.id);
      return stamped(created);
    }
    // A nameless start has no stored profile yet (transient id): attach to
    // the stored profile with this name, or create it.
    if (match) {
      markCreated(null);
      return stamped(match);
    }
    const created = await createProfile(wanted);
    markCreated(created.id);
    return stamped(created);
  });
}

/** Find a stored profile by first name (case-insensitive), for in-call switching. */
export function resolveProfileSwitch(profiles: Profile[], name: string): Profile | undefined {
  const wanted = name.trim().toLowerCase();
  if (!wanted) return undefined;
  return profiles.find((p) => p.name.trim().toLowerCase() === wanted);
}

const LAST_KEY = 'open-tutor-last-profile';

const lastKeyForBand = (band: BandId): string => `${LAST_KEY}:${band}`;

/** The student the last visit assumed; the next visit starts with them. */
export function getLastProfileId(): string | null {
  try {
    return localStorage.getItem(LAST_KEY);
  } catch {
    return null;
  }
}

/** The student last assumed in one band (siblings on one device). */
export function getLastProfileIdForBand(band: BandId): string | null {
  try {
    return localStorage.getItem(lastKeyForBand(band));
  } catch {
    return null;
  }
}

export function rememberLastProfileId(id: string, band?: BandId): void {
  try {
    localStorage.setItem(LAST_KEY, id);
    if (band) localStorage.setItem(lastKeyForBand(band), id);
  } catch {
    /* storage blocked: next visit just asks the name again */
  }
}

export function forgetLastProfileId(): void {
  try {
    localStorage.removeItem(LAST_KEY);
  } catch {
    /* ignore */
  }
}

// ---- Serialized profile writes -------------------------------------------------
//
// Learner RPCs from the worker (learner.setGrade, learner.switch) and the UI share
// this browser. Every write runs through one queue so concurrent calls cannot
// interleave: each message carries the profile it targets, and a write whose target
// is no longer the active profile is dropped as stale. Switching twice to the same
// new name resolves the same stored profile, so one profile is created.

let profileQueue: Promise<unknown> = Promise.resolve();

function enqueue<T>(job: () => Promise<T>): Promise<T> {
  const next = profileQueue.then(job, job);
  profileQueue = next.catch(() => undefined);
  return next;
}

/** Find the named profile or create it, atomically within the queue. */
export function enqueueProfileSwitch(name: string): Promise<Profile> {
  const wanted = name.trim().slice(0, 40);
  return enqueue(async () => {
    const stored = await listProfiles();
    return resolveProfileSwitch(stored, wanted) ?? createProfile(wanted);
  });
}

/** Append a tutor note to one profile by id (never "the current one": the
 *  caller binds the session's own profile id, so a delayed note from lesson A
 *  can never land on B). The id may be a thunk resolved inside the queue at
 *  execution time, so a note that arrived while a naming was in flight lands
 *  on the named profile once the naming write ahead of it has run. Returns
 *  the updated profile, or undefined when the profile is gone. */
export function enqueueNote(profileId: string | (() => string), note: Note): Promise<Profile | undefined> {
  return enqueue(async () => {
    const id = typeof profileId === 'function' ? profileId() : profileId;
    if (!id) return undefined;
    return appendNote(id, note);
  });
}

/** Apply a tutor-learned grade, but only when the target is still the active
 *  profile at execution time. `getActiveId` is read inside the queue so a write
 *  that lost its race with a switch (or arrives after a restart) is dropped as
 *  stale. Returns the updated profile, or undefined when stale/invalid. */
export function enqueueProfileGrade(
  profileId: string, grade: number, getActiveId: () => string | null,
): Promise<Profile | undefined> {
  return enqueue(async () => {
    const activeId = getActiveId();
    if (!profileId || !activeId || profileId !== activeId) return undefined;
    if (!Number.isInteger(grade) || grade < 1 || grade > 12) return undefined;
    const current = await getProfile(activeId);
    if (!current) return undefined;
    if (current.grade === grade) return current;
    return updateProfile(activeId, { grade });
  });
}

/** Append a note to a profile, keeping the newest MAX_NOTES. */
export async function appendNote(profileId: string, note: Note): Promise<Profile | undefined> {
  let profile: Profile | undefined;
  if (idbBroken) {
    profile = memoryFallback.get(profileId);
  } else {
    try {
      profile = await tx<Profile | undefined>('readonly', (store) => store.get(profileId));
    } catch {
      idbBroken = true;
      profile = memoryFallback.get(profileId);
    }
  }
  if (!profile) return undefined;
  const notes = [...profile.notes, note].slice(-MAX_NOTES);
  const updated: Profile = { ...profile, notes };
  await saveProfile(updated);
  return updated;
}
