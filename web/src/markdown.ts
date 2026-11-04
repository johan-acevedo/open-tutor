// Minimal safe Markdown for tutor text cards:
// paragraphs, **bold**, *italic*, lists, line breaks,
// inline $…$ and display $$…$$ via KaTeX. All HTML is escaped.

import katex from 'katex';

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderInline(text: string): string {
  // text is already HTML-escaped here; only insert our own tags.
  let out = text;
  out = out.replace(/\*\*([\s\S]+?)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[^*\w])\*([^*\n]+?)\*/g, '$1<em>$2</em>');
  return out;
}

function renderMathPlaceholders(source: string): { text: string; maths: string[] } {
  const maths: string[] = [];
  // Display math first so $$…$$ is not eaten by the inline rule.
  let text = source.replace(/\$\$([\s\S]+?)\$\$/g, (_m, body: string) => {
    const idx = maths.length;
    let html: string;
    try {
      html = katex.renderToString(body, { displayMode: true, throwOnError: false });
    } catch {
      html = `<code>${escapeHtml(body)}</code>`;
    }
    maths.push(html);
    return `\u0000MATH${idx}\u0000`;
  });
  text = text.replace(/\$([^$\n]+?)\$/g, (_m, body: string) => {
    const idx = maths.length;
    let html: string;
    try {
      html = katex.renderToString(body, { displayMode: false, throwOnError: false });
    } catch {
      html = `<code>${escapeHtml(body)}</code>`;
    }
    maths.push(html);
    return `\u0000MATH${idx}\u0000`;
  });
  return { text, maths };
}

function restoreMaths(html: string, maths: string[]): string {
  return html.replace(/\u0000MATH(\d+)\u0000/g, (_m, n: string) => maths[Number(n)] ?? '');
}

function isListItem(line: string): boolean {
  return /^(\s*[-*]\s+|\s*\d+[.)]\s+)/.test(line);
}

function stripListMarker(line: string): string {
  return line.replace(/^(\s*[-*]\s+|\s*\d+[.)]\s+)/, '');
}

/**
 * Render tutor markdown to safe HTML. Never emits raw author HTML:
 * everything is escaped before our own tags and KaTeX output are added.
 */
export function renderMarkdown(source: string): string {
  const { text, maths } = renderMathPlaceholders(source);
  const escaped = escapeHtml(text);
  const lines = escaped.split('\n');
  const blocks: string[] = [];
  let para: string[] = [];
  let list: string[] = [];

  const flushPara = () => {
    if (para.length > 0) {
      const joined = para.join('<br />');
      blocks.push(`<p>${renderInline(joined)}</p>`);
      para = [];
    }
  };
  const flushList = () => {
    if (list.length > 0) {
      const items = list.map((l) => `<li>${renderInline(l)}</li>`).join('');
      blocks.push(`<ul>${items}</ul>`);
      list = [];
    }
  };

  for (const line of lines) {
    if (line.trim() === '') {
      flushPara();
      flushList();
      continue;
    }
    if (isListItem(line)) {
      flushPara();
      list.push(stripListMarker(line).trim());
    } else {
      flushList();
      para.push(line.trim());
    }
  }
  flushPara();
  flushList();
  return restoreMaths(blocks.join('\n'), maths);
}
