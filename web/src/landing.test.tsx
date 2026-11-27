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

/** The h1 is built from three catalogue parts with NBSPs; compare plainly. */
function norm(s: string | null | undefined): string {
  return (s ?? '').replace(/ /g, ' ');
}

function h1Text(): string {
  return norm(screen.getByRole('heading', { level: 1 }).textContent);
}

function startButtons(name: string): HTMLElement[] {
  return screen.getAllByRole('button', { name }) as HTMLElement[];
}

describe('masthead', () => {
  it('shows the logo, the Skolnivå band nav and the Integritet link', () => {
    firstVisit();
    const logo = screen.getByRole('link', { name: 'Talarum' });
    expect(logo.getAttribute('href')).toBe('/');
    expect(logo.querySelector('img')?.getAttribute('alt')).toBe('Talarum');
    const nav = screen.getByRole('navigation', { name: 'Skolnivå' });
    const primary = within(nav).getByRole('link', { name: 'Åk 1–6' });
    const middle = within(nav).getByRole('link', { name: 'Högstadiet' });
    const upper = within(nav).getByRole('link', { name: 'Gymnasiet' });
    // On a non-tutor host (like jsdom's localhost) Åk 1–6 is the front door.
    expect(primary.getAttribute('href')).toBe('/');
    expect(middle.getAttribute('href')).toBe('/hogstadiet');
    expect(upper.getAttribute('href')).toBe('/gymnasiet');
    // The old section links are gone: the nav only names the three bands.
    expect(within(nav).queryByRole('link', { name: 'Så går det till' })).toBeNull();
    expect(within(nav).queryByRole('link', { name: 'Pris' })).toBeNull();
    const privacy = within(document.querySelector('.tp-mast') as HTMLElement).getByRole('link', { name: 'Integritet' });
    expect(privacy.getAttribute('href')).toBe('/integritet');
  });

  it('marks the current band and leaves Integritet unmarked on band pages', () => {
    firstVisit('middle');
    const nav = screen.getByRole('navigation', { name: 'Skolnivå' });
    expect(within(nav).getByRole('link', { name: 'Åk 1–6' }).getAttribute('aria-current')).toBeNull();
    expect(within(nav).getByRole('link', { name: 'Högstadiet' }).getAttribute('aria-current')).toBe('page');
    expect(within(nav).getByRole('link', { name: 'Gymnasiet' }).getAttribute('aria-current')).toBeNull();
    const mast = document.querySelector('.tp-mast') as HTMLElement;
    expect(within(mast).getByRole('link', { name: 'Integritet' }).getAttribute('aria-current')).toBeNull();
  });

  it('shows the Meny button only once the device remembers someone', () => {
    firstVisit();
    expect(screen.queryByRole('button', { name: 'Meny' })).toBeNull();
    cleanup();
    render(
      <LandingPage
        profiles={[profile()]}
        band={bandConfig('primary')}
        onPick={() => {}}
        starting={false}
        onSwitch={() => {}}
      />,
    );
    expect(screen.getByRole('button', { name: 'Meny' })).toBeDefined();
    cleanup();
    // A nameless stored profile is not someone: still no menu.
    render(
      <LandingPage
        profiles={[profile({ name: '' })]}
        band={bandConfig('primary')}
        onPick={() => {}}
        starting={false}
        onSwitch={() => {}}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Meny' })).toBeNull();
  });

  it('band links navigate in place; the active band link stays put', () => {
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
    const nav = screen.getByRole('navigation', { name: 'Skolnivå' });
    const middle = within(nav).getByRole('link', { name: 'Högstadiet' });
    // The href stays a real link (right-click, copy, no-JS), but a plain
    // left click on a talarum-style host navigates without reloading.
    expect(middle.getAttribute('href')).toBe('/hogstadiet');
    expect(fireEvent.click(middle)).toBe(false);
    expect(onBandLink).toHaveBeenCalledWith('middle');
    const upper = within(nav).getByRole('link', { name: 'Gymnasiet' });
    expect(fireEvent.click(upper)).toBe(false);
    expect(onBandLink).toHaveBeenCalledWith('upper');
    // Clicking the band we are already on fires no navigation.
    const current = within(nav).getByRole('link', { name: 'Åk 1–6' });
    expect(fireEvent.click(current)).toBe(false);
    expect(onBandLink).toHaveBeenCalledTimes(2);
  });
});

describe('start flow', () => {
  it('has TWO start buttons per page, and both start the call the same way', () => {
    for (const [band, cta] of [
      ['primary', 'Prata med Räven'],
      ['middle', 'Prata med Lodjuret'],
      ['upper', 'Prata med Björnen'],
    ] as Array<[BandId, string]>) {
      cleanup();
      const { onPick, order } = firstVisit(band);
      const buttons = startButtons(cta);
      expect(buttons).toHaveLength(2);
      fireEvent.click(buttons[0]);
      fireEvent.click(buttons[1]);
      expect(order).toEqual(['unlock', 'pick', 'unlock', 'pick']);
      expect(onPick).toHaveBeenCalledTimes(2);
      expect((onPick.mock.calls[0][0] as Profile).name).toBe('');
    }
  });

  it('starting from the hero stops the greeting clip', async () => {
    resetGreetingForTests();
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    const { onPick, order } = firstVisit();
    const listen = screen.getAllByRole('button', { name: /Hör rösten\s*– Räven/ })[0];
    fireEvent.click(listen);
    await waitFor(() => expect(listen.getAttribute('aria-pressed')).toBe('true'));
    fireEvent.click(startButtons('Prata med Räven')[0]);
    expect(MockAudio.instances[0].paused).toBe(true);
    expect(order).toEqual(['unlock', 'pick']);
    expect(onPick).toHaveBeenCalledTimes(1);
  });

  it('the closing call to action stops the greeting too', async () => {
    resetGreetingForTests();
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    firstVisit();
    const listen = screen.getAllByRole('button', { name: /Hör rösten\s*– Räven/ })[1];
    fireEvent.click(listen);
    await waitFor(() => expect(listen.getAttribute('aria-pressed')).toBe('true'));
    fireEvent.click(startButtons('Prata med Räven')[1]);
    expect(MockAudio.instances[0].paused).toBe(true);
  });

  it('there are two listen buttons, both following the same clip', async () => {
    resetGreetingForTests();
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    firstVisit();
    const buttons = screen.getAllByRole('button', { name: /Hör rösten\s*– Räven/ });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(buttons[0].getAttribute('aria-pressed')).toBe('true'));
    expect(buttons[1].getAttribute('aria-pressed')).toBe('true');
    expect(screen.getAllByRole('button', { name: /Spelar…\s*– Räven/ })).toHaveLength(2);
    fireEvent.click(buttons[1]);
    expect(MockAudio.instances[0].paused).toBe(true);
  });
});

describe('hero', () => {
  it.each([
    ['primary', 'En lugn läxhjälp som pratar – och visar.'],
    ['middle', 'En lugn läxhjälp du kan prata med.'],
    ['upper', 'Lugnt studiestöd du kan prata med.'],
  ] as Array<[BandId, string]>)('the %s headline reads %s', (band, headline) => {
    firstVisit(band);
    expect(h1Text()).toBe(headline);
  });

  it('the quiet line names the free test period and no account', () => {
    firstVisit();
    const hero = document.querySelector('.tp-hero') as HTMLElement;
    const quiet = norm(hero.textContent);
    expect(quiet).toContain('Gratis medan vi testar');
    expect(quiet).toContain('Inget konto');
  });

  it('the listen control names the greeting and the companion', () => {
    firstVisit('middle');
    const b = screen.getAllByRole('button', { name: /Hör rösten\s*– Lodjuret/ })[0];
    expect(b.getAttribute('aria-pressed')).toBe('false');
    expect(b.getAttribute('title')).toBe('Lyssna på Lodjuret');
    expect(b.textContent).toContain('Hör rösten');
  });

  it('shows work in progress, never the finished answer, in the hero', () => {
    firstVisit();
    const figure = document.querySelector('figure.tp-show') as HTMLElement;
    expect(figure?.getAttribute('aria-label')).toBe('Exempel: Räven går igenom en uppgift');
    expect(norm(figure.textContent)).toContain('30 + 40 = 70');
    expect(norm(figure.textContent)).toContain('6 + 7 = ?');
    expect(norm(figure.textContent)).not.toContain('83');
    expect(within(figure).getByText('Barnet:')).toBeDefined();
    expect(within(figure).getByText('Jag började med 30 plus 40.')).toBeDefined();
    expect(within(figure).getByText('Räven:')).toBeDefined();
    expect(within(figure).getByText('Snyggt! Vad blir 6 plus 7 då?')).toBeDefined();
  });

  it('the middle hero speaks to the learner directly', () => {
    firstVisit('middle');
    const figure = document.querySelector('figure.tp-show') as HTMLElement;
    expect(figure?.getAttribute('aria-label')).toBe('Exempel: Lodjuret går igenom en uppgift');
    expect(norm(figure.textContent)).toContain('3x = 15');
    expect(norm(figure.textContent)).toContain('x = ?');
    expect(within(figure).getByText('Du:')).toBeDefined();
  });

  it('the companion call window names the companion and the pointing pose', () => {
    firstVisit();
    const call = screen.getByRole('img', { name: 'Räven i samtalet' });
    const pose = call.querySelector('img');
    expect(pose?.getAttribute('src')).toContain('pointing.webp');
  });

  it('never mentions a board that shows the page', () => {
    for (const band of ['primary', 'middle', 'upper'] as const) {
      cleanup();
      firstVisit(band);
      expect(document.body.textContent).not.toContain('Tavlan, just nu');
    }
  });
});

describe('voice', () => {
  it('the primary page speaks to parents about their child', () => {
    firstVisit('primary');
    expect(screen.getByRole('heading', { name: 'Så hjälper Talarum barnet framåt.' })).toBeDefined();
    expect(screen.getByRole('heading', { name: /Barnet löser själv/ })).toBeDefined();
    const steps = document.getElementById('sa-gar-det-till') as HTMLElement;
    expect(steps.textContent).not.toContain(' du ');
  });

  it('the middle and upper pages speak to the learner directly', () => {
    for (const band of ['middle', 'upper'] as const) {
      cleanup();
      firstVisit(band);
      expect(screen.getByRole('heading', { name: 'Så hjälper Talarum dig framåt.' })).toBeDefined();
      expect(screen.getByRole('heading', { name: /Du löser själv/ })).toBeDefined();
      expect(document.body.textContent).not.toContain('Ditt barn');
    }
  });

  it('the upper hero never promises läxhjälp', () => {
    firstVisit('upper');
    const hero = document.querySelector('.tp-hero') as HTMLElement;
    expect(norm(hero.textContent).toLowerCase()).not.toContain('läxhjälp');
  });

  it('the closing question matches the voice', () => {
    firstVisit('primary');
    expect(screen.getByRole('heading', { name: 'Redo att testa på kvällens läxa?' })).toBeDefined();
    cleanup();
    firstVisit('middle');
    expect(screen.getByRole('heading', { name: 'Redo att testa på nästa uppgift?' })).toBeDefined();
    cleanup();
    firstVisit('upper');
    expect(screen.getByRole('heading', { name: 'Redo att testa på nästa uppgift?' })).toBeDefined();
  });
});

describe('steps', () => {
  it('shows three illustrations with the band maths written over them', () => {
    firstVisit('middle');
    const steps = document.getElementById('sa-gar-det-till') as HTMLElement;
    const srcs = Array.from(steps.querySelectorAll('img')).map((img) => img.getAttribute('src'));
    expect(srcs).toContain('/illustrations/step-capture.webp');
    expect(srcs).toContain('/illustrations/step-talk-middle.webp');
    expect(srcs).toContain('/illustrations/step-solve.webp');
    expect(norm(steps.textContent)).toContain('3x + 5 = 20');
    expect(norm(steps.textContent)).toContain('3x = 15');
    expect(norm(steps.textContent)).toContain('x = 5');
  });

  it('the primary illustrations carry the primary maths', () => {
    firstVisit('primary');
    const steps = document.getElementById('sa-gar-det-till') as HTMLElement;
    const srcs = Array.from(steps.querySelectorAll('img')).map((img) => img.getAttribute('src'));
    expect(srcs).toContain('/illustrations/step-talk-primary.webp');
    expect(norm(steps.textContent)).toContain('36 + 47');
    expect(norm(steps.textContent)).toContain('30 + 40 = 70');
  });

  it('the upper illustrations carry the derivative', () => {
    firstVisit('upper');
    const steps = document.getElementById('sa-gar-det-till') as HTMLElement;
    const srcs = Array.from(steps.querySelectorAll('img')).map((img) => img.getAttribute('src'));
    expect(srcs).toContain('/illustrations/step-talk-upper.webp');
    expect(norm(steps.textContent)).toContain('f′(x) = 2x + 3');
    expect(norm(steps.textContent)).toContain('f′(2) = 7');
  });
});

describe('steps for screen readers', () => {
  it('names each step equation once, including the finished line', () => {
    firstVisit('primary');
    const steps = document.getElementById('sa-gar-det-till') as HTMLElement;
    const names = within(steps).getAllByRole('img').map((el) => el.getAttribute('aria-label'));
    expect(names).toEqual(['36 + 47', '30 + 40 = 70', '70 + 13 = 83']);
  });
});

describe('price', () => {
  it('comes after the steps and names the free test period', () => {
    firstVisit();
    const steps = document.getElementById('sa-gar-det-till') as HTMLElement;
    const price = document.getElementById('pris') as HTMLElement;
    expect(steps.compareDocumentPosition(price) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(price).getByText('Gratis medan vi testar.')).toBeDefined();
    expect(within(price).getByText('Nu')).toBeDefined();
    expect(within(price).getByText('0 kr')).toBeDefined();
    expect(within(price).getByText('Planerat senare')).toBeDefined();
    expect(within(price).getByText('Bindningstid')).toBeDefined();
    expect(within(price).getByText('Ingen prenumeration')).toBeDefined();
  });

  it('compares against private tutoring, named per audience', () => {
    firstVisit('primary');
    expect(screen.getByText('Privat läxhjälp')).toBeDefined();
    cleanup();
    firstVisit('middle');
    expect(screen.getByText('Privat läxhjälp')).toBeDefined();
    cleanup();
    firstVisit('upper');
    expect(screen.getByText('Privatlärare')).toBeDefined();
    expect(screen.queryByText('Privat läxhjälp')).toBeNull();
  });
});

describe('footer', () => {
  it('stays calm and links to /integritet', () => {
    firstVisit();
    const footer = screen.getByRole('contentinfo');
    expect(footer?.textContent).toContain('Ett svenskt experiment');
    expect(footer?.textContent).not.toContain('sparas lokalt');
    expect(footer?.textContent).not.toContain('webbläsare');
    const link = within(footer).getByRole('link', { name: /Integritet/ });
    expect(link.getAttribute('href')).toBe('/integritet');
  });
});

describe('returning visit', () => {
  it('keeps the name and the not-you link in one paragraph', () => {
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
    // Either start button assumes the same student.
    const buttons = startButtons('Prata med Räven');
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[0]);
    expect(onPick).toHaveBeenCalledWith(profile());
  });
});

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
    expect(screen.getAllByRole('button', { name: /Hör rösten\s*– Räven/ })[0]).toBeDefined();
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
    expect(screen.getAllByRole('button', { name: /Hör rösten\s*– Lodjuret/ })[0]).toBeDefined();
    expect(screen.queryByText('Hej Elsa!')).toBeNull();
  });
});
