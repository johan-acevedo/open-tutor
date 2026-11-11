import { describe, expect, it } from 'vitest';
import { drawScreenPage, sanitizeSvg, wrapText } from './renderer';
import type { ScreenPage } from './types';

function mockContext() {
  const texts: { text: string; font: string }[] = [];
  let font = '400 16px sans-serif';
  const ctx = new Proxy(
    {},
    {
      get(_target, prop) {
        if (prop === 'font') return font;
        if (prop === 'measureText') return (text: string) => ({ width: text.length * 10 });
        if (prop === 'createLinearGradient') return () => ({ addColorStop() {} });
        if (prop === 'fillText') {
          return (text: string) => {
            texts.push({ text, font });
          };
        }
        return (..._args: unknown[]) => undefined;
      },
      set(_target, prop, value) {
        if (prop === 'font') font = value as string;
        return true;
      },
    },
  );
  return { ctx: ctx as unknown as CanvasRenderingContext2D, texts };
}

function exercisePage(overrides: Partial<ScreenPage> = {}): ScreenPage {
  return {
    id: 'p1',
    revision: 'r1',
    lessonId: 'lektion-1',
    kind: 'exercise',
    subject: 'Matte',
    title: 'Hur mycket är 7 + 5?',
    body: ['Räkna ut svaret och skriv det i svarsrutan.'],
    asset: null,
    svgAsset: null,
    answerLabel: 'Ditt svar',
    solution: 'Svaret är 12',
    sources: ['Matteboken'],
    revealed: false,
    createdAt: 1,
    ...overrides,
  };
}

describe('wrapText', () => {
  it('greedily wraps on word boundaries', () => {
    const { ctx } = mockContext();
    expect(wrapText(ctx, 'aa bb cc', 45)).toEqual(['aa', 'bb', 'cc']);
    expect(wrapText(ctx, 'aa bb', 100)).toEqual(['aa bb']);
    expect(wrapText(ctx, '', 100)).toEqual(['']);
  });
});

describe('sanitizeSvg', () => {
  it('strips scripts, handlers, iframes and javascript: URLs', () => {
    const dirty =
      '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script>' +
      '<circle onload="evil()" cx="5" cy="5" r="4"/>' +
      '<a href="javascript:alert(2)"><text>x</text></a>' +
      '<iframe src="https://evil.example"></iframe>' +
      '<foreignObject><div>no</div></foreignObject></svg>';
    const clean = sanitizeSvg(dirty);
    expect(clean).not.toContain('<script');
    expect(clean).not.toContain('onload');
    expect(clean).not.toContain('javascript:');
    expect(clean).not.toContain('<iframe');
    expect(clean).not.toContain('<foreignObject');
    expect(clean).toContain('<circle');
  });

  it('keeps safe generated maps', () => {
    const svg = '<svg xmlns="http://www.w3.org/2000/svg"><circle cx="5" cy="5" r="4"/></svg>';
    expect(sanitizeSvg(svg)).toContain('<circle');
  });
});

describe('drawScreenPage', () => {
  it('renders the question and draft but keeps a hidden solution out of pixels', () => {
    const { ctx, texts } = mockContext();
    drawScreenPage(ctx, { w: 1280, h: 800 }, exercisePage(), {
      draftText: '11',
      pageLabel: 'Sida 1 av 1',
    });
    const drawn = texts.map((t) => t.text).join('\n');
    expect(drawn).toContain('Hur mycket är 7 + 5?');
    expect(drawn).toContain('11');
    expect(drawn).toContain('Sida 1 av 1');
    expect(drawn).toContain('Facit är dolt');
    expect(drawn).not.toContain('Svaret är 12');
  });

  it('draws the revealed solution after a fox-gated reveal', () => {
    const { ctx, texts } = mockContext();
    drawScreenPage(ctx, { w: 1280, h: 800 }, exercisePage({ revealed: true }), { draftText: '12' });
    const drawn = texts.map((t) => t.text).join('\n');
    expect(drawn).toContain('Svaret är 12');
    expect(drawn).not.toContain('Facit är dolt');
  });

  it('shows a placeholder when an SVG asset has no preloaded drawable', () => {
    const { ctx, texts } = mockContext();
    drawScreenPage(
      ctx,
      { w: 390, h: 700 },
      exercisePage({ kind: 'geography', subject: 'Geografi', svgAsset: '<svg></svg>' }),
      {},
    );
    const drawn = texts.map((t) => t.text).join('\n');
    expect(drawn).toMatch(/laddas/);
  });
});
