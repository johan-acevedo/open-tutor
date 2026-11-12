import { afterEach, describe, expect, it, vi } from 'vitest';
import { createMemoryBlobStore } from './assets';
import {
  decodeSvgDrawable,
  drawContain,
  drawScreenPage,
  renderScreenPage,
  resolveScreenAssets,
  sanitizeSvg,
  wrapText,
  type ScreenRenderResult,
} from './renderer';
import type { ScreenPage } from './types';

function mockContext() {
  const texts: { text: string; font: string; y: number }[] = [];
  let font = '400 16px sans-serif';
  const ctx = new Proxy(
    {},
    {
      get(_target, prop) {
        if (prop === 'font') return font;
        if (prop === 'measureText') return (text: string) => ({ width: text.length * 10 });
        if (prop === 'createLinearGradient') return () => ({ addColorStop() {} });
        if (prop === 'fillText') {
          return (text: string, _x: number, y: number) => {
            texts.push({ text, font, y });
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
  it.each([240, 400])('keeps the question and revealed solution visible on a 390 by %i phone canvas', (h) => {
    const { ctx, texts } = mockContext();
    drawScreenPage(ctx, { w: 390, h }, exercisePage({ revealed: true }), { draftText: '12' });
    expect(texts.map((t) => t.text).join('\n')).toContain('Hur mycket är 7 + 5?');
    expect(texts.map((t) => t.text).join('\n')).toContain('Svaret är 12');
    expect(texts.every((t) => t.y > 0 && t.y < h)).toBe(true);
  });

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

  it('draws a rasterised SVG instead of the placeholder when resolved', () => {
    const draws: string[] = [];
    const { ctx, texts } = mockContext();
    const withDraw = new Proxy(ctx, {
      get(target, prop, receiver) {
        if (prop === 'drawImage') {
          return (..._args: unknown[]) => {
            draws.push('drawImage');
          };
        }
        return Reflect.get(target as object, prop, receiver);
      },
    });
    const fakeDrawable = { width: 200, height: 100 } as unknown as CanvasImageSource;
    drawScreenPage(
      withDraw as unknown as CanvasRenderingContext2D,
      { w: 390, h: 700 },
      exercisePage({ kind: 'geography', subject: 'Geografi', svgAsset: '<svg></svg>' }),
      { svgImage: fakeDrawable },
    );
    const drawn = texts.map((t) => t.text).join('\n');
    expect(draws).toContain('drawImage');
    expect(drawn).not.toMatch(/laddas/);
  });
});

describe('resolveScreenAssets (SVG rasterisation)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('rasterises sanitized SVG via createImageBitmap where feasible', async () => {
    const fakeBitmap = { width: 10, height: 10 } as unknown as ImageBitmap;
    vi.stubGlobal('createImageBitmap', vi.fn(async () => fakeBitmap));
    const store = createMemoryBlobStore();
    const page = {
      id: 'p1',
      revision: 'r1',
      lessonId: 'lektion-1',
      kind: 'geography',
      subject: 'Geografi',
      title: 'Sverige',
      body: ['Var ligger Sverige?'],
      asset: null,
      svgAsset: '<svg xmlns="http://www.w3.org/2000/svg"><circle cx="5" cy="5" r="4"/></svg>',
      answerLabel: 'Ditt svar',
      solution: 'I Norden',
      sources: [],
      revealed: false,
      createdAt: 1,
    } as ScreenPage;
    const assets = await resolveScreenAssets(page, store, '', 'Sida 1 av 1');
    expect(assets.svgImage).toBe(fakeBitmap);
    // The bitmap path must receive an SVG blob, not an arbitrary URL.
    const blob = (vi.mocked(globalThis.createImageBitmap).mock.calls[0]?.[0] as Blob | undefined);
    expect(blob).toBeInstanceOf(Blob);
    expect(blob?.type).toBe('image/svg+xml');
  });

  it('falls back to Image/object-URL when createImageBitmap is unavailable', async () => {
    vi.stubGlobal('createImageBitmap', undefined);
    const fakeImg = { width: 20, height: 20 } as unknown as HTMLImageElement;
    const created: string[] = [];
    vi.stubGlobal('URL', {
      createObjectURL: (b: Blob) => {
        created.push(b.type);
        return 'blob:svg-test';
      },
      revokeObjectURL: () => {},
    } as unknown as typeof URL);
    class FakeImage {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      src = '';
      constructor() {
        setTimeout(() => this.onload?.(), 0);
      }
    }
    vi.stubGlobal('Image', FakeImage as unknown as typeof Image);
    const drawable = await decodeSvgDrawable('<svg xmlns="http://www.w3.org/2000/svg"></svg>');
    expect(drawable).toBeDefined();
    expect(created).toContain('image/svg+xml');
    void fakeImg;
  });

  it('drawContain letterboxes instead of cropping (contain, not cover)', () => {
    const calls: number[][] = [];
    const ctx = { drawImage: (...args: unknown[]) => calls.push(args as number[]) } as unknown as CanvasRenderingContext2D;
    const wide = { width: 400, height: 100 } as unknown as CanvasImageSource;
    drawContain(ctx, wide, 0, 0, 100, 100);
    expect(calls).toHaveLength(1);
    const [_img, _x, _y, dw, dh] = calls[0] as unknown as [unknown, number, number, number, number];
    // 400x100 into 100x100 contain-fit => 100x25, fully visible
    expect(Math.round(dw!)).toBe(100);
    expect(Math.round(dh!)).toBe(25);
  });

describe('geography responsive layout', () => {
    function mockGeoContext() {
      const texts: { text: string; font: string; y: number }[] = [];
      const draws: { x: number; y: number; dw: number; dh: number }[] = [];
      let font = '400 16px sans-serif';
      const ctx = new Proxy(
        {},
        {
          get(_target, prop) {
            if (prop === 'font') return font;
            if (prop === 'measureText') return (text: string) => ({ width: text.length * 10 });
            if (prop === 'createLinearGradient') return () => ({ addColorStop() {} });
            if (prop === 'fillText') {
              return (text: string, _x: number, y: number) => {
                texts.push({ text, font, y });
              };
            }
            if (prop === 'drawImage') {
              return (_img: unknown, x: number, y: number, dw: number, dh: number) => {
                draws.push({ x, y, dw, dh });
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
      return { ctx: ctx as unknown as CanvasRenderingContext2D, texts, draws };
    }

    function geographyPage(overrides: Partial<ScreenPage> = {}): ScreenPage {
      return exercisePage({
        kind: 'geography',
        subject: 'Geografi',
        title: 'Sveriges landskap',
        body: [
          'Sverige ligger i Nordeuropa och gränsar till Norge och Finland.',
          'Vilka tre största städer ligger vid kusten eller sjöar?',
          'Peka ut Bergslagen på kartan och förklara varför järn fanns där.',
        ],
        svgAsset: '<svg xmlns="http://www.w3.org/2000/svg"><circle cx="5" cy="5" r="4"/></svg>',
        solution: 'Stockholm, Göteborg och Malmö. Bergslagen har järnmalm.',
        sources: ['SO-rummet'],
        ...overrides,
      });
    }

    it('draws body text with a prominent map on the 894x501 acceptance canvas', () => {
      const { ctx, texts, draws } = mockGeoContext();
      const fakeDrawable = { width: 400, height: 300 } as unknown as CanvasImageSource;
      const result: ScreenRenderResult = drawScreenPage(
        ctx,
        { w: 894, h: 501 },
        geographyPage(),
        { svgImage: fakeDrawable },
      );
      const drawn = texts.map((t) => t.text).join('\n');
      // Previously ALL body paragraphs were omitted on this canvas.
      expect(drawn).toContain('Nordeuropa');
      expect(drawn).toContain('Bergslagen');
      // The map is the hero now: far larger than the old 110px strip.
      expect(draws.length).toBeGreaterThan(0);
      const biggest = draws.reduce((a, b) => (b.dh > a.dh ? b : a), draws[0]!);
      expect(biggest.dh).toBeGreaterThan(130);
      expect(biggest.dw).toBeGreaterThan(200);
      expect(biggest.y).toBeGreaterThanOrEqual(0);
      expect(biggest.y + biggest.dh).toBeLessThanOrEqual(501);
      // Nothing is clipped outside the canvas.
      expect(texts.every((t) => t.y > 0 && t.y < 501)).toBe(true);
      // visibleText carries the drawn body, never the hidden solution.
      expect(result.visibleText).toContain('Nordeuropa');
      expect(result.visibleText).not.toContain('Malmö');
    });

    it('stacks a legible full-width map on a 390px phone canvas', () => {
      const { ctx, texts, draws } = mockGeoContext();
      const fakeDrawable = { width: 400, height: 300 } as unknown as CanvasImageSource;
      const result: ScreenRenderResult = drawScreenPage(
        ctx,
        { w: 390, h: 700 },
        geographyPage(),
        { svgImage: fakeDrawable, draftText: 'mitt svar' },
      );
      const drawn = texts.map((t) => t.text).join('\n');
      expect(drawn).toContain('Nordeuropa');
      expect(drawn).toContain('Bergslagen');
      expect(drawn).toContain('mitt svar');
      expect(draws.length).toBeGreaterThan(0);
      const biggest = draws.reduce((a, b) => (b.dh > a.dh ? b : a), draws[0]!);
      expect(biggest.dw).toBeGreaterThanOrEqual(300);
      expect(biggest.dh).toBeGreaterThanOrEqual(180);
      expect(texts.every((t) => t.y > 0 && t.y < 700)).toBe(true);
      expect(result.visibleText).toContain('mitt svar');
      expect(result.visibleText).not.toContain('Malmö');
    });

    it('keeps the solution private until reveal, then returns it in visibleText', () => {
      const hiddenCtx = mockGeoContext();
      const hidden: ScreenRenderResult = drawScreenPage(
        hiddenCtx.ctx,
        { w: 894, h: 501 },
        geographyPage({ revealed: false }),
        { svgImage: { width: 400, height: 300 } as unknown as CanvasImageSource },
      );
      expect(hiddenCtx.texts.map((t) => t.text).join('\n')).toContain('Facit är dolt');
      expect(hidden.visibleText).toContain('Facit är dolt');
      expect(hidden.visibleText).not.toContain('Malmö');

      const shownCtx = mockGeoContext();
      const shown: ScreenRenderResult = drawScreenPage(
        shownCtx.ctx,
        { w: 894, h: 501 },
        geographyPage({ revealed: true }),
        { svgImage: { width: 400, height: 300 } as unknown as CanvasImageSource },
      );
      const shownDrawn = shownCtx.texts.map((t) => t.text).join('\n');
      expect(shownDrawn).toContain('Malmö');
      expect(shownDrawn).not.toContain('Facit är dolt');
      expect(shown.visibleText).toContain('Malmö');
    });

    it('visibleText matches actual draw operations when long body text is clipped', () => {
      const { ctx, texts } = mockGeoContext();
      const filler =
        'Paragraf om landskapet med älvar sjöar berg och dalar ' +
        'fyller rad efter rad så att den lilla ytan tar slut';
      const longBody = [...Array.from({ length: 5 }, () => filler),
        `Sista paragrafen nämner det hemliga ordet SLUTORD-ZZZ flera gånger ` +
        'så att ett läckage skulle synas direkt i texten'];
      const result: ScreenRenderResult = drawScreenPage(
        ctx,
        { w: 390, h: 400 },
        geographyPage({ body: longBody }),
        { svgImage: { width: 400, height: 300 } as unknown as CanvasImageSource },
      );
      // Exactly what hit the pixels — no hidden tails.
      expect(result.visibleText).toBe(texts.map((t) => t.text).join('\n'));
      expect(result.visibleText).not.toContain('SLUTORD-ZZZ');
      // Honest truncation, and nothing drawn outside the canvas.
      expect(result.visibleText).toContain('…');
      expect(texts.every((t) => t.y > 0 && t.y < 400)).toBe(true);
    });

    it('renderScreenPage returns the drawn text, including the homework branch', () => {
      const { ctx } = mockGeoContext();
      const canvas = {
        clientWidth: 894,
        clientHeight: 501,
        width: 0,
        height: 0,
        getContext: () => ctx,
      } as unknown as HTMLCanvasElement;
      const exercise: ScreenRenderResult = renderScreenPage(canvas, exercisePage({ revealed: true }));
      expect(exercise.visibleText).toContain('Hur mycket är 7 + 5?');
      expect(exercise.visibleText).toContain('Svaret är 12');

      const hwCtx = mockGeoContext();
      const hwCanvas = {
        clientWidth: 1280,
        clientHeight: 800,
        width: 0,
        height: 0,
        getContext: () => hwCtx.ctx,
      } as unknown as HTMLCanvasElement;
      const homework: ScreenRenderResult = renderScreenPage(
        hwCanvas,
        exercisePage({ kind: 'homework', subject: 'Läxa', title: 'Min läxa', body: ['Räkna 7 + 5.'], solution: '' }),
      );
      expect(homework.visibleText).toContain('Min läxa');
      expect(homework.visibleText).not.toContain('Facit är dolt');
    });
  });

  it('renderScreenPage throws on a real canvas without 2d context', async () => {
    const { renderScreenPage } = await import('./renderer');
    const canvas = { clientWidth: 100, clientHeight: 100, width: 100, height: 100, getContext: () => null };
    expect(() =>
      renderScreenPage(canvas as unknown as HTMLCanvasElement, {
        id: 'p',
        revision: 'r',
        lessonId: 'l',
        kind: 'exercise',
        subject: 'Matte',
        title: 'T',
        body: [],
        asset: null,
        svgAsset: null,
        answerLabel: 'Ditt svar',
        solution: '',
        sources: [],
        revealed: false,
        createdAt: 1,
      }),
    ).toThrow('no-2d-context');
  });
});
