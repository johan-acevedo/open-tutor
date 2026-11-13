import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { BoardItem } from './protocol';
import type { Pill } from './avatarState';
import PhoneStage from './components/PhoneStage';
import { usePhoneStage } from './phoneStage';

afterEach(() => cleanup());

const pill: Pill = { label: 'Pratar', icon: 'bars', tone: 'cyan', animateBars: true };
const task: BoardItem = { id: 't1', kind: 'text', title: 'Ekvationer', markdown: 'Vi löser 3x = 15.' };
const other: BoardItem = { id: 't2', kind: 'text', title: 'Ekvationer 2', markdown: '3x = 15' };

type HarnessProps = {
  items: BoardItem[];
  signal: number;
  caption: string;
  captionFading?: boolean;
};

/** PhoneStage with the real two-view state machine in front of it. */
function Harness({ items, signal, caption, captionFading = false }: HarnessProps) {
  const stage = usePhoneStage({ hasItem: items.length > 0, itemSignal: signal });
  return (
    <div className="ot-phone ot-phone-portrait">
      <PhoneStage
        learnerName="Leo"
        items={items}
        focused={null}
        mode={items.length > 0 ? 'teaching' : 'arrival'}
        stage={stage}
        pose="speaking"
        pill={pill}
        caption={caption}
        captionFading={captionFading}
        activeItemId={items[0]?.id ?? null}
        onItemMounted={() => {}}
        onResourceClosed={() => {}}
      />
    </div>
  );
}

const view = (container: HTMLElement) => container.querySelector('[data-phone-view]')?.getAttribute('data-phone-view');

describe('Phone portrait: the fox fills the screen until something is shown', () => {
  it('shows the big fox with the line in a bubble, not the empty-board card', () => {
    const { container } = render(<Harness items={[]} signal={0} caption="Hej Johan! Vad jobbar du med idag?" />);

    expect(view(container)).toBe('fox');
    // The caption is a bubble by the fox's head and stays a live region.
    const bubble = container.querySelector('.ot-fox-bubble-hero');
    expect(bubble?.getAttribute('aria-live')).toBe('polite');
    expect(bubble?.textContent).toBe('Hej Johan! Vad jobbar du med idag?');
    expect(container.querySelector('.ot-fox-hero img.ot-avatar-img')?.getAttribute('src')).toBe(
      '/character/speaking.webp',
    );
    // The state pill stays visible near the fox.
    expect(screen.getByRole('status', { name: 'Pratar' })).toBeTruthy();
    // The placeholder card ("Hej Leo! Här hamnar det vi jobbar med.") is not on the phone.
    expect(screen.queryByText('Hej Leo!')).toBeNull();
    expect(screen.queryByText('Här hamnar det vi jobbar med.')).toBeNull();
    // Nothing to go back to, so no page chip and no strip.
    expect(screen.queryByRole('button', { name: 'Visa sidan' })).toBeNull();
    expect(container.querySelector('.ot-fox-head')).toBeNull();
  });

  it('gives a shown item the height and moves the fox into the strip', () => {
    const { container } = render(
      <Harness items={[task]} signal={1} caption="Nu tar vi bort fem på båda sidor, precis som vi gjorde nyss." />,
    );

    expect(view(container)).toBe('item');
    expect(container.querySelector('.ot-fox-hero')).toBeNull();
    expect(screen.getByText('Ekvationer')).toBeTruthy();
    // The board is visible, not hidden behind the fox.
    expect(container.querySelector('.ot-board')?.getAttribute('aria-hidden')).toBeNull();
    // Round fox head on the left, latest line in a bubble to its right.
    const head = screen.getByRole('button', { name: 'Visa Räven' });
    expect(head.className).toContain('ot-fox-head-cyan');
    const bubble = container.querySelector('.ot-fox-bubble-strip');
    expect(bubble?.getAttribute('aria-live')).toBe('polite');
    expect(bubble?.textContent).toContain('Nu tar vi bort fem på båda sidor');
    // The state is still available to screen readers without a visible pill.
    expect(screen.getByRole('status', { name: 'Pratar' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Visa sidan' })).toBeNull();
  });

  it('tapping the fox head goes back to the fox and keeps the item mounted', () => {
    const { container } = render(<Harness items={[task]} signal={1} caption="Skriv svaret i rutan." />);

    fireEvent.click(screen.getByRole('button', { name: 'Visa Räven' }));

    expect(view(container)).toBe('fox');
    expect(container.querySelector('.ot-board')?.getAttribute('aria-hidden')).toBe('true');
    // Hidden, not removed: the child's page and its answers survive.
    expect(container.querySelector('[data-board-id="t1"]')).toBeTruthy();
    expect(container.querySelector('.ot-fox-bubble-hero')?.textContent).toBe('Skriv svaret i rutan.');

    fireEvent.click(screen.getByRole('button', { name: 'Visa sidan' }));

    expect(view(container)).toBe('item');
    expect(container.querySelector('.ot-board')?.getAttribute('aria-hidden')).toBeNull();
  });

  it('turns back to the item when the tutor shows or patches one', () => {
    const { container, rerender } = render(<Harness items={[task]} signal={1} caption="Titta här." />);

    fireEvent.click(screen.getByRole('button', { name: 'Visa Räven' }));
    expect(view(container)).toBe('fox');

    // board.show / board.focus / board.patch bump the signal.
    rerender(<Harness items={[task]} signal={2} caption="Titta här." />);
    expect(view(container)).toBe('item');
  });

  it('stays on the item when the child turns the page', () => {
    const { container } = render(<Harness items={[task, other]} signal={1} caption="Bläddra." />);

    expect(screen.getByText('1 / 2')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Framåt/ }));

    expect(view(container)).toBe('item');
    expect(screen.getByText('2 / 2')).toBeTruthy();
    expect(container.querySelector('[data-board-id="t2"]')?.closest('[hidden]')).toBeNull();
  });
});
