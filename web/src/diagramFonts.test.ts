import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FONT_ERROR, ensureDiagramFonts, resetDiagramFonts } from './diagramFonts';

type Face = { family: string; status: string; source: string; descriptors: Record<string, string> };

function fakeFonts(outcome: 'loads' | 'fails' | 'nothing') {
  const faces: Face[] = [];
  const set = {
    add: vi.fn((face: Face) => void faces.push(face)),
    load: vi.fn(async (_font: string, _text: string) => {
      if (outcome === 'fails') throw new Error('NetworkError');
      if (outcome === 'loads') faces.forEach((f) => (f.status = 'loaded'));
      return [];
    }),
    [Symbol.iterator]: () => faces[Symbol.iterator](),
  };
  return { set, faces };
}
const factory = (family: string, source: string, descriptors: Record<string, string>): Face => ({ family, status: 'unloaded', source, descriptors });

beforeEach(() => resetDiagramFonts());

describe('ensureDiagramFonts', () => {
  it('registers the two Latin files from our own base URL, once, and waits for them', async () => {
    const { set, faces } = fakeFonts('loads');
    await ensureDiagramFonts('Växthusgaser', set as never, factory as never, 'http://127.0.0.1:1/excalidraw/fonts/Nunito/');
    await ensureDiagramFonts('Moln', set as never, factory as never, 'http://127.0.0.1:1/excalidraw/fonts/Nunito/');
    expect(faces).toHaveLength(2);
    expect(faces.every((f) => f.source.startsWith('url(http://127.0.0.1:1/excalidraw/fonts/Nunito/Nunito-Regular-'))).toBe(true);
    expect(faces.map((f) => f.descriptors.unicodeRange.startsWith('U+0000-00FF'))).toEqual([true, false]); // Latin, Latin extended
    expect(set.load).toHaveBeenCalledWith(expect.stringContaining('Nunito'), expect.stringContaining('Växthusgaser'));
    expect(set.load.mock.calls[0][1]).toContain('ÅÄÖåäö'); // Swedish letters are always requested
  });

  it('fails with a Swedish message when the files cannot be fetched', async () => {
    const { set } = fakeFonts('fails');
    await expect(ensureDiagramFonts('x', set as never, factory as never, 'http://x/')).rejects.toThrow(FONT_ERROR);
  });

  it('does not accept "nothing failed" as "the font loaded"', async () => {
    const { set } = fakeFonts('nothing');
    await expect(ensureDiagramFonts('x', set as never, factory as never, 'http://x/')).rejects.toThrow(FONT_ERROR);
  });
});
