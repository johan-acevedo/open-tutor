import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import CallStage from './components/CallStage';
import { readBoardSize } from './useSession';
import type { Pill } from './avatarState';
import type { BoardItem } from './protocol';

afterEach(() => cleanup());

const pill: Pill = { label: 'Pratar', icon: 'bars', tone: 'cyan', animateBars: true };
const task: BoardItem = { id: 't1', kind: 'homework', title: 'Ekvationer', text: 'Vi löser 3x = 15.' };

function arrivalProps(extra: Record<string, unknown> = {}) {
  return {
    learnerName: 'Leo',
    items: [],
    focused: null,
    mode: 'arrival' as const,
    pose: 'greeting' as const,
    pill,
    caption: 'Hej Leo! Vad jobbar du med idag?',
    captionFading: false,
    activeItemId: null,
    onItemMounted: () => {},
    onResourceClosed: () => {},
    ...extra,
  };
}

describe('Call stage arrival: no empty board, companion owns the stage', () => {
  it('shows the companion large and centred with the caption in a speech bubble', () => {
    const { container } = render(<CallStage {...arrivalProps()} />);

    expect(container.querySelector('.ot-main-arrival')).toBeTruthy();
    // One bubble near the head: the state as a small line on top (a live
    // region, as before), the caption under it (a live region, as before).
    // (The right column mounts the same bubble unseen, so the switch is a
    // fade; visibility:hidden keeps it out of the accessibility tree.)
    const says = container.querySelectorAll('.ot-stage-hero .ot-say');
    expect(says).toHaveLength(1);
    expect(screen.getAllByRole('status', { name: 'Pratar' })).toHaveLength(2);
    const hero = within(container.querySelector('.ot-stage-hero') as HTMLElement);
    expect(hero.getByRole('status', { name: 'Pratar' })).toBeTruthy();
    const text = container.querySelector('.ot-stage-hero .ot-say-text');
    expect(text?.getAttribute('aria-live')).toBe('polite');
    expect(text?.textContent).toBe('Hej Leo! Vad jobbar du med idag?');
    // The figure is there, large (sized by the stage, not a thumbnail strip).
    const img = container.querySelector('.ot-stage-hero .ot-avatar-img');
    expect(img?.getAttribute('src')).toBe('/character/greeting.webp?v=20261119');
  });

  it('shows no empty-board copy on desktop arrival, but keeps the homework tray usable', () => {
    const { container } = render(<CallStage {...arrivalProps()} />);

    expect(screen.queryByText('Här hamnar det vi jobbar med.')).toBeNull();
    expect(container.querySelector('.ot-board-empty')).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Hej Leo!' })).toBeNull();
  });

  it('keeps the board laid out at teaching size while unseen', () => {
    const { container } = render(<CallStage {...arrivalProps()} />);

    // The scroll surface the server commissions pages for is mounted in
    // arrival too …
    const scroll = container.querySelector('.ot-main-arrival .ot-board .ot-board-scroll');
    expect(scroll).toBeTruthy();
    // … and hidden only by stylesheet (visibility), never removed from layout:
    // no hidden attribute, no display:none that would collapse its size.
    const section = container.querySelector('.ot-main-arrival .ot-board');
    expect(section?.hasAttribute('hidden')).toBe(false);
    expect((section as HTMLElement)?.style?.display).not.toBe('none');
    expect((scroll as HTMLElement)?.style?.display).not.toBe('none');
  });

  it('shows only the state, compact, when there is no caption yet', () => {
    const { container } = render(<CallStage {...arrivalProps({ caption: '' })} />);

    const hero = within(container.querySelector('.ot-stage-hero') as HTMLElement);
    expect(hero.getByRole('status', { name: 'Pratar' })).toBeTruthy();
    // Compact: the bubble carries the empty marker …
    const say = container.querySelector('.ot-stage-hero .ot-say');
    expect(say?.className).toContain('ot-say-empty');
    const text = container.querySelector('.ot-stage-hero .ot-say-text');
    // …but the live region stays mounted (empty, and never hidden from
    // assistive tech) so the first words are announced.
    expect(text?.getAttribute('aria-live')).toBe('polite');
    expect(text?.textContent).toBe('');
    expect(text?.className).toContain('ot-text-empty');
    expect(text?.hasAttribute('hidden')).toBe(false);
  });

  it('marks a captioned bubble as non-empty', () => {
    const { container } = render(<CallStage {...arrivalProps()} />);

    expect(container.querySelector('.ot-stage-hero .ot-say')?.className).not.toContain('ot-say-empty');
    expect(container.querySelector('.ot-stage-hero .ot-say-text')?.className).not.toContain('ot-text-empty');
  });

  it('shrinks back to the state line once the caption has faded', () => {
    const { container } = render(<CallStage {...arrivalProps({ captionFading: true })} />);

    expect(container.querySelector('.ot-stage-hero .ot-say')?.className).toContain('ot-say-empty');
    const text = container.querySelector('.ot-stage-hero .ot-say-text');
    expect(text?.className).toContain('ot-text-empty');
    expect(text?.textContent).not.toBe('');
  });

  it('opts the hidden arrival board back into visibility while it carries the tray', () => {
    const { container, rerender } = render(<CallStage {...arrivalProps()} />);
    expect(container.querySelector('.ot-main-arrival .ot-board')?.className).not.toContain(
      'ot-board-has-tray',
    );

    rerender(<CallStage {...arrivalProps({ overlay: <div className="ot-homework-tray" /> })} />);
    expect(container.querySelector('.ot-main-arrival .ot-board')?.className).toContain(
      'ot-board-has-tray',
    );
  });
});

describe('Call stage teaching: board left, companion stays large right', () => {
  it('slides the board in and keeps the bubble with the companion', () => {
    const { container } = render(
      <CallStage
        {...arrivalProps({ mode: 'teaching', items: [task], pose: 'pointing' as const })}
      />,
    );

    expect(container.querySelector('.ot-main-teaching')).toBeTruthy();
    expect(screen.getByText('Ekvationer')).toBeTruthy();
    // The right column keeps its own bubble (state + caption live regions).
    const colSay = container.querySelector('.ot-avatar-col .ot-say');
    expect(colSay).toBeTruthy();
    expect(colSay?.querySelector('.ot-say-text')?.textContent).toBe('Hej Leo! Vad jobbar du med idag?');
    const img = container.querySelector('.ot-avatar-col .ot-avatar-img');
    expect(img?.getAttribute('src')).toBe('/character/pointing.webp?v=20261119');
  });
});

describe('Board size guarantee: the server hears the teaching size', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('measures the laid-out scroll surface, not the window', () => {
    document.body.innerHTML = '<div class="ot-board-scroll"></div>';
    const el = document.querySelector('.ot-board-scroll') as HTMLElement;
    // jsdom has no layout: stand in for the teaching-size box.
    Object.defineProperty(el, 'clientWidth', { value: 914, configurable: true });
    Object.defineProperty(el, 'clientHeight', { value: 708, configurable: true });

    expect(readBoardSize()).toMatchObject({ w: 914, h: 708, device: 'desktop' });
  });

  it('falls back to the window only when no board surface is mounted', () => {
    document.body.innerHTML = '';
    const size = readBoardSize();
    expect(size.w).toBeGreaterThanOrEqual(320);
    expect(size.h).toBeGreaterThanOrEqual(1);
  });
});
