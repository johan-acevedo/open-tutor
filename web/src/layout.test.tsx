import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { BoardItem } from './protocol';
import Board from './components/Board';
import TopMenu from './components/TopMenu';

afterEach(() => cleanup());

const noop = vi.fn();

const homeworkOne: BoardItem = {
  id: 'h1',
  kind: 'homework',
  title: 'matte1.jpg',
  images: ['data:image/jpeg;base64,x'],
};
const homeworkTwo: BoardItem = {
  id: 'h2',
  kind: 'homework',
  title: 'matte2.jpg',
  images: ['data:image/jpeg;base64,y'],
};

describe('Board greeting lives in the empty state', () => {
  it('greets by name only while the board is empty', () => {
    const { rerender } = render(
      <Board learnerName="Leo" items={[]} focused={null} onItemMounted={noop} onResourceClosed={noop} />,
    );
    expect(screen.getByRole('heading', { name: 'Hej Leo!' })).toBeTruthy();
    expect(screen.getByText('Här hamnar det vi jobbar med.')).toBeTruthy();
    // No permanent surface: no greeting header or inbox strip outside the empty state.
    expect(screen.queryByText('Inkorg · tom')).toBeNull();
    expect(screen.queryByText('släpp fil här')).toBeNull();

    rerender(
      <Board
        learnerName="Leo"
        items={[{ id: 't1', kind: 'text', title: 'Ekvationer', markdown: 'Vi löser **3x = 15**.' }]}
        focused={null}
        onItemMounted={noop}
        onResourceClosed={noop}
      />,
    );
    expect(screen.queryByText('Här hamnar det vi jobbar med.')).toBeNull();
    expect(screen.queryByText('Hej Leo!')).toBeNull();
    expect(screen.getByText('Ekvationer')).toBeTruthy();
    expect(screen.getByText(/Vi löser/)).toBeTruthy();
  });

  it('renders homework as a paper card', () => {
    render(
      <Board
        learnerName="Elsa"
        items={[{ id: 'h1', kind: 'homework', title: 'matteprov.jpg', images: ['data:image/jpeg;base64,x'] }]}
        focused={null}
        onItemMounted={noop}
        onResourceClosed={noop}
      />,
    );
    expect(screen.getByText('matteprov.jpg')).toBeTruthy();
  });
});

describe('Header menu inbox', () => {
  const menuProps = { dragOver: false, runtime: null, onCamera: noop, onFiles: noop };

  it('opens from the hamburger and shows a live empty inbox', () => {
    render(<TopMenu items={[]} {...menuProps} />);
    expect(screen.queryByText('Inkorg · tom')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Meny' }));
    expect(screen.getByText('Inkorg · tom')).toBeTruthy();
    expect(screen.getByText('släpp fil här')).toBeTruthy();
  });

  it('reflects real homework state in the menu', () => {
    const { rerender } = render(<TopMenu items={[]} {...menuProps} />);
    fireEvent.click(screen.getByRole('button', { name: 'Meny' }));
    expect(screen.getByText('Inkorg · tom')).toBeTruthy();

    rerender(<TopMenu items={[homeworkOne, homeworkTwo]} {...menuProps} />);
    expect(screen.getByText('Inkorg · 2 uppgifter')).toBeTruthy();
  });

  it('wires the add buttons to the real handlers', () => {
    const onCamera = vi.fn();
    const onFiles = vi.fn();
    render(<TopMenu items={[]} dragOver={false} runtime={null} onCamera={onCamera} onFiles={onFiles} />);
    fireEvent.click(screen.getByRole('button', { name: 'Meny' }));

    fireEvent.click(screen.getByRole('button', { name: 'Fota läxan' }));
    expect(onCamera).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Välj bild' }));
    expect(onFiles).toHaveBeenCalledTimes(1);
  });

  it('opens the about note from the menu', () => {
    render(<TopMenu items={[]} {...menuProps} />);
    fireEvent.click(screen.getByRole('button', { name: 'Meny' }));
    fireEvent.click(screen.getByRole('button', { name: 'Om Open Tutor' }));
    expect(screen.getByText('by Johan Acevedo')).toBeTruthy();
  });
});

describe('Mobile board continuity', () => {
  const equation: BoardItem = { id: 'a', kind: 'steps', title: 'Equation', steps: [{ tex: '3x=15' }, { tex: 'x=5' }] };
  const other: BoardItem = { id: 'b', kind: 'text', title: 'Other task', markdown: 'A different task' };
  const defaults = { learnerName: 'Leo', onResourceClosed: noop, mobile: true };

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
