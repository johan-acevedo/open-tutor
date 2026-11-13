import { describe, expect, it } from 'vitest';
import { composePage, PAGE_CSP } from './shell';

// The browser composes the frame the same way screen/tools/screenkit.py
// compose() does: frame.html with CSP, shell CSS, shell JS and the body.
describe('composePage', () => {
  const body = '<h1>Vad är klockan?</h1><p>$3+4$</p>';
  const doc = composePage(body);

  it('inlines the shell with the frame content security policy', () => {
    expect(doc).toContain(`content="${PAGE_CSP}"`);
    expect(PAGE_CSP).toContain('connect-src https://cdn.jsdelivr.net https://commons.wikimedia.org');
    // Shell CSS and JS travel in full, `$` sequences untouched.
    expect(doc).toContain('.ot-page');
    expect(doc).toContain(`s.indexOf('$')`);
  });

  it('carries Sweden\'s 21 län as data inside the frame, not in the page body', () => {
    // The region polygons travel with the shell: a page body stays far under the LiveKit RPC limit.
    expect(doc).toContain('id="ot-map-data"');
    expect(doc).toContain('"regions":[{"code":"AB","name":"Stockholm"');
    expect(doc.indexOf('id="ot-map-data"')).toBeLessThan(doc.indexOf('<main class="ot-page"'));
    expect(body).not.toContain('"regions"');
  });

  it('puts the body last inside the page main', () => {
    const mainAt = doc.indexOf('<main class="ot-page" id="page">');
    expect(mainAt).toBeGreaterThan(-1);
    expect(doc.indexOf(body)).toBeGreaterThan(mainAt);
    // A body can never inject into the shell slots.
    expect(composePage('{{CSS}}')).toContain('<main class="ot-page" id="page">\n{{CSS}}');
  });
});
