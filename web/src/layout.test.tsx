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
    expect(screen.queryByText('Ingen läxa skickad än')).toBeNull();
    expect(screen.queryByText('Du kan också dra in en bild eller pdf i fönstret.')).toBeNull();

    rerender(
      <Board
        learnerName="Leo"
        items={[{ id: 't1', kind: 'homework', title: 'Ekvationer', text: 'Vi löser 3x = 15.' }]}
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
  const menuProps = { dragOver: false, onCamera: noop, onFiles: noop };

  it('opens from the hamburger and shows a live empty inbox', () => {
    render(<TopMenu items={[]} {...menuProps} />);
    expect(screen.queryByText('Ingen läxa skickad än')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Meny' }));
    expect(screen.getByText('Ingen läxa skickad än')).toBeTruthy();
    expect(screen.getByText('Du kan också dra in en bild eller pdf i fönstret.')).toBeTruthy();
  });

  it('reflects real homework state in the menu', () => {
    const { rerender } = render(<TopMenu items={[]} {...menuProps} />);
    fireEvent.click(screen.getByRole('button', { name: 'Meny' }));
    expect(screen.getByText('Ingen läxa skickad än')).toBeTruthy();

    rerender(<TopMenu items={[homeworkOne, homeworkTwo]} {...menuProps} />);
    expect(screen.getByText('2 läxor skickade')).toBeTruthy();
  });

  it('wires the add buttons to the real handlers', () => {
    const onCamera = vi.fn();
    const onFiles = vi.fn();
    render(<TopMenu items={[]} dragOver={false} onCamera={onCamera} onFiles={onFiles} />);
    fireEvent.click(screen.getByRole('button', { name: 'Meny' }));

    fireEvent.click(screen.getByRole('button', { name: 'Fota läxan' }));
    expect(onCamera).toHaveBeenCalledTimes(1);
    // Picking an action closes the menu; reopen it for the next one.
    expect(screen.queryByRole('button', { name: 'Välj bild' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Meny' }));
    fireEvent.click(screen.getByRole('button', { name: 'Välj bild' }));
    expect(onFiles).toHaveBeenCalledTimes(1);
  });

  it('opens the about note from the menu', () => {
    render(<TopMenu items={[]} {...menuProps} />);
    fireEvent.click(screen.getByRole('button', { name: 'Meny' }));
    fireEvent.click(screen.getByRole('button', { name: 'Om Open Tutor' }));
    expect(screen.getByText('Gjord av Johan Acevedo.')).toBeTruthy();
  });
});

describe('Mobile board continuity', () => {
  const equation: BoardItem = { id: 'a', kind: 'homework', title: 'Equation', text: '3x=15' };
  const other: BoardItem = { id: 'b', kind: 'homework', title: 'Other task', text: 'A different task' };
  const defaults = { learnerName: 'Leo', onResourceClosed: noop };

  it('keeps the selected older item in focus as you turn the page', () => {
    const { container } = render(
      <Board
        {...defaults}
        items={[equation, other]}
        focused={{ id: 'a' }}
        activeItemId="a"
        onItemMounted={noop}
      />,
    );
    expect(container.querySelector('[data-board-id="b"]')?.parentElement?.hidden).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: /Framåt/ }));
    expect(container.querySelector('[data-board-id="b"]')?.parentElement?.hidden).toBe(false);
    expect(screen.getByText('2 / 2')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Tillbaka/ }));
    expect(container.querySelector('[data-board-id="a"]')?.parentElement?.hidden).toBe(false);
  });

  it('confirms a same-id update after mounting the changed content', async () => {
    const ack = vi.fn();
    const { rerender } = render(<Board {...defaults} items={[other]} focused={null} onItemMounted={ack} />);
    await waitFor(() => expect(ack).toHaveBeenCalledTimes(1));
    rerender(
      <Board {...defaults} items={[{ ...other, text: 'Updated task' }]} focused={null} onItemMounted={ack} />,
    );
    await waitFor(() => expect(ack).toHaveBeenCalledTimes(2));
    expect(screen.getByText('Updated task')).toBeTruthy();
  });

  it('keeps the resource player mounted while turning pages', () => {
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
    fireEvent.click(screen.getByRole('button', { name: /Tillbaka/ }));
    expect(container.querySelector('iframe')).toBe(player);
    fireEvent.click(screen.getByRole('button', { name: /Framåt/ }));
    expect(container.querySelector('iframe')).toBe(player);
  });
});
