// The diagram font (Nunito), loaded from our own server before any text is measured or drawn.
//
// Excalidraw registers its fonts only when a scene already uses them, so the first diagram would be
// measured in a fallback font and clip its labels. We register the two Latin files ourselves (the
// same files the library ships, in public/excalidraw/fonts) and wait for them. Swedish needs only
// these two; Cyrillic and Vietnamese are not served.

import { FONT_STACK, LINK_FONT_PX, NODE_FONT_PX } from './diagramModel';

const FILES = [
  {
    file: 'Nunito-Regular-XRXI3I6Li01BKofiOc5wtlZ2di8HDIkhdTQ3j6zbXWjgeg.woff2',
    range:
      'U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, U+2000-206F, U+2074, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD',
  },
  {
    file: 'Nunito-Regular-XRXI3I6Li01BKofiOc5wtlZ2di8HDIkhdTo3j6zbXWjgevT5.woff2',
    range:
      'U+0100-02AF, U+0304, U+0308, U+0329, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF',
  },
];

export const FONT_ERROR = 'Typsnittet för diagrammet kunde inte laddas.';

type FontSet = Pick<FontFaceSet, 'add' | 'load'> & Iterable<FontFace>;
type FaceFactory = (family: string, source: string, descriptors: FontFaceDescriptors) => FontFace;

let registered = false;

/** Make sure the Nunito files for `text` are loaded. Throws a Swedish message if they cannot be. */
export async function ensureDiagramFonts(
  text: string,
  fonts: FontSet = document.fonts,
  makeFace: FaceFactory = (family, source, descriptors) => new FontFace(family, source, descriptors),
  base: string = new URL('excalidraw/fonts/Nunito/', document.baseURI).href,
): Promise<void> {
  try {
    if (!registered) {
      for (const { file, range } of FILES) {
        fonts.add(makeFace('Nunito', `url(${base}${file}) format('woff2')`, { unicodeRange: range }));
      }
      registered = true;
    }
    const sample = text + 'ÅÄÖåäö';
    await Promise.all([fonts.load(`${NODE_FONT_PX}px ${FONT_STACK}`, sample), fonts.load(`${LINK_FONT_PX}px ${FONT_STACK}`, sample)]);
    const ready = [...fonts].some((f) => f.family.replace(/["']/g, '') === 'Nunito' && f.status === 'loaded');
    if (!ready) throw new Error('no Nunito face loaded');
  } catch {
    // A face that failed stays failed for this page; a reload fetches the files again.
    throw new Error(FONT_ERROR);
  }
}

/** For tests. */
export function resetDiagramFonts(): void {
  registered = false;
}
