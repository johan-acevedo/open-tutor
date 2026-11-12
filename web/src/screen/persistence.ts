/**
 * Device-local persistence for the Screen deck.
 *
 * One deck per learner profile and lesson (interrupted lessons resume from
 * here), plus archived lesson summaries so a returning learner gets a warm
 * greeting without loading the old board. IndexedDB with an in-memory
 * fallback when IndexedDB is unavailable (tests, very old browsers).
 */
import type { LessonSummary, ScreenDeckSnapshot } from "./types";

export interface ScreenStore {
  loadDeck(profileId: string, lessonId: string): Promise<ScreenDeckSnapshot | null>;
  saveDeck(snapshot: ScreenDeckSnapshot): Promise<void>;
  loadSummaries(profileId: string): Promise<LessonSummary[]>;
  saveSummary(summary: LessonSummary): Promise<void>;
}

function deckKey(profileId: string, lessonId: string): string {
  return `${profileId}\n${lessonId}`;
}

export function createMemoryScreenStore(): ScreenStore {
  const decks = new Map<string, ScreenDeckSnapshot>();
  const summaries = new Map<string, LessonSummary[]>();
  return {
    async loadDeck(profileId, lessonId) {
      return decks.get(deckKey(profileId, lessonId)) ?? null;
    },
    async saveDeck(snapshot) {
      decks.set(deckKey(snapshot.profileId, snapshot.lessonId), snapshot);
    },
    async loadSummaries(profileId) {
      return summaries.get(profileId) ?? [];
    },
    async saveSummary(summary) {
      const list = summaries.get(summary.profileId) ?? [];
      summaries.set(
        summary.profileId,
        [...list.filter((s) => s.lessonId !== summary.lessonId), summary].slice(-10),
      );
    },
  };
}

const DB_NAME = "open-tutor-screen";
const DECKS = "decks";
const SUMMARIES = "summaries";

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("no-indexeddb"));
      return;
    }
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(DECKS);
      req.result.createObjectStore(SUMMARIES);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("indexeddb-open-failed"));
  });
}

function requestDone<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("indexeddb-request-failed"));
  });
}

function txDone(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error("indexeddb-transaction-failed"));
    tx.onabort = () => reject(tx.error ?? new Error("indexeddb-transaction-aborted"));
  });
}

/** IndexedDB store; degrades to memory when IndexedDB is unavailable. */
export function createIndexedDbScreenStore(): ScreenStore {
  const memory = createMemoryScreenStore();
  let db: IDBDatabase | null = null;
  let useMemory = false;

  async function conn(): Promise<IDBDatabase | null> {
    if (useMemory) return null;
    if (db) return db;
    try {
      db = await openDb();
      return db;
    } catch {
      useMemory = true;
      return null;
    }
  }

  async function put(store: string, key: string, value: unknown): Promise<void> {
    const c = await conn();
    if (!c) {
      if (store === DECKS) await memory.saveDeck(value as ScreenDeckSnapshot);
      else await memory.saveSummary(value as LessonSummary);
      return;
    }
    const t = c.transaction(store, "readwrite");
    t.objectStore(store).put(value, key);
    await txDone(t);
  }

  async function get<T>(store: string, key: string): Promise<T | null> {
    const c = await conn();
    if (!c) return null;
    const t = c.transaction(store, "readonly");
    const raw = await requestDone<T | undefined>(t.objectStore(store).get(key));
    return raw ?? null;
  }

  return {
    async loadDeck(profileId, lessonId) {
      const key = deckKey(profileId, lessonId);
      const stored = await get<ScreenDeckSnapshot>(DECKS, key);
      if (stored) return stored;
      return memory.loadDeck(profileId, lessonId);
    },
    async saveDeck(snapshot) {
      await put(DECKS, deckKey(snapshot.profileId, snapshot.lessonId), snapshot);
      await memory.saveDeck(snapshot);
    },
    async loadSummaries(profileId) {
      const stored = await get<LessonSummary[]>(SUMMARIES, profileId);
      if (stored) return stored;
      return memory.loadSummaries(profileId);
    },
    async saveSummary(summary) {
      const current = await this.loadSummaries(summary.profileId);
      const next = [...current.filter((s) => s.lessonId !== summary.lessonId), summary].slice(-10);
      await put(SUMMARIES, summary.profileId, next);
      await memory.saveSummary(summary);
    },
  };
}
