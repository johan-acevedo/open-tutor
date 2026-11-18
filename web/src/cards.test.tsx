import { describe, expect, it, vi } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import { afterEach } from 'vitest';
import BoardCard from './components/Cards';
import type { BoardItem } from './protocol';

afterEach(() => cleanup());

const noop = vi.fn();

describe('BoardCard surfaces', () => {
  it('renders homework as a paper card with its title and text', () => {
    const item: BoardItem = { id: 'h1', kind: 'homework', title: 'matte.jpg', text: 'Uppgift 3' };
    const { container } = render(<BoardCard item={item} onMounted={noop} />);
    expect(container.querySelector('h3')?.textContent).toBe('matte.jpg');
    expect(container.querySelector('.ot-paper p')?.textContent).toBe('Uppgift 3');
  });

  it('renders an image card with its alt text', () => {
    const item: BoardItem = { id: 'i1', kind: 'image', url: 'https://x/y.png', alt: 'En bild' };
    const { container } = render(<BoardCard item={item} onMounted={noop} />);
    expect(container.querySelector('img')?.getAttribute('alt')).toBe('En bild');
  });

  it('renders a resource card with its player and the Klar button', () => {
    const item: BoardItem = {
      id: 'r1',
      kind: 'resource',
      title: 'Film',
      url: 'https://example.org/v',
      embedUrl: 'https://example.org/embed',
    };
    const closed = vi.fn();
    const { container } = render(
      <BoardCard item={item} onMounted={noop} onResourceClosed={closed} />,
    );
    expect(container.querySelector('iframe.ot-resource-frame')).toBeTruthy();
    container.querySelector<HTMLButtonElement>('.ot-klar-btn')?.click();
    expect(closed).toHaveBeenCalledWith('r1');
  });

  it('shows a drawing status without an outer headline while pending', () => {
    const { container } = render(
      <BoardCard item={{ id: 'b1', kind: 'pending', title: 'Linjen y=kx+m', height: 800 }} onMounted={noop} />,
    );
    expect(container.querySelector('article h2')).toBeNull();
    expect(container.querySelector('article')?.getAttribute('aria-label')).toBe('Linjen y=kx+m');
    expect(container.querySelector('[role="status"]')?.textContent).toContain('Ritar');
  });

  it('leaves pages to PageCard', () => {
    const item: BoardItem = { id: 'p1', kind: 'page', title: 'Klockan', body: '<h1>x</h1>' };
    const { container } = render(<BoardCard item={item} onMounted={noop} />);
    expect(container.innerHTML).toBe('');
  });
});
