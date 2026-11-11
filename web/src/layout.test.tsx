import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { BoardItem } from './protocol';
import Board from './components/Board';

afterEach(() => cleanup());

const noop = vi.fn();

describe('Board layout switch', () => {
  it('shows the greeting, an empty whiteboard and an empty inbox strip', () => {
    render(
      <Board
        learnerName="Leo"
        lastTopic="ekvationer"
        items={[]}
        focused={null}
        onItemMounted={noop}
        onResourceClosed={noop}
        dragOver={false}
      />,
    );
    expect(screen.getByText('Hej Leo!')).toBeTruthy();
    expect(screen.getByText('Vad har du med dig idag?')).toBeTruthy();
    expect(screen.getByText(/Förra gången: ekvationer/)).toBeTruthy();
    expect(screen.getByText('Inkorg · tom')).toBeTruthy();
    expect(screen.getByText('släpp fil här')).toBeTruthy();
    expect(screen.getByText('Här hamnar det vi jobbar med.')).toBeTruthy();
    expect(screen.queryByText('Släpp en fil eller klistra in')).toBeNull();
  });

  it('reflects real homework state in the inbox strip', () => {
    const { rerender } = render(
      <Board
        learnerName="Leo"
        lastTopic={null}
        items={[]}
        focused={null}
        onItemMounted={noop}
        onResourceClosed={noop}
        dragOver={false}
      />,
    );
    expect(screen.getByText('Inkorg · tom')).toBeTruthy();

    rerender(
      <Board
        learnerName="Leo"
        lastTopic={null}
        items={[
          { id: 'h1', kind: 'homework', title: 'matte1.jpg', images: ['data:image/jpeg;base64,x'] },
          { id: 'h2', kind: 'homework', title: 'matte2.jpg', images: ['data:image/jpeg;base64,y'] },
        ]}
        focused={null}
        onItemMounted={noop}
        onResourceClosed={noop}
        dragOver={false}
      />,
    );
    expect(screen.getByText('Inkorg · 2 uppgifter')).toBeTruthy();
  });

  it('keeps the greeting and inbox visible once teaching starts', () => {
    const { rerender } = render(
      <Board
        learnerName="Leo"
        lastTopic={null}
        items={[]}
        focused={null}
        onItemMounted={noop}
        onResourceClosed={noop}
        dragOver={false}
      />,
    );
    expect(screen.getByText('Här hamnar det vi jobbar med.')).toBeTruthy();

    rerender(
      <Board
        learnerName="Leo"
        lastTopic={null}
        items={[{ id: 't1', kind: 'text', title: 'Ekvationer', markdown: 'Vi löser **3x = 15**.' }]}
        focused={null}
        onItemMounted={noop}
        onResourceClosed={noop}
        dragOver={false}
      />,
    );
    expect(screen.queryByText('Här hamnar det vi jobbar med.')).toBeNull();
    expect(screen.getByText('Ekvationer')).toBeTruthy();
    expect(screen.getByText(/Vi löser/)).toBeTruthy();
    // Greeting + inbox stay on top while teaching.
    expect(screen.getByText('Hej Leo!')).toBeTruthy();
    expect(screen.getByText('Inkorg · tom')).toBeTruthy();
  });

  it('renders homework as a paper card', () => {
    render(
      <Board
        learnerName="Elsa"
        lastTopic={null}
        items={[{ id: 'h1', kind: 'homework', title: 'matteprov.jpg', images: ['data:image/jpeg;base64,x'] }]}
        focused={null}
        onItemMounted={noop}
        onResourceClosed={noop}
        dragOver={false}
      />,
    );
    expect(screen.getByText('matteprov.jpg')).toBeTruthy();
  });
});

describe('Mobile board continuity', () => {
  const equation: BoardItem = { id: 'a', kind: 'steps', title: 'Equation', steps: [{ tex: '3x=15' }, { tex: 'x=5' }] };
  const other: BoardItem = { id: 'b', kind: 'text', title: 'Other task', markdown: 'A different task' };
  const defaults = { learnerName: 'Leo', lastTopic: null, onResourceClosed: noop, dragOver: false, mobile: true };

  it('keeps the selected older item in focus and reveals future steps only in the full board', () => {
    const { container } = render(
      <Board
        {...defaults}
        items={[equation, other]}
        focused={{ id: 'a', step: 0 }}
        activeItemId="a"
        onItemMounted={noop}
      />,
    );
    expect(container.querySelector('[data-board-id="b"]')?.parentElement?.hidden).toBe(true);
    expect(container.querySelector('[data-step="1"]')?.closest('[hidden]')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Hela tavlan/ }));
    expect(container.querySelector('[data-board-id="b"]')?.parentElement?.hidden).toBe(false);
    expect(container.querySelector('[data-step="1"]')?.closest('[hidden]')).toBeNull();
  });

  it('confirms a same-id update after mounting the changed content', async () => {
    const ack = vi.fn();
    const { rerender } = render(<Board {...defaults} items={[other]} focused={null} onItemMounted={ack} />);
    await waitFor(() => expect(ack).toHaveBeenCalledTimes(1));
    rerender(
      <Board {...defaults} items={[{ ...other, markdown: 'Updated task' }]} focused={null} onItemMounted={ack} />,
    );
    await waitFor(() => expect(ack).toHaveBeenCalledTimes(2));
    expect(screen.getByText('Updated task')).toBeTruthy();
  });

  it('keeps the resource player mounted while switching board views', () => {
    const resource: BoardItem = {
      id: 'r',
      kind: 'resource',
      title: 'Video',
      url: 'https://example.org',
      embedUrl: 'https://example.org/embed',
    };
    const { container } = render(
      <Board {...defaults} items={[resource, other]} focused={null} activeItemId="b" onItemMounted={noop} />,
    );
    const player = container.querySelector('iframe');
    fireEvent.click(screen.getByRole('button', { name: /Hela tavlan/ }));
    expect(container.querySelector('iframe')).toBe(player);
    fireEvent.click(screen.getByRole('button', { name: /Hela tavlan/ }));
    expect(container.querySelector('iframe')).toBe(player);
  });
});
