import { describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach } from 'vitest';
import Avatar from './components/Avatar';
import type { Pill } from './avatarState';

afterEach(() => cleanup());

const pill: Pill = { label: 'Ritar…', icon: 'pencil', tone: 'violet', animateBars: false };

describe('Avatar pose image fallback', () => {
  it('loads the working pose image while a board is drawing', () => {
    render(<Avatar pose="working" pill={pill} caption="" captionFading={false} />);
    const img = screen.getByAltText('Tutorn');
    expect(img.getAttribute('src')).toBe('/character/working.webp');
  });

  it('retries the new pose image instead of sticking on the fallback', () => {
    // working.webp ships separately; while it 404s the silhouette shows…
    const { rerender } = render(<Avatar pose="working" pill={pill} caption="" captionFading={false} />);
    fireEvent.error(screen.getByAltText('Tutorn'));
    expect(screen.getByRole('img', { name: 'Tutorn' })).toBeTruthy();
    expect(screen.queryByAltText('Tutorn')).toBeNull();
    // …but the next pose change tries its image again instead of sticking.
    rerender(<Avatar pose="speaking" pill={pill} caption="" captionFading={false} />);
    const img = screen.getByAltText('Tutorn');
    expect(img.getAttribute('src')).toBe('/character/speaking.webp');
  });
});
