import { describe, expect, it } from 'vitest';
import { composePage, PAGE_CSP } from './shell';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';

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

  it('carries the body as inert escaped text before the empty page main', () => {
    const mainAt = doc.indexOf('<main class="ot-page" id="page">');
    expect(mainAt).toBeGreaterThan(-1);
    expect(doc).toContain('<template id="ot-source">&lt;h1&gt;Vad är klockan?&lt;/h1&gt;&lt;p&gt;$3+4$&lt;/p&gt;</template>');
    expect(doc).not.toContain(body);
    // A body can never inject into the shell slots.
    expect(composePage('{{CSS}}')).toContain('<template id="ot-source">{{CSS}}</template>');
  });

  it('cannot escape the inert body with closing tags or replacement patterns', () => {
    const hostile = '</template><script>window.attack = true</script><p onclick="attack()">$& &amp;</p>';
    const output = composePage(hostile);
    expect(output).not.toContain(hostile);
    expect(output).toContain('&lt;/template&gt;&lt;script&gt;window.attack = true&lt;/script&gt;');
    expect(output).toContain('$&amp; &amp;amp;');
  });

  it('encodes the body exactly like the server renderer', () => {
    const input = '</template><p title="å & ö">$& &amp; {{JS}}</p>';
    const python = execFileSync('python3', ['-c',
      'import sys; sys.path.insert(0, "screen/tools"); import screenkit; sys.stdout.write(screenkit.compose(sys.stdin.read()))',
    ], { input, encoding: 'utf8', cwd: resolve(process.cwd(), '..') });
    const source = /<template id="ot-source">([\s\S]*?)<\/template>/;
    expect(composePage(input).match(source)?.[1]).toBe(python.match(source)?.[1]);
  });
});
