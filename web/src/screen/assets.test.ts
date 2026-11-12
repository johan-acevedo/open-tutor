import { describe, expect, it } from 'vitest';
import {
  createMemoryBlobStore,
  isAssetRefUsable,
  sha256Hex,
  sniffMimeType,
  validateAssetRef,
  verifyBlobBytes,
} from './assets';
import type { ScreenAssetRef } from './types';

function ref(overrides: Partial<ScreenAssetRef> = {}): ScreenAssetRef {
  return {
    id: 'b1',
    hash: 'a'.repeat(64),
    mimeType: 'image/png',
    provenance: 'wikimedia:Fil:Sverige.png',
    lessonId: 'lektion-1',
    status: 'ready',
    ...overrides,
  };
}

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00]);

describe('validateAssetRef', () => {
  it('accepts a well-formed ready reference', () => {
    expect(validateAssetRef(ref())).toEqual([]);
  });

  it('flags bad hashes, MIME types, provenance, lessons and statuses', () => {
    expect(validateAssetRef(ref({ hash: 'xyz' }))).toContain('bad-hash');
    expect(validateAssetRef(ref({ mimeType: 'application/pdf' }))).toContain('mime-not-allowed');
    expect(validateAssetRef(ref({ provenance: '' }))).toContain('missing-provenance');
    expect(validateAssetRef(ref({ lessonId: '' }))).toContain('missing-lesson');
    expect(validateAssetRef(ref({ status: 'weird' as never }))).toContain('bad-status');
  });

  it('isAssetRefUsable requires ready status and the current lesson', () => {
    expect(isAssetRefUsable(ref(), 'lektion-1')).toBe(true);
    expect(isAssetRefUsable(ref(), 'lektion-2')).toBe(false);
    expect(isAssetRefUsable(ref({ status: 'staged' }), 'lektion-1')).toBe(false);
  });
});

describe('sniffMimeType', () => {
  it('sniffs png, jpeg, webp, gif and svg', () => {
    expect(sniffMimeType(PNG)).toBe('image/png');
    expect(sniffMimeType(new Uint8Array([0xff, 0xd8, 0xff, 0x00]))).toBe('image/jpeg');
    const webp = new Uint8Array(13);
    webp.set([0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x45, 0x42, 0x50]);
    expect(sniffMimeType(webp)).toBe('image/webp');
    expect(sniffMimeType(new Uint8Array([0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x00, 0x00]))).toBe(
      'image/gif',
    );
    expect(sniffMimeType(new TextEncoder().encode('<svg xmlns="x"></svg>'))).toBe('image/svg+xml');
    expect(sniffMimeType(new Uint8Array([1, 2, 3, 4]))).toBeNull();
  });
});

describe('verifyBlobBytes', () => {
  it('accepts matching bytes and rejects mismatches, empties and oversize blobs', async () => {
    const hash = await sha256Hex(PNG);
    expect(await verifyBlobBytes(PNG, { hash, mimeType: 'image/png' })).toEqual({ ok: true });
    expect(await verifyBlobBytes(PNG, { hash: 'b'.repeat(64), mimeType: 'image/png' })).toEqual({
      ok: false,
      reason: 'hash-mismatch',
    });
    expect(await verifyBlobBytes(PNG, { hash, mimeType: 'image/jpeg' })).toMatchObject({ ok: false });
    expect(await verifyBlobBytes(new Uint8Array(0), { hash, mimeType: 'image/png' })).toMatchObject({
      ok: false,
    });
    expect(
      await verifyBlobBytes(new Uint8Array(1_200_001), { hash, mimeType: 'image/png' }),
    ).toMatchObject({ ok: false, reason: 'blob-too-large' });
  });
});

describe('memory blob store', () => {
  it('round-trips bytes with content hashes', async () => {
    const store = createMemoryBlobStore();
    const id = await store.put('b1', PNG, {
      mimeType: 'image/png',
      provenance: 'test',
      lessonId: 'lektion-1',
    });
    expect(id).toBe('b1');
    expect(await store.has('b1')).toBe(true);
    const record = await store.get('b1');
    expect(record?.hash).toBe(await sha256Hex(PNG));
    expect(record?.bytes).toEqual(PNG);
    await store.remove('b1');
    expect(await store.get('b1')).toBeNull();
  });
});
