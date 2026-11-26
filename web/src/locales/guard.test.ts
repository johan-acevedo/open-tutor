import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { t } from './sv';

// Every user-visible Swedish string lives in web/src/locales/sv.ts. This guard
// fails if a Swedish-looking literal (å/ä/ö) appears anywhere else in web/src,
// outside tests. Add new copy to sv.ts and look it up with t('key', {name});
// the SvKey type makes a missing key a compile error.
const SRC = join(process.cwd(), 'src');

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) walk(full, out);
    else if (/\.(tsx?|jsx?)$/.test(entry)) out.push(full);
  }
  return out;
}

describe('Swedish catalogue guard', () => {
  it('keeps Swedish literals (å/ä/ö) in locales/ and tests only', () => {
    const offenders: string[] = [];
    for (const file of walk(SRC)) {
      const rel = file.slice(SRC.length + 1);
      if (rel.startsWith('locales/')) continue;
      if (/\.test\.(ts|tsx)$/.test(rel)) continue;
      const text = readFileSync(file, 'utf8');
      // Strip comments so a Swedish word in a comment does not fail the build;
      // user-visible copy is still caught because it lives in string literals.
      // (The catalogue itself is the only exception and is skipped above.)
      const noComments = text
        .replace(/\/\/.*$/gm, '')
        .replace(/\/\*[\s\S]*?\*\//g, '');
      const stringsOnly = Array.from(noComments.matchAll(/'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`/g))
        .map((m) => m[0])
        .join('\n');
      if (/[åäöÅÄÖ]/.test(stringsOnly)) offenders.push(rel);
    }
    expect(offenders).toEqual([]);
  });

  it('interpolates {name} placeholders', () => {
    expect(t('band.primary.returningBubble', { name: 'Noa' })).toBe('Hej Noa!');
    expect(t('shell.loading', { topic: 'historia' })).toBe('Laddar historia …');
  });

  it('has renamed Open Tutor to Talarum in user-visible copy', () => {
    const text = readFileSync(join(SRC, 'locales', 'sv.ts'), 'utf8');
    expect(text).not.toContain('Open Tutor');
    expect(text).toContain('Talarum');
  });

  it('never promises open source, non-profit or forever-free', () => {
    const text = readFileSync(join(SRC, 'locales', 'sv.ts'), 'utf8').toLowerCase();
    for (const banned of ['open source', '\u00f6ppen k\u00e4llkod', 'ideell', 'alltid gratis']) {
      expect(text).not.toContain(banned);
    }
  });
});
