/**
 * Binary asset handling for the Screen.
 *
 * Rule: Durable JSON docs and page records carry only `ScreenAssetRef`
 * values (id, sha-256 hash, MIME type, provenance, lesson/request scope,
 * status). The bytes themselves live here, in a separate per-profile
 * IndexedDB blob store with an in-memory fallback for tests and browsers
 * without IndexedDB.
 */
import type { ScreenAssetRef } from "./types";

export const MAX_BLOB_BYTES = 1_200_000;
const SHA256_HEX = /^[0-9a-f]{64}$/;

const ALLOWED_MIME_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
  "image/svg+xml",
]);

export interface BlobMeta {
  mimeType: string;
  provenance: string;
  lessonId: string;
  label?: string;
}

export interface BlobRecord {
  id: string;
  bytes: Uint8Array;
  meta: BlobMeta;
  hash: string;
  createdAt: number;
}

export interface ScreenBlobStore {
  put(id: string, bytes: Uint8Array, meta: BlobMeta): Promise<string>;
  get(id: string): Promise<BlobRecord | null>;
  has(id: string): Promise<boolean>;
  remove(id: string): Promise<void>;
}

export type AssetRefIssue =
  | "missing-id"
  | "bad-hash"
  | "mime-not-allowed"
  | "missing-provenance"
  | "missing-lesson"
  | "bad-status";

/** Synchronous format validation of an asset reference (no I/O). */
export function validateAssetRef(ref: ScreenAssetRef): AssetRefIssue[] {
  const issues: AssetRefIssue[] = [];
  if (!ref.id || ref.id.length > 128) issues.push("missing-id");
  if (!SHA256_HEX.test(ref.hash)) issues.push("bad-hash");
  if (!ALLOWED_MIME_TYPES.has(ref.mimeType)) issues.push("mime-not-allowed");
  if (!ref.provenance || ref.provenance.length > 300) issues.push("missing-provenance");
  if (!ref.lessonId) issues.push("missing-lesson");
  if (ref.status !== "staged" && ref.status !== "ready" && ref.status !== "discarded") {
    issues.push("bad-status");
  }
  return issues;
}

export function isAssetRefUsable(ref: ScreenAssetRef, lessonId: string): boolean {
  return (
    validateAssetRef(ref).length === 0 && ref.status === "ready" && ref.lessonId === lessonId
  );
}

/** Verify raw bytes against the reference: size cap, MIME sniff, sha-256. */
export async function verifyBlobBytes(
  bytes: Uint8Array,
  ref: Pick<ScreenAssetRef, "hash" | "mimeType">,
): Promise<{ ok: true } | { ok: false; reason: string }> {
  if (bytes.byteLength === 0) return { ok: false, reason: "empty-blob" };
  if (bytes.byteLength > MAX_BLOB_BYTES) return { ok: false, reason: "blob-too-large" };
  const sniffed = sniffMimeType(bytes);
  if (sniffed && sniffed !== ref.mimeType) {
    return { ok: false, reason: `mime-mismatch: declared ${ref.mimeType}, sniffed ${sniffed}` };
  }
  const hash = await sha256Hex(bytes);
  if (hash !== ref.hash.toLowerCase()) return { ok: false, reason: "hash-mismatch" };
  return { ok: true };
}

export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes as BufferSource);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Minimal magic-number sniff for the allowlisted raster types + SVG. */
export function sniffMimeType(bytes: Uint8Array): string | null {
  if (
    bytes.length > 8 &&
    bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47
  ) {
    return "image/png";
  }
  if (bytes.length > 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return "image/jpeg";
  }
  if (
    bytes.length > 12 &&
    bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50
  ) {
    return "image/webp";
  }
  if (bytes.length > 6 && bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46) {
    return "image/gif";
  }
  const head = new TextDecoder().decode(bytes.slice(0, 200)).trimStart();
  if (head.startsWith("<svg")) return "image/svg+xml";
  return null;
}

// ---------------------------------------------------------------------------
// Stores
// ---------------------------------------------------------------------------

function dbName(profileId: string): string {
  return `open-tutor-screen-blobs-${profileId.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 64)}`;
}

function openDb(name: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("no-indexeddb"));
      return;
    }
    const req = indexedDB.open(name, 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore("blobs", { keyPath: "id" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("indexeddb-open-failed"));
  });
}

function txDone(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error("indexeddb-transaction-failed"));
    tx.onabort = () => reject(tx.error ?? new Error("indexeddb-transaction-aborted"));
  });
}

function reqDone<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("indexeddb-request-failed"));
  });
}

/** IndexedDB-backed blob store; falls back to memory when IndexedDB fails. */
export function createBlobStore(profileId: string): ScreenBlobStore {
  const memory = createMemoryBlobStore();
  let db: IDBDatabase | null = null;
  let useMemory = false;

  async function conn(): Promise<IDBDatabase | null> {
    if (useMemory) return null;
    if (db) return db;
    try {
      db = await openDb(dbName(profileId));
      return db;
    } catch {
      useMemory = true;
      return null;
    }
  }

  return {
    async put(id, bytes, meta) {
      const now = Date.now();
      const hash = await sha256Hex(bytes);
      const record = { id, bytes, meta, hash, createdAt: now };
      const c = await conn();
      if (!c) return memory.put(id, bytes, meta);
      const t = c.transaction("blobs", "readwrite");
      t.objectStore("blobs").put(record);
      await txDone(t);
      return id;
    },
    async get(id) {
      const c = await conn();
      if (!c) return memory.get(id);
      const t = c.transaction("blobs", "readonly");
      const raw = await reqDone<{ id: string; bytes: Uint8Array; meta: BlobMeta; hash: string; createdAt: number } | undefined>(
        t.objectStore("blobs").get(id),
      );
      if (!raw) return null;
      return { id: raw.id, bytes: raw.bytes, meta: raw.meta, hash: raw.hash, createdAt: raw.createdAt };
    },
    async has(id) {
      return (await this.get(id)) !== null;
    },
    async remove(id) {
      const c = await conn();
      if (!c) return memory.remove(id);
      const t = c.transaction("blobs", "readwrite");
      t.objectStore("blobs").delete(id);
      await txDone(t);
    },
  };
}

export function createMemoryBlobStore(): ScreenBlobStore {
  const records = new Map<string, BlobRecord>();
  return {
    async put(id, bytes, meta) {
      const hash = await sha256Hex(bytes);
      records.set(id, { id, bytes: bytes.slice(), meta, hash, createdAt: Date.now() });
      return id;
    },
    async get(id) {
      return records.get(id) ?? null;
    },
    async has(id) {
      return records.has(id);
    },
    async remove(id) {
      records.delete(id);
    },
  };
}
