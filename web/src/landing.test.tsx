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

describe('mast', () => {
  it('shows the logo, section nav and privacy link beside the menu', () => {
    firstVisit();
    const logo = screen.getByRole('link', { name: 'Talarum' });
    expect(logo.getAttribute('href')).toBe('/');
    expect(logo.querySelector('img')?.getAttribute('alt')).toBe('Talarum');
    const nav = screen.getByRole('navigation', { name: 'Navigering' });
    expect(within(nav).getByRole('link', { name: 'Så går det till' }).getAttribute('href')).toBe('#sa-gar-det-till');
    expect(within(nav).getByRole('link', { name: 'Pris' }).getAttribute('href')).toBe('#pris');
    expect(within(nav).getByRole('link', { name: 'Integritet' }).getAttribute('href')).toBe('/integritet');
    // The right side is the start menu hamburger, not a second CTA.
    expect(screen.getByRole('button', { name: 'Meny' })).toBeDefined();
  });

  it('has exactly one start button per page', () => {
    for (const band of ['primary', 'middle', 'upper'] as const) {
      cleanup();
      firstVisit(band);
      expect(screen.getAllByRole('button', { name: /Prata med / })).toHaveLength(1);
    }
  });

  it('the footer stays calm and links to /integritet', () => {
    firstVisit();
    const footer = screen.getByRole('contentinfo');
    expect(footer?.textContent).toContain('webbläsare');
    const link = within(footer).getByRole('link', { name: /Integritet/ });
    expect(link.getAttribute('href')).toBe('/integritet');
  });

  it('the start button begins the call with audio unlock first', () => {
    const { onPick, order } = firstVisit();
    fireEvent.click(screen.getByRole('button', { name: 'Prata med Räven' }));
    expect(order).toEqual(['unlock', 'pick']);
    expect(onPick).toHaveBeenCalledTimes(1);
    expect((onPick.mock.calls[0][0] as Profile).name).toBe('');
  });

  it('starting from the hero stops the greeting clip', async () => {
    resetGreetingForTests();
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    const { onPick, order } = firstVisit();
    const listen = screen.getByRole('button', { name: 'Hej! Lyssna på Räven' });
    fireEvent.click(listen);
    await waitFor(() => expect(listen.getAttribute('aria-pressed')).toBe('true'));
    fireEvent.click(screen.getByRole('button', { name: 'Prata med Räven' }));
    expect(MockAudio.instances[0].paused).toBe(true);
    expect(order).toEqual(['unlock', 'pick']);
    expect(onPick).toHaveBeenCalledTimes(1);
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
    const lynx = screen.getByRole('link', { name: /Läxhjälp med Lodjuret/ });
    // The href stays a real link (right-click, copy, no-JS), but a plain
    // left click on a talarum-style host navigates without reloading.
    expect(lynx.getAttribute('href')).toContain('/hogstadiet');
    fireEvent.click(lynx);
    expect(onBandLink).toHaveBeenCalledWith('middle');
    const bear = screen.getByRole('link', { name: /Studiestöd med Björnen/ });
    expect(bear.getAttribute('href')).toContain('/gymnasiet');
    fireEvent.click(bear);
    expect(onBandLink).toHaveBeenCalledWith('upper');
  });
});

describe('hero', () => {
  it('renders the headline with the accent word', () => {
    firstVisit();
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('En lugn läxkompis som pratar – och visar.');
  });

  it('names the price anchor beside the start button', () => {
    firstVisit();
    const hero = document.querySelector('.tp-hero') as HTMLElement;
    expect(within(hero).getByText('Gratis medan vi testar.')).toBeDefined();
    expect(within(hero).getByText(/Planerat pris/)).toBeDefined();
  });

  it('the listen control names the greeting and the companion', () => {
    firstVisit('middle');
    expect(screen.getByRole('button', { name: 'Hej! Lyssna på Lodjuret' })).toBeDefined();
  });

  it('cross-links the other two bands as quiet rows after the steps', () => {
    firstVisit();
    const quiet = screen.getByRole('region', { name: 'Andra åldrar' });
    const links = within(quiet).getAllByRole('link');
    expect(links).toHaveLength(2);
    const lynx = within(quiet).getByRole('link', { name: /Läxhjälp med Lodjuret/ });
    expect(lynx.getAttribute('href')).toContain('/hogstadiet');
    expect(lynx.querySelector('img')?.getAttribute('src')).toContain('face.webp');
    const bear = within(quiet).getByRole('link', { name: /Studiestöd med Björnen/ });
    expect(bear.getAttribute('href')).toContain('/gymnasiet');
  });

  it('the middle band invites both younger and older learners', () => {
    firstVisit('middle');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Plugga med någon som lyssnar – och visar.');
    const quiet = screen.getByRole('region', { name: 'Andra åldrar' });
    expect(within(quiet).getAllByRole('link')).toHaveLength(2);
    expect(within(quiet).getByRole('link', { name: /Läxhjälp med Räven/ }).getAttribute('href')).toContain('/ak1-6');
    expect(within(quiet).getByRole('link', { name: /Studiestöd med Björnen/ }).getAttribute('href')).toContain('/gymnasiet');
  });

  it('returning visit keeps the name and the not-you link in one paragraph', () => {
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
    const hello = document.querySelector('p.tp-hello');
    expect(hello).not.toBeNull();
    expect(hello?.textContent).toContain('Hej Elsa!');
    const notYou = within(hello as HTMLElement).getByRole('button', { name: 'Inte Elsa?' });
    expect(notYou).toBeDefined();
    // The single start button assumes the same student.
    fireEvent.click(screen.getByRole('button', { name: 'Prata med Räven' }));
    expect(onPick).toHaveBeenCalledWith(profile());
  });
});

describe('upper band', () => {
  it('speaks to adults: the study-support headline', () => {
    firstVisit('upper');
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Lugnt studiestöd du kan prata med.');
  });

  it('never talks about läxkompis or ditt barn', () => {
    firstVisit('upper');
    const body = (document.body.textContent ?? '').toLowerCase();
    expect(body).not.toContain('läxkompis');
    expect(body).not.toContain('ditt barn');
    expect(screen.getByRole('button', { name: 'Prata med Björnen' })).toBeDefined();
  });

  it('the only quiet link points younger siblings to /', () => {
    const onBandLink = vi.fn();
    render(
      <LandingPage
        profiles={[]}
        band={bandConfig('upper')}
        onPick={() => {}}
        starting={false}
        onSwitch={() => {}}
        onBandLink={onBandLink}
      />,
    );
    const quiet = screen.getByRole('region', { name: 'Andra åldrar' });
    const links = within(quiet).getAllByRole('link');
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute('href')).toBe('/');
    expect(links[0].textContent).toContain('Läxhjälp för åk 1–9');
    fireEvent.click(links[0]);
    expect(onBandLink).toHaveBeenCalledWith('/');
  });

  it('shows the derivative in the notebook', () => {
    firstVisit('upper');
    expect(screen.getAllByText('f′(x) = 2x + 3').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('f′(2) = 7').length).toBeGreaterThanOrEqual(1);
  });

  it('prices study help, not läxhjälp', () => {
    firstVisit('upper');
    const section = document.getElementById('pris');
    expect(section).not.toBeNull();
    expect((section as HTMLElement).textContent).toContain('En timmes studiehjälp kostar');
  });
});

describe.each([
  ['primary', 'Prata med Räven', 'Visa läxan', 'Det barnet hör syns samtidigt på tavlan.', '30 + 40 = 70', '6 + 7 = 13', '70 + 13 = 83'],
  ['middle', 'Prata med Lodjuret', 'Visa läxan', 'Det barnet hör syns samtidigt på tavlan.', '3x + 5 = 20', '3x = 15', 'x = 5'],
  ['upper', 'Prata med Björnen', 'Visa uppgiften', 'Det du hör syns samtidigt på tavlan.', 'f(x) = x² + 3x', 'f′(x) = 2x + 3', 'f′(2) = 7'],
] as Array<[BandId, string, string, string, string, string, string]>)(
  'band %s',
  (band, cta, step1, howHead, row1, row2, row3) => {
    it('shows the steps with the band examples', () => {
      firstVisit(band);
      const steps = document.getElementById('sa-gar-det-till') as HTMLElement;
      expect(within(steps).getByText('Så går det till')).toBeDefined();
      expect(screen.getByRole('heading', { level: 2, name: howHead })).toBeDefined();
      expect(screen.getByRole('heading', { level: 3, name: step1 })).toBeDefined();
      expect(screen.getByRole('heading', { level: 3, name: 'Prata om uppgiften' })).toBeDefined();
      expect(screen.getByRole('heading', { level: 3, name: 'Lös den ihop' })).toBeDefined();
      expect(screen.getAllByText(row1).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(row2).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(row3).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByRole('button', { name: cta })).toHaveLength(1);
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
    // The component only fires the callback (App opens the picker): the
    // returning view itself is unchanged.
    expect(screen.getByText('Hej Elsa!')).toBeDefined();
    expect(screen.getByRole('button', { name: 'Hej Elsa! Lyssna på Räven' })).toBeDefined();
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
    expect(screen.getByRole('button', { name: 'Hej! Lyssna på Lodjuret' })).toBeDefined();
    expect(screen.queryByText('Hej Elsa!')).toBeNull();
  });
});
