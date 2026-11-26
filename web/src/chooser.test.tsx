import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import HomeChooser from './components/HomeChooser';
import HouseholdPicker from './components/HouseholdPicker';
import PrivacyPage from './components/PrivacyPage';
import EndCard from './components/EndCard';
import type { Profile } from './db';

afterEach(cleanup);

function profile(over: Partial<Profile> = {}): Profile {
  return { id: 'p1', name: 'Alva', grade: 4, band: 'primary', notes: [], createdAt: 0, ...over };
}

describe('HomeChooser', () => {
  it('shows three equal-weight companion cards with one-tap start each', () => {
    const onBegin = vi.fn();
    render(<HomeChooser onBegin={onBegin} starting={false} />);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Läxhjälp du kan prata med.');
    for (const cta of ['Prata med Räven', 'Prata med Lodjuret', 'Prata med Björnen']) {
      expect(screen.getByRole('button', { name: cta })).toBeDefined();
    }
    expect(screen.getByText('Åk 1–6')).toBeDefined();
    expect(screen.getByText('Högstadiet')).toBeDefined();
    expect(screen.getByText('Gymnasiet och vuxna')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Prata med Lodjuret' }));
    expect(onBegin).toHaveBeenCalledWith('middle');
  });

  it('plays the hello clip when a face is tapped', () => {
    const onBegin = vi.fn();
    render(<HomeChooser onBegin={onBegin} starting={false} />);
    const face = screen.getByRole('button', { name: /Lyssna på Björnen$/ });
    expect(face.querySelector('img')?.getAttribute('src')).toContain('face.webp');
  });
});

describe('HouseholdPicker', () => {
  it('lists remembered learners with their companion and a new entry', () => {
    const onPick = vi.fn();
    render(
      <HouseholdPicker
        profiles={[profile(), profile({ id: 'p2', name: 'Max', band: 'middle' }), profile({ id: 'p3', name: '', band: 'upper' })]}
        band="primary"
        onPick={onPick}
        onNew={() => {}}
        onBack={() => {}}
      />,
    );
    expect(screen.getByRole('heading', { name: 'Vem ska prata?' })).toBeDefined();
    // Nameless profiles are not listed; named ones carry their companion.
    expect(screen.queryByText(/ · Björnen/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Max · Lodjuret' }));
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: '+ Någon ny' })).toBeDefined();
  });

  it('shows learners without a band by name only', () => {
    render(
      <HouseholdPicker
        profiles={[{ id: 'p9', name: 'Noa', grade: null, notes: [], createdAt: 1 }]}
        band="primary"
        onPick={() => {}}
        onNew={() => {}}
        onBack={() => {}}
      />,
    );
    expect(screen.getByRole('button', { name: 'Noa' })).toBeDefined();
  });
});

describe('PrivacyPage', () => {
  it('renders the privacy copy with contact link and back', () => {
    const onBack = vi.fn();
    render(<PrivacyPage onBack={onBack} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Om Talarum och din integritet' })).toBeDefined();
    const mail = screen.getByRole('link', { name: 'hej@talarum.se' });
    expect(mail.getAttribute('href')).toBe('mailto:hej@talarum.se');
    fireEvent.click(screen.getByRole('button', { name: /Tillbaka/ }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});

describe('EndCard share', () => {
  it('invites parents on the younger bands and anyone on the upper band', () => {
    const { unmount } = render(<EndCard learnerName="Alva" notes={[]} onBack={() => {}} band="primary" />);
    expect(screen.getByRole('heading', { name: 'Tipsa andra föräldrar' })).toBeDefined();
    unmount();
    cleanup();
    render(<EndCard learnerName="Alva" notes={[]} onBack={() => {}} band="upper" />);
    expect(screen.getByRole('heading', { name: 'Tipsa någon' })).toBeDefined();
  });
});
