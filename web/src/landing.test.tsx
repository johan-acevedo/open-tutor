import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { bandConfig, type BandId } from './bands';
import type { Profile } from './db';
import LandingPage from './components/LandingPage';

afterEach(() => {
  cleanup();
  localStorage.clear();
});

function profile(over: Partial<Profile> = {}): Profile {
  return { id: 'p1', name: 'Elsa', grade: 4, notes: [], createdAt: 0, ...over };
}

function firstVisit(band: BandId = 'primary') {
  const onPick = vi.fn();
  const order: string[] = [];
  render(
    <LandingPage
      profiles={[]}
      band={bandConfig(band)}
      onPick={(p: Profile) => { order.push('pick'); onPick(p); }}
      starting={false}
      onStartGesture={() => order.push('unlock')}
      onSwitch={() => {}}
    />,
  );
  return { onPick, order };
}

describe('top bar', () => {
  it('shows the brand, nav links and ghost CTA on desktop', () => {
    firstVisit();
    expect(screen.getByText('Open Tutor')).toBeDefined();
    expect(screen.getByRole('link', { name: 'Så funkar det' }).getAttribute('href')).toBe('#sa-funkar-det');
    expect(screen.getByRole('button', { name: 'Om Open Tutor' })).toBeDefined();
    expect(screen.getByRole('button', { name: 'Integritet' })).toBeDefined();
    expect(screen.getAllByRole('button', { name: 'Prata med Räven' })).toHaveLength(2);
  });

  it('the ghost button starts the call exactly like the hero CTA', () => {
    const { onPick, order } = firstVisit();
    const [ghost] = screen.getAllByRole('button', { name: 'Prata med Räven' });
    fireEvent.click(ghost);
    expect(order).toEqual(['unlock', 'pick']);
    expect(onPick).toHaveBeenCalledTimes(1);
    expect((onPick.mock.calls[0][0] as Profile).name).toBe('');
  });

  it('the nav opens the about and privacy panels from outside the menu', () => {
    firstVisit();
    const nav = screen.getByRole('navigation', { name: 'Navigering' });
    fireEvent.click(within(nav).getByRole('button', { name: 'Om Open Tutor' }));
    expect(screen.getByLabelText('Om Open Tutor')).toBeDefined();
    fireEvent.click(within(nav).getByRole('button', { name: 'Integritet' }));
    expect(screen.getByLabelText('Integritet')).toBeDefined();
  });

  it('the footer privacy button opens the privacy panel', () => {
    firstVisit();
    const trigger = screen.getByRole('button', { name: /Läs om integritet/ });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole('dialog', { name: 'Integritet' });
    expect(document.activeElement).toBe(dialog);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Integritet' })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

describe('hero', () => {
  it('renders the headline with the accent word', () => {
    firstVisit();
    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1.textContent).toBe('Läxhjälp du kan prata med.');
  });

  it('links the other bands with faces', () => {
    firstVisit();
    const lynx = screen.getByRole('link', { name: 'Lodjuret' });
    expect(lynx.getAttribute('href')).toContain('band=middle');
    const face = lynx.querySelector('img.ot-land-face');
    expect(face?.getAttribute('src')).toContain('face.webp');
    expect(screen.getByRole('link', { name: 'Björnen' }).getAttribute('href')).toContain('band=upper');
  });

  it('returning visit shares the row between CTA and not-you', () => {
    localStorage.setItem('open-tutor-last-profile', 'p1');
    const onPick = vi.fn();
    render(
      <LandingPage
        profiles={[profile()]}
        band={bandConfig('primary')}
        onPick={onPick}
        starting={false}
        onSwitch={() => {}}
      />,
    );
    expect(screen.getByText('Hej Elsa!')).toBeDefined();
    const [ghost, hero] = screen.getAllByRole('button', { name: 'Prata med Räven' });
    // Both start the same assumed call.
    fireEvent.click(ghost);
    expect(onPick).toHaveBeenCalledWith(profile());
    onPick.mockClear();
    fireEvent.click(hero);
    expect(onPick).toHaveBeenCalledWith(profile());
    expect(screen.getByRole('button', { name: 'Inte Elsa?' })).toBeDefined();
  });
});

describe.each([
  ['primary', 'Prata med Räven', '36 + 47 = ?', '36 + 47', '70 + 13', '= 83'],
  ['middle', 'Prata med Lodjuret', '3x + 5 = 20', '3x + 5 = 20', '3x = 15', 'x = 5'],
  ['upper', 'Prata med Björnen', 'f(x) = x² + 3x', 'f(x) = x² + 3x', 'f′(x) = 2x + 3', 'f′(2) = 7'],
] as Array<[BandId, string, string, string, string, string]>)(
  'band %s',
  (band, cta, paper, row1, row2, row3) => {
    it('shows the steps with the band examples', () => {
      firstVisit(band);
      expect(screen.getByRole('heading', { level: 2, name: 'Så funkar det' })).toBeDefined();
      expect(screen.getByRole('heading', { level: 3, name: 'Visa läxan' })).toBeDefined();
      expect(screen.getAllByText(paper).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByRole('heading', { level: 3, name: cta })).toBeDefined();
      expect(screen.getByRole('heading', { level: 3, name: 'Lös den ihop' })).toBeDefined();
      expect(screen.getAllByText(row1).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(row2)).toBeDefined();
      expect(screen.getByText(row3)).toBeDefined();
      expect(screen.getAllByRole('button', { name: cta })).toHaveLength(2);
    });
  },
);
