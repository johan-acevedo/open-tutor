// Smart Screen shell, bundled as text from screen/shell/.
// Only the page body travels over LiveKit; the web app composes the frame itself,
// the same way screen/tools/screenkit.py compose() does it.
import { frameHtml, shellCss, shellJs } from 'virtual:screen-shell';

// Frame policy from screenkit.py (CSP). The frame stays sandbox="allow-scripts".
export const PAGE_CSP =
  "default-src 'none'; " +
  "script-src 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; " +
  "style-src 'unsafe-inline' https://cdn.jsdelivr.net; " +
  "font-src https://cdn.jsdelivr.net; " +
  "img-src data: https:; " +
  "connect-src https://cdn.jsdelivr.net https://commons.wikimedia.org";

/** Wrap a page body in the shell. Mirrors screenkit.py compose(): BODY last. */
export function composePage(body: string): string {
  // Replacer functions: a plain string replacement would read `$` patterns
  // (`$$`, `$&`, `$'` …) in the shell and the body. Python's replace is literal.
  return frameHtml
    .replace('{{CSP}}', () => PAGE_CSP)
    .replace('{{CSS}}', () => shellCss)
    .replace('{{JS}}', () => shellJs.replace(/<\/script/g, '<\\/script'))
    .replace('{{BODY}}', () => body);
}
