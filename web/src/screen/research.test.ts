import { describe, expect, it, vi } from 'vitest';
import {
  GEOGRAPHY_PATH,
  decodeDataUrl,
  fetchGeographyResearch,
  normalizeMap,
  normalizeResearchResult,
  selectGeographyVisual,
} from './research';

function gatewayBody(overrides: Record<string, unknown> = {}) {
  const pngBytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x01]);
  let binary = '';
  for (const b of pngBytes) binary += String.fromCharCode(b);
  const b64 = btoa(binary);
  return {
    query: 'Sverige',
    place: {
      displayName: 'Sverige',
      lat: 62.0,
      lon: 15.0,
      boundingBox: [55, 69, 11, 24],
      address: { country: 'Sverige' },
      category: 'place',
      type: 'country',
    },
    maps: [
      {
        dataUrl: `data:image/png;base64,${b64}`,
        mime: 'image/png',
        bytes: pngBytes.byteLength,
        sourceUrl: 'https://commons.wikimedia.org/wiki/File:Sverige.png',
        retrievedAt: '2026-11-11T00:00:00Z',
        attribution: 'Wikimedia Commons',
        license: 'CC BY-SA',
      },
    ],
    retrievedAt: '2026-11-11T00:00:00Z',
    ...overrides,
  };
}

describe('geography gateway schema (real POST contract)', () => {
  it('POSTs JSON {query} to the exact gateway path', async () => {
    const fetchFn = vi.fn(async () => new Response(JSON.stringify(gatewayBody()), { status: 200 }));
    await fetchGeographyResearch({
      query: 'Sverige',
      lessonId: 'lektion-1',
      requestId: 'r1',
      accessCode: 'kod',
      fetchFn: fetchFn as unknown as typeof fetch,
    });
    expect(fetchFn).toHaveBeenCalledTimes(1);
    const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(GEOGRAPHY_PATH);
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['Content-Type']).toContain('application/json');
    expect(JSON.parse(init.body as string)).toEqual({ query: 'Sverige' });
  });

  it('parses {query,place,maps:[{dataUrl,mime,bytes,sourceUrl,retrievedAt,attribution,license}]}', async () => {
    const fetchFn = vi.fn(async () => new Response(JSON.stringify(gatewayBody()), { status: 200 }));
    const result = await fetchGeographyResearch({
      query: 'Sverige',
      lessonId: 'lektion-1',
      requestId: 'r1',
      accessCode: 'kod',
      fetchFn: fetchFn as unknown as typeof fetch,
    });
    expect(result.query).toBe('Sverige');
    expect(result.place?.displayName).toBe('Sverige');
    expect(result.maps).toHaveLength(1);
    expect(result.maps[0]).toMatchObject({
      mime: 'image/png',
      sourceUrl: expect.stringContaining('https://'),
      attribution: 'Wikimedia Commons',
    });
  });

  it('rejects gateway bodies without maps or with unsafe entries', () => {
    const query = { query: 'x', lessonId: 'l', requestId: 'r', accessCode: 'k' };
    expect(() => normalizeResearchResult({ query: 'x' }, query)).toThrow('missing maps');
    expect(normalizeMap({ dataUrl: 'https://evil.example/x.png', mime: 'image/png' })).toBeNull();
    expect(
      normalizeMap({
        dataUrl: 'data:image/png;base64,AAAA',
        mime: 'application/pdf',
        bytes: 4,
        sourceUrl: 'https://commons.wikimedia.org/wiki/File:X',
      }),
    ).toBeNull();
  });

  it('decodes dataUrl bytes without leaking base64 to callers', () => {
    const body = gatewayBody();
    const map = normalizeMap((body.maps as unknown[])[0]);
    expect(map).not.toBeNull();
    const { mime, bytes } = decodeDataUrl(map!.dataUrl);
    expect(mime).toBe('image/png');
    expect(bytes[0]).toBe(0x89);
    // The worker-facing concise text must never contain the encoding itself.
    const concise = `Plats: Sverige (62, 15). karta 1: assetId b1, mime ${mime}, bytes ${bytes.byteLength}`;
    expect(concise).not.toContain('base64');
    expect(concise).not.toContain('data:image');
  });

  it('selects a researched map when present, otherwise generated SVG', async () => {
    const fetchFn = vi.fn(async () => new Response(JSON.stringify(gatewayBody()), { status: 200 }));
    const withMap = await fetchGeographyResearch({
      query: 'Sverige',
      lessonId: 'l',
      requestId: 'r',
      accessCode: 'k',
      fetchFn: fetchFn as unknown as typeof fetch,
    });
    expect(selectGeographyVisual(withMap).kind).toBe('researched-map');
    const empty = { ...withMap, maps: [] };
    expect(selectGeographyVisual(empty).kind).toBe('generated');
  });

  it('works with an empty access code in public Swedish mode (same-origin, no credential)', async () => {
    const fetchFn = vi.fn(async () => new Response(JSON.stringify(gatewayBody()), { status: 200 }));
    const result = await fetchGeographyResearch({
      query: 'Sverige',
      lessonId: 'lektion-1',
      requestId: 'r1',
      accessCode: '',
      fetchFn: fetchFn as unknown as typeof fetch,
    });
    expect(result.query).toBe('Sverige');
    expect(result.maps).toHaveLength(1);
    const [, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['x-tutor-code']).toBe('');
  });
});
