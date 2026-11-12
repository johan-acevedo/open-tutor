import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import Board from './components/Board';
import type { BoardItem } from './protocol';

afterEach(() => cleanup());

const noop = vi.fn();

const textOne: BoardItem = { id: 't1', kind: 'text', title: 'Ett', markdown: 'första' };
const pageTwo: BoardItem = { id: 'p2', kind: 'page', title: 'Klockan', body: '<h1>Klockan</h1>' };
const pageThree: BoardItem = { id: 'p3', kind: 'page', title: 'Bråk', body: '<h1>Bråk</h1>' };

function renderBook(items: BoardItem[], activeItemId?: string | null) {
  return render(
    <Board
      learnerName="Leo"
      items={items}
      focused={null}
      onItemMounted={noop}
      onResourceClosed={noop}
      activeItemId={activeItemId}
    />,
  );
}

describe('Board book', () => {
  it('shows one leaf at a time with a position', () => {
    const { container } = renderBook([textOne, pageTwo]);
    // Latest item is current: the page shows, the text leaf hides.
    expect(screen.getByText('2 / 2')).toBeTruthy();
    expect(container.querySelector('[data-board-id="p2"]')).toBeTruthy();
    expect(container.querySelector('[data-board-id="t1"]')?.closest('[hidden]')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Tillbaka/ }));
    expect(screen.getByText('1 / 2')).toBeTruthy();
    expect(container.querySelector('[data-board-id="t1"]')?.closest('[hidden]')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Framåt/ }));
    expect(screen.getByText('2 / 2')).toBeTruthy();
  });

  it('turns to a newly shown item and keeps earlier frames mounted', () => {
    const { container, rerender } = renderBook([pageTwo], 'p2');
    expect(container.querySelectorAll('iframe.ot-page-frame')).toHaveLength(1);
    rerender(
      <Board
        learnerName="Leo"
        items={[pageTwo, pageThree]}
        focused={null}
        onItemMounted={noop}
        onResourceClosed={noop}
        activeItemId="p3"
      />,
    );
    expect(screen.getByText('2 / 2')).toBeTruthy();
    // Both frames stay in the DOM; the earlier one hides instead of unmounting.
    const frames = container.querySelectorAll('iframe.ot-page-frame');
    expect(frames).toHaveLength(2);
    expect(frames[0].closest('[hidden]')).toBeTruthy();
    expect(frames[1].closest('[hidden]')).toBeNull();
  });

  it('hides the pager for a single leaf', () => {
    renderBook([textOne]);
    expect(screen.queryByText(/\/ 1/)).toBeNull();
    expect(screen.queryByRole('button', { name: /Tillbaka/ })).toBeNull();
  });

  it('still greets by name while empty', () => {
    renderBook([]);
    expect(screen.getByRole('heading', { name: 'Hej Leo!' })).toBeTruthy();
  });
});
