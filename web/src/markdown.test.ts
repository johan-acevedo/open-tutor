import { describe, expect, it } from 'vitest';
import { renderMarkdown } from './markdown';

describe('renderMarkdown', () => {
  it('escapes HTML injection', () => {
    const html = renderMarkdown('<script>alert(1)</script><img src=x onerror=alert(2)>');
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('<img');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('&lt;img');
  });

  it('renders bold, italic, lists and line breaks', () => {
    const html = renderMarkdown('Hej **Leo** och *Elsa*\n- ett\n- två');
    expect(html).toContain('<strong>Leo</strong>');
    expect(html).toContain('<em>Elsa</em>');
    expect(html).toContain('<ul>');
    expect(html).toContain('<li>ett</li>');
  });

  it('renders inline and display math with KaTeX', () => {
    const html = renderMarkdown('Lös $3x + 5 = 20$ nu\n\n$$x = 5$$');
    expect(html).toContain('katex');
    expect(html).not.toContain('$3x');
  });

  it('leaves unmatched dollars alone', () => {
    const html = renderMarkdown('Det kostar 5 $ idag');
    expect(html).toContain('5 $ idag');
  });
});
