import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import HomeChooser from './components/HomeChooser';
import ChooserPage from './components/ChooserPage';
import HouseholdPicker from './components/HouseholdPicker';
import PrivacyPage from './components/PrivacyPage';
import EndCard from './components/EndCard';
import { focusStartControl } from './focus';
import type { Profile } from './db';
import { MockAudio } from './components/mockAudio';
import { resetGreetingForTests, stopGreeting } from './components/greetingAudio';

afterEach(() => {
  cleanup();
  resetGreetingForTests();
  vi.unstubAllGlobals();
});

function profile(over: Partial<Profile> = {}): Profile {
  return { id: 'p1', name: 'Alva', grade: 4, band: 'primary', notes: [], createdAt: 0, ...over };
}

describe('HomeChooser', () => {
  it('offers the two grundskola bands in a switch with one start button', () => {
    const onBegin = vi.fn();
    render(<HomeChooser onBegin={onBegin} starting={false} />);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('En lugn läxkompis som pratar – och visar.');
    const group = screen.getByRole('group', { name: 'Välj årskurs' });
    const options = within(group).getAllByRole('button');
    expect(options).toHaveLength(2);
    expect(options[0].textContent).toContain('Åk 1–6');
    expect(options[0].textContent).toContain('Räven');
    expect(options[1].textContent).toContain('Högstadiet');
    expect(options[1].textContent).toContain('Lodjuret');
    // Räven is selected by default; exactly one start button follows it.
    expect(options[0].getAttribute('aria-pressed')).toBe('true');
    expect(options[1].getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByRole('button', { name: 'Prata med Räven' })).toBeDefined();
    expect(screen.queryByRole('button', { name: 'Prata med Björnen' })).toBeNull();
    // The hero is honest about the price from the start.
    expect(screen.getByText('Gratis medan vi testar.')).toBeDefined();
  });

  it('switching the band moves the start button, the board and the listen control', () => {
    const onBegin = vi.fn();
    render(<HomeChooser onBegin={onBegin} starting={false} />);
    fireEvent.click(screen.getByRole('button', { name: /Högstadiet/ }));
    expect(screen.getByRole('button', { name: /Högstadiet/ }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: /Åk 1–6/ }).getAttribute('aria-pressed')).toBe('false');
    // One start button, now for Lodjuret; the board shows the middle example.
    expect(screen.getByRole('button', { name: 'Prata med Lodjuret' })).toBeDefined();
    expect(screen.queryByRole('button', { name: 'Prata med Räven' })).toBeNull();
    expect(screen.getAllByText('3x + 5 = 20').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole('button', { name: 'Hej! Lyssna på Lodjuret' })).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: 'Prata med Lodjuret' }));
    expect(onBegin).toHaveBeenCalledWith('middle');
  });

  it('the front door has no Björnen start, only a quiet link to /gymnasiet', () => {
    render(<ChooserPage onBegin={vi.fn()} starting={false} />);
    expect(screen.queryByRole('button', { name: 'Prata med Björnen' })).toBeNull();
    const quiet = screen.getByRole('link', { name: /Studiestöd med Björnen/ });
    expect(quiet.getAttribute('href')).toBe('/gymnasiet');
  });

  it('the price section names the planned price and the free test period', () => {
    render(<ChooserPage onBegin={vi.fn()} starting={false} />);
    const section = document.getElementById('pris');
    expect(section).not.toBeNull();
    const scoped = within(section as HTMLElement);
    expect(scoped.getByText('25 kr/tim')).toBeDefined();
    expect(scoped.getByText(/Just nu helt gratis under testperioden/)).toBeDefined();
  });

  it('the listen button plays the hello clip for the selected companion', () => {
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    render(<HomeChooser onBegin={vi.fn()} starting={false} />);
    const listen = screen.getByRole('button', { name: 'Hej! Lyssna på Räven' });
    fireEvent.click(listen);
    expect(MockAudio.instances).toHaveLength(1);
    expect(MockAudio.instances[0].src).toContain('hello-primary.mp3');
    stopGreeting();
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

describe('ChooserPage', () => {
  it('shows a quiet Integritet link in the mast before any call button', () => {
    render(<ChooserPage onBegin={() => {}} starting={false} />);
    const mast = document.querySelector('.tp-mast') as HTMLElement;
    const link = within(mast).getByRole('link', { name: 'Integritet' });
    expect(link.getAttribute('href')).toBe('/integritet');
    // Quiet text link, never a pill row above the headline.
    expect(link.className).toContain('tp-mast-link');
    expect(link.className).not.toContain('tp-cta');
    expect(link.className).not.toContain('tp-listen');
    // The mast comes before the hero start button in the document.
    const cta = screen.getByRole('button', { name: 'Prata med Räven' });
    expect(link.compareDocumentPosition(cta) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('navigates in place on the quiet /gymnasiet link', () => {
    const onNavigate = vi.fn();
    render(<ChooserPage onBegin={() => {}} starting={false} onNavigate={onNavigate} />);
    const quiet = screen.getByRole('link', { name: /Studiestöd med Björnen/ });
    fireEvent.click(quiet);
    expect(onNavigate).toHaveBeenCalledWith('upper');
  });
});

describe('HomeChooser switch start', () => {
  it('stops the greeting clip when a call starts after switching bands', async () => {
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    const onBegin = vi.fn();
    render(<HomeChooser onBegin={onBegin} starting={false} />);
    // Switch to Lodjuret first: the start button follows the switch.
    fireEvent.click(screen.getByRole('button', { name: /Högstadiet/ }));
    const listen = screen.getByRole('button', { name: 'Hej! Lyssna på Lodjuret' });
    fireEvent.click(listen);
    await waitFor(() => expect(listen.getAttribute('aria-pressed')).toBe('true'));
    fireEvent.click(screen.getByRole('button', { name: 'Prata med Lodjuret' }));
    expect(MockAudio.instances[0].paused).toBe(true);
    expect(onBegin).toHaveBeenCalledWith('middle');
    stopGreeting();
  });
});

describe('ChooserPage steps', () => {
  it('shows the steps for the selected band and follows the switch', () => {
    render(<ChooserPage onBegin={vi.fn()} starting={false} />);
    const steps = document.getElementById('sa-gar-det-till') as HTMLElement;
    expect(within(steps).getByText('Så går det till')).toBeDefined();
    expect(screen.getByRole('heading', { name: 'Det barnet hör syns samtidigt på tavlan.' })).toBeDefined();
    expect(screen.getByRole('heading', { name: 'Visa läxan' })).toBeDefined();
    // Family steps name the companion that asks how the child thought.
    expect(screen.getByText(/Räven frågar först/)).toBeDefined();
    expect(screen.getAllByText('30 + 40 = 70').length).toBeGreaterThanOrEqual(1);
    // Switching to Högstadiet moves the steps to the middle example.
    fireEvent.click(screen.getByRole('button', { name: /Högstadiet/ }));
    expect(screen.getByText(/Lodjuret frågar först/)).toBeDefined();
    expect(screen.getAllByText('3x = 15').length).toBeGreaterThanOrEqual(1);
  });

  it('gives the listen control a visible-on-hover title', () => {
    render(<HomeChooser onBegin={vi.fn()} starting={false} />);
    const listen = screen.getByRole('button', { name: 'Hej! Lyssna på Räven' });
    expect(listen.getAttribute('title')).toBe('Lyssna på Räven');
  });
});

describe('HomeChooser listen state', () => {
  it('switching the band stops the playing greeting', async () => {
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    render(<HomeChooser onBegin={vi.fn()} starting={false} />);
    const foxListen = screen.getByRole('button', { name: 'Hej! Lyssna på Räven' });
    fireEvent.click(foxListen);
    await waitFor(() => expect(foxListen.getAttribute('aria-pressed')).toBe('true'));
    // Picking another companion: its hello must not keep playing.
    fireEvent.click(screen.getByRole('button', { name: /Högstadiet/ }));
    expect(MockAudio.instances[0].paused).toBe(true);
    const lynxListen = screen.getByRole('button', { name: 'Hej! Lyssna på Lodjuret' });
    expect(lynxListen.getAttribute('aria-pressed')).toBe('false');
    stopGreeting();
  });

  it('ignores a late error from a clip it already switched away from', async () => {
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    render(<HomeChooser onBegin={vi.fn()} starting={false} />);
    fireEvent.click(screen.getByRole('button', { name: 'Hej! Lyssna på Räven' }));
    await waitFor(() => expect(MockAudio.instances.length).toBe(1));
    fireEvent.click(screen.getByRole('button', { name: /Högstadiet/ }));
    const lynxListen = screen.getByRole('button', { name: 'Hej! Lyssna på Lodjuret' });
    fireEvent.click(lynxListen);
    await waitFor(() => expect(lynxListen.getAttribute('aria-pressed')).toBe('true'));
    // The Räven clip fails late (a 404 arriving after the switch).
    act(() => MockAudio.instances[0].emit('error'));
    expect(lynxListen.getAttribute('aria-pressed')).toBe('true');
    stopGreeting();
  });
});

describe('HouseholdPicker focus', () => {
  it('moves focus to its heading when it opens', () => {
    render(
      <HouseholdPicker profiles={[profile()]} band="primary" onPick={() => {}} onNew={() => {}} onBack={() => {}} />,
    );
    expect(document.activeElement?.textContent).toBe('Vem ska prata?');
  });
  it('restores focus to the opener when it closes', () => {
    const opener = document.createElement('button');
    opener.textContent = 'Inte Alva?';
    document.body.appendChild(opener);
    opener.focus();
    const { unmount } = render(
      <HouseholdPicker profiles={[profile()]} band="primary" onPick={() => {}} onNew={() => {}} onBack={() => {}} />,
    );
    expect(document.activeElement?.textContent).toBe('Vem ska prata?');
    unmount();
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });
});

describe('focusStartControl', () => {
  it('prefers the landing hero CTA over other start buttons', () => {
    document.body.innerHTML =
      '<div class="tp-hero"><button class="tp-cta">Prata med Räven</button></div>' +
      '<div class="tp-sec"><button class="tp-cta">Prata med Lodjuret</button></div>';
    expect(focusStartControl()).toBe(true);
    expect(document.activeElement?.textContent).toBe('Prata med Räven');
    document.body.innerHTML = '';
  });
  it('falls back to any start button and reports when missing', () => {
    document.body.innerHTML =
      '<div class="tp-sec"><button class="tp-cta">Prata med Lodjuret</button></div>';
    expect(focusStartControl()).toBe(true);
    expect(document.activeElement?.textContent).toBe('Prata med Lodjuret');
    document.body.innerHTML = '<div class="tp"></div>';
    expect(focusStartControl()).toBe(false);
    document.body.innerHTML = '';
  });
});

describe('PrivacyPage', () => {
  it('renders the privacy principles with contact link and back', () => {
    const onBack = vi.fn();
    render(<PrivacyPage onBack={onBack} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Om Talarum och din integritet' })).toBeDefined();
    expect(screen.getByRole('heading', { name: 'Det som stannar i webbläsaren' })).toBeDefined();
    expect(screen.getByRole('heading', { name: 'Det som skickas under samtalet' })).toBeDefined();
    expect(screen.getByRole('heading', { name: 'Statistik och reklam' })).toBeDefined();
    const mail = screen.getByRole('link', { name: 'hej@talarum.se' });
    expect(mail.getAttribute('href')).toBe('mailto:hej@talarum.se');
    fireEvent.click(screen.getByRole('button', { name: 'Tillbaka till start' }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('names no vendors and promises no camera-covering rituals', () => {
    render(<PrivacyPage onBack={() => {}} />);
    const body = (document.body.textContent ?? '').toLowerCase();
    for (const vendor of ['livekit', 'soniox', 'deepgram', 'exa', 'commons', 'parallel', 'cloudflare', 'posthog', 'muse']) {
      expect(body).not.toContain(vendor);
    }
    expect(body).not.toContain('täck över');
    expect(body).toContain('hej@talarum.se');
  });

  it('the mast back link returns without reloading', () => {
    const onBack = vi.fn();
    render(<PrivacyPage onBack={onBack} />);
    const back = screen.getByRole('link', { name: /Tillbaka/ });
    expect(back.getAttribute('href')).toBe('/');
    fireEvent.click(back);
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

  it('uses a dedicated share style, not the collapsible header ghost', () => {
    render(<EndCard learnerName="Alva" notes={[]} onBack={() => {}} band="upper" />);
    const button = screen.getByRole('button', { name: 'Tipsa' });
    expect(button.className).toContain('ot-share-btn');
    expect(button.className).not.toContain('ot-land-ghost');
  });

  it('leaves the clipboard alone when the user dismisses the share sheet', async () => {
    const abort = new DOMException('dismissed', 'AbortError');
    Object.defineProperty(navigator, 'share', { value: vi.fn().mockRejectedValue(abort), configurable: true });
    const writeText = vi.fn();
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<EndCard learnerName="Alva" notes={[]} onBack={() => {}} band="upper" />);
    fireEvent.click(screen.getByRole('button', { name: 'Tipsa' }));
    await waitFor(() => expect(navigator.share).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(writeText).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Tipsa' })).toBeDefined();
    delete (navigator as unknown as Record<string, unknown>).share;
  });

  it('copies the link when the share sheet is missing or fails otherwise', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    delete (navigator as unknown as Record<string, unknown>).share;
    const { unmount } = render(<EndCard learnerName="Alva" notes={[]} onBack={() => {}} band="primary" />);
    fireEvent.click(screen.getByRole('button', { name: 'Tipsa' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('https://talarum.se/'));
    expect(screen.getByRole('button', { name: 'Kopierat ✓' })).toBeDefined();
    unmount();
    cleanup();
    // A non-dismissal share failure also falls back to the clipboard.
    Object.defineProperty(navigator, 'share', { value: vi.fn().mockRejectedValue(new Error('nope')), configurable: true });
    const writeText2 = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: writeText2 }, configurable: true });
    render(<EndCard learnerName="Alva" notes={[]} onBack={() => {}} band="primary" />);
    fireEvent.click(screen.getByRole('button', { name: 'Tipsa' }));
    await waitFor(() => expect(writeText2).toHaveBeenCalledWith('https://talarum.se/'));
    delete (navigator as unknown as Record<string, unknown>).share;
  });
});
