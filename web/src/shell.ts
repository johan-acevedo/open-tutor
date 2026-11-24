// Smart Screen shell, bundled as text from screen/shell/.
// Only the page body travels over LiveKit; the web app composes the frame itself,
// the same way screen/tools/screenkit.py compose() does it.
import { frameHtml, shellCss, shellJs, mapLanData, uiSdkJs } from 'virtual:screen-shell';
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
    orderLabel: sv['shell.orderLabel'],
    orderUp: sv['shell.orderUp'],
    orderDown: sv['shell.orderDown'],
    orderMoved: sv['shell.orderMoved'],
    matchChoose: sv['shell.matchChoose'],
    matchFor: sv['shell.matchFor'],
    choiceLabel: sv['shell.choiceLabel'],
    loading: sv['shell.loading'],
    bc: sv['shell.bc'],
    ad: sv['shell.ad'],
    mapCreditHistorical: sv['shell.mapCreditHistorical'],
    mapCredit: sv['shell.mapCredit'],
  };
}

/** Model-facing experiment blocks that need the inlined UI SDK bundle. */
export const SDK_TAGS = ['ot-order', 'ot-match', 'ot-sdk-choice', 'ot-sdk-answer'] as const;

/** True when the page body uses one of the experiment blocks. */
export function hasSdkBlocks(body: string): boolean {
  return new RegExp(`<\\s*(?:${SDK_TAGS.join('|')})[\\s>]`).test(body || '');
}

/** Wrap a page body in the shell. Mirrors screenkit.py compose(): BODY last.
 *  The frame language follows the active locale, and the shell's visible
 *  labels are injected as JSON (default Swedish). `uiSdk: 'auto'` (default)
 *  inlines the experiment bundle only where SDK blocks are present. */
export function composePage(body: string, band: BandConfig = BANDS.primary, locale: string = localeId, uiSdk: boolean | 'auto' = 'auto'): string {
  // Replacer functions: a plain string replacement would read `$` patterns
  // (`$$`, `$&`, `$'` …) in the shell and the body. Python's replace is literal.
  const stringsJson = JSON.stringify(shellStrings()).replace(/</g, '\\u003c');
  const wantSdk = uiSdk === 'auto' ? hasSdkBlocks(body) : uiSdk;
  const sdk = wantSdk ? uiSdkJs : '';
  if (wantSdk && !sdk) {
    throw new Error('UI SDK bundle missing: run screen/shell/ui-sdk/build.sh');
  }
  return frameHtml
    .replace('{{UI_SDK_JS}}', () => (sdk ? `<script>${sdk.replace(/<\/script/g, '<\\/script')}</script>` : ''))
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
