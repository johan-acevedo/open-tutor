// Learner profiles in IndexedDB (db `open-tutor`, store `profiles`).
// Tiny wrapper, no library. If IndexedDB fails, fall back to memory silently.

import type { Note } from './protocol';

export type Profile = {
  id: string;
  name: string;
  grade: number;
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

export async function createProfile(name: string, grade: number): Promise<Profile> {
  const profile: Profile = {
    id: newProfileId(),
    name: name.trim(),
    grade,
    notes: [],
    createdAt: Date.now(),
  };
  await saveProfile(profile);
  return profile;
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
