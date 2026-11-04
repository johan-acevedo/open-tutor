import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import Board from './components/Board';

afterEach(() => cleanup());

const noop = vi.fn();

describe('Board layout switch', () => {
  it('shows the arrival greeting with drop zone when empty', () => {
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
    expect(screen.getByText('Släpp en fil eller klistra in')).toBeTruthy();
  });

  it('renders the first board item and leaves arrival behind', () => {
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
    expect(screen.queryAllByText('Släpp en fil eller klistra in').length).toBeGreaterThan(0);

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
    expect(screen.queryAllByText('Släpp en fil eller klistra in')).toHaveLength(0);
    expect(screen.getByText('Ekvationer')).toBeTruthy();
    expect(screen.getByText(/Vi löser/)).toBeTruthy();
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
