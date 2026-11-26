import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { bandConfig, type BandId } from './bands';
import type { Profile } from './db';
import LandingPage from './components/LandingPage';
import { MockAudio } from './components/mockAudio';
import { resetGreetingForTests } from './components/greetingAudio';

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
  resetGreetingForTests();
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
    expect(screen.getByText('talarum')).toBeDefined();
    expect(screen.getByRole('link', { name: 'Så funkar det' }).getAttribute('href')).toBe('#sa-funkar-det');
    expect(screen.getByRole('button', { name: 'Om Talarum' })).toBeDefined();
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
    fireEvent.click(within(nav).getByRole('button', { name: 'Om Talarum' }));
    expect(screen.getByLabelText('Om Talarum')).toBeDefined();
    fireEvent.click(within(nav).getByRole('button', { name: 'Integritet' }));
    expect(screen.getByLabelText('Integritet')).toBeDefined();
  });

  it('the footer links to the /integritet page', () => {
    firstVisit();
    const link = screen.getByRole('link', { name: /Läs om integritet/ });
    expect(link.getAttribute('href')).toBe('/integritet');
  });

  it('the footer says profiles stay local and calls go to providers', () => {
    firstVisit();
    const footer = document.querySelector('.ot-land-foot');
    expect(footer?.textContent).toContain('webbläsaren');
    expect(footer?.textContent).toContain('Integritet');
    // The old line claimed everything stays in the browser; conversation
    // content goes to the providers named on /integritet.
    expect(footer?.textContent).not.toContain('sparas bara i din webbläsare');
  });

  it('cross-band links navigate in place when the host picks no band', () => {
    const onBandLink = vi.fn();
    render(
      <LandingPage
        profiles={[]}
        band={bandConfig('primary')}
        onPick={() => {}}
        starting={false}
        onSwitch={() => {}}
        onBandLink={onBandLink}
      />,
    );
    const lynx = screen.getByRole('link', { name: 'Högstadiet med Lodjuret' });
    // The href stays a real link (right-click, copy, no-JS), but a plain
    // left click on a talarum-style host navigates without reloading.
    expect(lynx.getAttribute('href')).toContain('/hogstadiet');
    fireEvent.click(lynx);
    expect(onBandLink).toHaveBeenCalledWith('middle');
  });
  it('the ghost button stops the greeting clip when starting', async () => {
    resetGreetingForTests();
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    const { onPick, order } = firstVisit();
    const bubble = screen.getByRole('button', { name: /Lyssna på Räven$/ });
    fireEvent.click(bubble);
    await waitFor(() => expect(bubble.getAttribute('aria-pressed')).toBe('true'));
    const [ghost] = screen.getAllByRole('button', { name: 'Prata med Räven' });
    fireEvent.click(ghost);
    expect(MockAudio.instances[0].paused).toBe(true);
    expect(order).toEqual(['unlock', 'pick']);
    expect(onPick).toHaveBeenCalledTimes(1);
  });
});

describe('hero', () => {
  it('renders the headline with the accent word', () => {
    firstVisit();
    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1.textContent).toBe('Läxhjälp du kan prata med.');
  });

  it('asks to show the homework so the companion sees it too', () => {
    firstVisit();
    expect(screen.getByText('Fota uppgiften, så ser Räven den också.')).toBeDefined();
  });

  it('step 2 shows a static three-dot speech bubble, step 3 no operation labels', () => {
    firstVisit();
    expect(document.querySelectorAll('.ot-land-chat i')).toHaveLength(3);
    expect(document.querySelector('.ot-land-wave')).toBeNull();
    expect(screen.queryByText('dela upp')).toBeNull();
    expect(screen.queryByText('lägg ihop')).toBeNull();
  });

  it('cross-links the other two bands as whole cards after the steps', () => {
    firstVisit();
    expect(screen.getByRole('heading', { level: 2, name: 'Går du i en annan årskurs?' })).toBeDefined();
    const lynx = screen.getByRole('link', { name: 'Högstadiet med Lodjuret' });
    expect(lynx.getAttribute('href')).toContain('/hogstadiet');
    const face = lynx.querySelector('img.ot-land-bandface');
    expect(face?.getAttribute('src')).toContain('face.webp');
    const bear = screen.getByRole('link', { name: 'Gymnasiet och vuxna med Björnen' });
    expect(bear.getAttribute('href')).toContain('/gymnasiet');
  });

  it('names the younger bands for the upper band', () => {
    firstVisit('upper');
    expect(screen.getByRole('heading', { level: 2, name: 'Någon yngre hemma?' })).toBeDefined();
    expect(screen.getByRole('link', { name: 'Åk 1–6 med Räven' }).getAttribute('href')).toContain('/ak1-6');
    expect(screen.getByRole('link', { name: 'Högstadiet med Lodjuret' }).getAttribute('href')).toContain('/hogstadiet');
  });

  it('the middle band invites both younger and older learners', () => {
    firstVisit('middle');
    expect(screen.getByRole('heading', { level: 2, name: 'Går du i en annan årskurs?' })).toBeDefined();
    expect(screen.getByRole('link', { name: 'Åk 1–6 med Räven' }).getAttribute('href')).toContain('/ak1-6');
    expect(screen.getByRole('link', { name: 'Gymnasiet och vuxna med Björnen' }).getAttribute('href')).toContain('/gymnasiet');
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
  ['primary', 'Prata med Räven', '36 + 47 = ?', '30 + 40 = 70', '6 + 7 = 13', '70 + 13 = 83'],
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

describe('household picker entry', () => {
  it('opens the picker from Inte-namnet instead of the nameless view', () => {
    localStorage.setItem('open-tutor-last-profile', 'p1');
    const onNotYou = vi.fn();
    render(
      <LandingPage
        profiles={[profile()]}
        band={bandConfig('primary')}
        onPick={() => {}}
        starting={false}
        onSwitch={() => {}}
        onNotYou={onNotYou}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Inte Elsa?' }));
    expect(onNotYou).toHaveBeenCalledTimes(1);
    // The nameless view is not shown: still the returning view.
    expect(screen.queryByText('Hej!')).toBeNull();
    expect(screen.getByText('Hej Elsa!')).toBeDefined();
  });

  it('ignores a remembered learner from another band on a band route', () => {
    localStorage.setItem('open-tutor-last-profile', 'p1');
    render(
      <LandingPage
        profiles={[profile()]}
        band={bandConfig('middle')}
        onPick={() => {}}
        starting={false}
        onSwitch={() => {}}
        ignoreLastId
      />,
    );
    expect(screen.getByText('Hej!')).toBeDefined();
    expect(screen.queryByText('Hej Elsa!')).toBeNull();
  });
});
