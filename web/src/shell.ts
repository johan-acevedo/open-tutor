// Smart Screen shell, bundled as text from screen/shell/.
// Only the page body travels over LiveKit; the web app composes the frame itself,
// the same way screen/tools/screenkit.py compose() does it.
import { frameHtml, shellCss, shellJs, mapLanData } from 'virtual:screen-shell';
import { BANDS, type BandConfig } from './bands';

// Frame policy from screenkit.py (CSP). The frame stays sandbox="allow-scripts".
export const PAGE_CSP =
  "default-src 'none'; " +
  "script-src 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; " +
  "style-src 'unsafe-inline' https://cdn.jsdelivr.net; " +
  "font-src https://cdn.jsdelivr.net; " +
  "img-src data: https:; " +
  "connect-src https://cdn.jsdelivr.net https://commons.wikimedia.org";

/** Wrap a page body in the shell. Mirrors screenkit.py compose(): BODY last. */
export function composePage(body: string, band: BandConfig = BANDS.primary): string {
  // Replacer functions: a plain string replacement would read `$` patterns
  // (`$$`, `$&`, `$'` …) in the shell and the body. Python's replace is literal.
  return frameHtml
    .replace('<html lang="sv"', () => `<html lang="sv" data-band="${band.id}"`)
    .replace('{{CSP}}', () => PAGE_CSP)
    .replace('{{CSS}}', () => shellCss + '\n' + band.theme.stylesheet)
    .replace('{{LAN}}', () => mapLanData.replace(/</g, '\\u003c'))
    .replace('{{JS}}', () => shellJs.replace(/<\/script/g, '<\\/script'))
    .replace('{{BODY}}', () => body.replace(/[&<>]/g, character => {
      switch (character) {
        case '&': return '&amp;';
        case '<': return '&lt;';
        case '>': return '&gt;';
        default: return character;
      }
    }));
}
