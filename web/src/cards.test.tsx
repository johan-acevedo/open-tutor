import { describe, expect, it, vi } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import { afterEach } from 'vitest';
import BoardCard from './components/Cards';
import type { BoardItem } from './protocol';

afterEach(() => cleanup());

const noop = vi.fn();

function htmlItem(height?: number, width?: number): BoardItem {
  return {
    id: 'b1',
    kind: 'html',
    title: 'Linjen y=kx+m',
    html: '<!doctype html><html><head></head><body><h1>Linjär ekvation</h1></body></html>',
    ...(height === undefined ? {} : { height }),
    ...(width === undefined ? {} : { width }),
  };
}

describe('HtmlCard generated-board surface', () => {
  it('renders no outer headline, padding frame or card chrome', () => {
    const { container } = render(<BoardCard item={htmlItem(800)} onMounted={noop} />);
    const article = container.querySelector('article[data-board-id="b1"]');
    expect(article).toBeTruthy();
    expect(article?.classList.contains('ot-bcard-html')).toBe(true);
    expect(article?.querySelector('h2')).toBeNull();
  });

  it('keeps the title accessible on the article and the frame', () => {
    const { container } = render(<BoardCard item={htmlItem(800)} onMounted={noop} />);
    const article = container.querySelector('article[data-board-id="b1"]');
    expect(article?.getAttribute('aria-label')).toBe('Linjen y=kx+m');
    const frame = container.querySelector('iframe.ot-html-frame') as HTMLIFrameElement | null;
    expect(frame?.title).toBe('Linjen y=kx+m');
  });

  it('sizes the frame to the commissioned pane height', () => {
    const { container } = render(<BoardCard item={htmlItem(800)} onMounted={noop} />);
    const frame = container.querySelector('iframe.ot-html-frame') as HTMLIFrameElement | null;
    expect(frame?.style.height).toBe('800px');
  });

  it('keeps the commissioned design box for the fit wrapper', () => {
    const { container } = render(<BoardCard item={htmlItem(800, 1280)} onMounted={noop} />);
    const fit = container.querySelector('.ot-html-fit') as HTMLElement | null;
    expect(fit?.dataset.designW).toBe('1280');
    expect(fit?.dataset.designH).toBe('800');
    const frame = container.querySelector('iframe.ot-html-frame') as HTMLIFrameElement | null;
    expect(frame?.style.width).toBe('1280px');
    expect(frame?.style.height).toBe('800px');
  });

  it('scales the frame with transform so clicks still land after shrinking', () => {
    const { container } = render(<BoardCard item={htmlItem(800, 1280)} onMounted={noop} />);
    const frame = container.querySelector('iframe.ot-html-frame') as HTMLIFrameElement | null;
    expect(frame?.style.transformOrigin).toBe('top left');
    expect(frame?.style.transform).toMatch(/^scale\(/);
    // Legacy items without width keep fluid-width behaviour (height fit only).
    const { container: legacy } = render(<BoardCard item={htmlItem(800)} onMounted={noop} />);
    expect(legacy.querySelector('.ot-html-fit')).toBeNull();
    expect(legacy.querySelector('iframe.ot-html-frame')).toBeTruthy();
  });

  it('serves the board with the library CSP (CDN styles, fonts, images)', () => {
    const { container } = render(<BoardCard item={htmlItem(800)} onMounted={noop} />);
    const frame = container.querySelector('iframe.ot-html-frame') as HTMLIFrameElement | null;
    const srcDoc = frame?.srcdoc ?? '';
    expect(srcDoc).toContain("style-src 'unsafe-inline' https://cdn.jsdelivr.net");
    expect(srcDoc).toContain('font-src https://cdn.jsdelivr.net');
    expect(srcDoc).toContain('img-src data: https:');
    expect(frame?.getAttribute('sandbox')).toContain('allow-scripts');
  });

  it('shows a drawing status without an outer headline while pending', () => {
    const { container } = render(
      <BoardCard item={{ id: 'b1', kind: 'pending', title: 'Linjen y=kx+m', height: 800 }} onMounted={noop} />,
    );
    expect(container.querySelector('article h2')).toBeNull();
    expect(container.querySelector('article')?.getAttribute('aria-label')).toBe('Linjen y=kx+m');
    expect(container.querySelector('[role="status"]')?.textContent).toContain('Ritar');
  });

  it('keeps the document doctype before the security policy', () => {
    const { container } = render(<BoardCard item={htmlItem(800, 1280)} onMounted={noop} />);
    const frame = container.querySelector<HTMLIFrameElement>('iframe');
    expect(frame?.srcdoc.startsWith('<!doctype html>')).toBe(true);
    expect(frame?.srcdoc).toContain('<head><meta http-equiv="Content-Security-Policy"');
  });
});
