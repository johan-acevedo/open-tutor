import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useEffect } from 'react';
import Board from './components/Board';
import { setDiagramImporter } from './diagramLoader';
import type { DiagramCanvasProps } from './diagramLoader';
import type { BoardItem, DiagramItem } from './protocol';
import { upsertItem } from './useSession';
import fontsSource from './diagramFonts.ts?raw';
import canvasSource from './DiagramCanvas.tsx?raw';
import assetsSource from './excalidrawAssets.ts?raw';
import noticeText from '../public/excalidraw/NOTICE.md?raw';
import packageJson from '../package.json?raw';

const served = Object.keys(import.meta.glob('../public/excalidraw/fonts/**/*.woff2'));

const diagram = (patch: Partial<DiagramItem> = {}): DiagramItem => ({
  id: 'b1',
  kind: 'diagram',
  title: 'Vattnets kretslopp',
  rev: 1,
  layout: 'radial',
  nodes: [
    { id: 'k', text: 'Vattnets kretslopp', role: 'center', x: 0, y: 0 },
    { id: 'm', text: 'Moln', role: 'idea', x: 400, y: 0 },
  ],
  links: [{ id: 'l1', source: 'k', target: 'm', label: 'blir' }],
  focus: [],
  ...patch,
});

/** A canvas that reports the revision it was given, the way the real one does after drawing. */
function FakeCanvas({ item, onRendered, interactive }: DiagramCanvasProps) {
  useEffect(() => onRendered(item.rev), [item, onRendered]);
  return <div data-testid="canvas" data-interactive={String(interactive)} data-rev={item.rev} />;
}

function board(items: BoardItem[], onDiagramRendered = vi.fn()) {
  const ui = (list: BoardItem[]) => (
    <Board
      learnerName="Leo"
      lastTopic={null}
      items={list}
      focused={null}
      onItemMounted={vi.fn()}
      onResourceClosed={vi.fn()}
      onDiagramRendered={onDiagramRendered}
      dragOver={false}
    />
  );
  const view = render(ui(items));
  return { onDiagramRendered, rerender: (list: BoardItem[]) => view.rerender(ui(list)) };
}

beforeEach(() => setDiagramImporter(null));
afterEach(() => {
  cleanup();
  setDiagramImporter(null);
});

describe('diagram card', () => {
  it('fetches the drawing library only when a diagram is on the board, then reports what was drawn', async () => {
    const importer = vi.fn(async () => ({ default: FakeCanvas }));
    setDiagramImporter(importer);
    const { onDiagramRendered, rerender } = board([{ id: 't', kind: 'text', markdown: 'Hej' }]);
    expect(importer).not.toHaveBeenCalled();
    rerender([{ id: 't', kind: 'text', markdown: 'Hej' }, diagram()]);
    expect(screen.getByRole('status').textContent).toBe('Ritar…'); // visible while the chunk loads
    await waitFor(() => expect(screen.getByTestId('canvas')).toBeTruthy());
    expect(importer).toHaveBeenCalledTimes(1);
    expect(onDiagramRendered).toHaveBeenCalledWith('b1', 1, undefined);
    rerender([diagram({ rev: 2 })]);
    await waitFor(() => expect(onDiagramRendered).toHaveBeenCalledWith('b1', 2, undefined));
    expect(importer).toHaveBeenCalledTimes(1);
  });

  it('shows a readable text version that names every connection', async () => {
    setDiagramImporter(async () => ({ default: FakeCanvas }));
    board([diagram({ focus: ['m'] })]);
    await waitFor(() => screen.getByTestId('canvas'));
    const stage = screen.getByRole('img');
    expect(stage.getAttribute('aria-label')).toBe('Tankekarta om Vattnets kretslopp: 2 rutor och 1 pil.');
    const text = document.getElementById(stage.getAttribute('aria-describedby')!)!;
    expect(text.textContent).toContain('Vattnets kretslopp → Moln (blir)');
    expect(text.textContent).toContain('Markerat just nu: Moln');
    expect(screen.getByText('Visa som text')).toBeTruthy();
  });

  it('a library that cannot load fails visibly, answers every revision at once, keeps the text and other cards', async () => {
    const importer = vi.fn().mockRejectedValue(new Error('chunk 404'));
    setDiagramImporter(importer);
    const steps: BoardItem = { id: 's', kind: 'steps', title: 'Ekvation', steps: [{ tex: '3x = 15' }] };
    const { onDiagramRendered, rerender } = board([steps, diagram()]);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Diagrammet kunde inte visas');
    expect(onDiagramRendered).toHaveBeenCalledWith('b1', 1, 'Ritprogrammet kunde inte laddas.');
    // The next revision is answered with the failure too, not left to time out.
    rerender([steps, diagram({ rev: 2 })]);
    await waitFor(() => expect(onDiagramRendered).toHaveBeenCalledWith('b1', 2, 'Ritprogrammet kunde inte laddas.'));
    // The text version is open, and the equation card is untouched.
    expect(document.querySelector('details.ot-diagram-text')?.hasAttribute('open')).toBe(true);
    expect(document.querySelector('[data-board-id="s"] .katex')).not.toBeNull();
    expect(screen.queryByTestId('canvas')).toBeNull();
  });

  it('retry loads the library again (a failed load is not cached)', async () => {
    const importer = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ default: FakeCanvas });
    setDiagramImporter(importer);
    const { onDiagramRendered } = board([diagram()]);
    fireEvent.click(await screen.findByRole('button', { name: 'Försök igen' }));
    await waitFor(() => screen.getByTestId('canvas'));
    expect(importer).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(onDiagramRendered).toHaveBeenLastCalledWith('b1', 1, undefined);
  });

  it('a drawing error from the canvas is shown and passed on', async () => {
    function Broken({ item, onRendered }: DiagramCanvasProps) {
      useEffect(() => onRendered(item.rev, 'Typsnittet för diagrammet kunde inte laddas.'), [item, onRendered]);
      return null;
    }
    setDiagramImporter(async () => ({ default: Broken }));
    const { onDiagramRendered } = board([diagram()]);
    expect((await screen.findByRole('alert')).textContent).toContain('Diagrammet kunde inte visas');
    expect(onDiagramRendered).toHaveBeenCalledWith('b1', 1, 'Typsnittet för diagrammet kunde inte laddas.');
    expect(document.querySelector('.ot-diagram-stage-off')).not.toBeNull(); // no empty box
  });

  it('the page scrolls through the diagram until the child unlocks zoom and pan', async () => {
    setDiagramImporter(async () => ({ default: FakeCanvas }));
    board([diagram()]);
    await waitFor(() => screen.getByTestId('canvas'));
    expect(screen.getByTestId('canvas').getAttribute('data-interactive')).toBe('false');
    const toggle = screen.getByRole('button', { name: 'Zooma och flytta' });
    expect(toggle.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(toggle);
    expect(screen.getByTestId('canvas').getAttribute('data-interactive')).toBe('true');
    expect(screen.getByRole('button', { name: 'Lås diagrammet' }).getAttribute('aria-pressed')).toBe('true');
  });
});

describe('upsertItem', () => {
  it('replaces an item with the same id and appends a new one', () => {
    const a: BoardItem = { id: 'a', kind: 'text', markdown: '1' };
    expect(upsertItem([a], { id: 'a', kind: 'text', markdown: '2' })).toEqual([{ id: 'a', kind: 'text', markdown: '2' }]);
    expect(upsertItem([a], { id: 'b', kind: 'text', markdown: '3' })).toHaveLength(2);
  });
  it('never lets an older diagram revision replace a newer one', () => {
    const newer = diagram({ rev: 5 });
    const items = [newer];
    expect(upsertItem(items, diagram({ rev: 4 }))).toBe(items);
    expect(upsertItem(items, diagram({ rev: 6 }))[0]).toMatchObject({ rev: 6 });
    expect(upsertItem(items, diagram({ rev: 5 }))[0]).toMatchObject({ rev: 5 });
  });
});

describe('self-hosted assets', () => {
  it('ships the diagram font files and the licence notice, and pins the library exactly', () => {
    const files = [...fontsSource.matchAll(/file: '([^']+\.woff2)'/g)].map((m) => m[1]);
    expect(files).toHaveLength(2);
    for (const file of files) expect(served).toContain(`../public/excalidraw/fonts/Nunito/${file}`);
    expect(served.some((f) => f.includes('/Excalifont/'))).toBe(true);
    expect(noticeText).toContain('SIL OPEN FONT LICENSE Version 1.1');
    expect(noticeText).toContain('Nunito');
    expect(JSON.parse(packageJson).dependencies['@excalidraw/excalidraw']).toBe('0.18.1');
  });
  it('points the library at our own server for fonts, before the library is imported', () => {
    expect(canvasSource.indexOf("import './excalidrawAssets'")).toBeLessThan(canvasSource.indexOf("from '@excalidraw/excalidraw'"));
    expect(assetsSource).toContain("new URL('excalidraw/', document.baseURI)");
  });
});
