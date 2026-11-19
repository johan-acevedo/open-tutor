// Smart Screen shell, bundled as text from screen/shell/.
// Only the page body travels over LiveKit; the web app composes the frame itself,
// the same way screen/tools/screenkit.py compose() does it.
import { frameHtml, shellCss, shellJs, mapLanData } from 'virtual:screen-shell';
import { BANDS, type BandConfig } from './bands';
import { htmlLang, localeId, sv } from './locales/sv';

// Frame policy from screenkit.py (CSP). The frame stays sandbox="allow-scripts".
export const PAGE_CSP =
  "default-src 'none'; " +
  "script-src 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; " +
  "style-src 'unsafe-inline' https://cdn.jsdelivr.net; " +
  "font-src https://cdn.jsdelivr.net; " +
  "img-src data: https:; " +
  "connect-src https://cdn.jsdelivr.net https://commons.wikimedia.org";

/** Shell strings for the frame, from the web catalogue (mirrors
 *  screen/shell/locales/sv.json for the server composer). */
export function shellStrings() {
  return {
    send: sv['shell.send'],
    sent: sv['shell.sent'],
    answerLabel: sv['shell.answerLabel'],
    gapLabel: sv['shell.gapLabel'],
    loading: sv['shell.loading'],
    bc: sv['shell.bc'],
    ad: sv['shell.ad'],
    mapCreditHistorical: sv['shell.mapCreditHistorical'],
    mapCredit: sv['shell.mapCredit'],
  };
}

/** Wrap a page body in the shell. Mirrors screenkit.py compose(): BODY last.
 *  The frame language follows the active locale, and the shell's visible
 *  labels are injected as JSON (default Swedish). */
export function composePage(body: string, band: BandConfig = BANDS.primary, locale: string = localeId): string {
  // Replacer functions: a plain string replacement would read `$` patterns
  // (`$$`, `$&`, `$'` …) in the shell and the body. Python's replace is literal.
  const stringsJson = JSON.stringify(shellStrings()).replace(/</g, '\\u003c');
  return frameHtml
    .replace('<html lang="{{LANG}}"', () => `<html lang="${locale}" data-band="${band.id}"`)
    .replace('<html lang="sv"', () => `<html lang="${locale || htmlLang}" data-band="${band.id}"`)
    .replace('{{LANG}}', () => locale)
    .replace('{{CSP}}', () => PAGE_CSP)
    .replace('{{CSS}}', () => shellCss + '\n' + band.theme.stylesheet)
    .replace('{{LAN}}', () => mapLanData.replace(/</g, '\\u003c'))
    .replace('{{STRINGS}}', () => stringsJson)
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
