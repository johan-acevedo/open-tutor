import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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

  it('plays the hello clip when a portrait is tapped', () => {
    const onBegin = vi.fn();
    render(<HomeChooser onBegin={onBegin} starting={false} />);
    const face = screen.getByRole('button', { name: /Lyssna på Björnen$/ });
    expect(face.querySelector('img')?.getAttribute('src')).toContain('hero.webp');
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
  it('shows a quiet Integritet link in the header before any call button', () => {
    render(<ChooserPage onBegin={() => {}} starting={false} />);
    const link = screen.getByRole('link', { name: 'Integritet' });
    expect(link.getAttribute('href')).toBe('/integritet');
    // Quiet text link, never a pill row above the headline.
    expect(link.className).not.toContain('ot-land-ghost');
    expect(link.className).not.toContain('ot-land-cta');
    expect(link.className).toContain('ot-choose-privacy');
  });
});

describe('HomeChooser card start', () => {
  it('stops the greeting clip when a call starts from a card', async () => {
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    const onBegin = vi.fn();
    render(<HomeChooser onBegin={onBegin} starting={false} />);
    const face = screen.getByRole('button', { name: /Lyssna på Lodjuret$/ });
    fireEvent.click(face);
    await waitFor(() => expect(MockAudio.instances.length).toBeGreaterThan(0));
    fireEvent.click(screen.getByRole('button', { name: 'Prata med Lodjuret' }));
    expect(MockAudio.instances[0].paused).toBe(true);
    expect(onBegin).toHaveBeenCalledWith('middle');
    stopGreeting();
  });
});

describe('ChooserPage steps', () => {
  it('keeps the how-it-works steps band-neutral under all three companions', () => {
    render(<ChooserPage onBegin={vi.fn()} starting={false} />);
    expect(screen.getByRole('heading', { name: 'Prata om uppgiften' })).toBeDefined();
    expect(screen.getByText('Fota uppgiften, så syns den på tavlan.')).toBeDefined();
    // The companion-specific step copy belongs to the band pages only.
    expect(screen.queryByRole('heading', { name: 'Prata med Räven' })).toBeNull();
    expect(screen.queryByText(/så ser Räven den/)).toBeNull();
  });

  it('gives each portrait a visible-on-hover listen title', () => {
    render(<HomeChooser onBegin={vi.fn()} starting={false} />);
    const fox = screen.getByRole('button', { name: /Lyssna på Räven$/ });
    expect(fox.getAttribute('title')).toBe('Lyssna på Räven');
  });
});

describe('HomeChooser listen state', () => {
  it('marks only the playing companion portrait as pressed', async () => {
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    render(<HomeChooser onBegin={vi.fn()} starting={false} />);
    const lynx = screen.getByRole('button', { name: /Lyssna på Lodjuret$/ });
    const bear = screen.getByRole('button', { name: /Lyssna på Björnen$/ });
    fireEvent.click(lynx);
    await waitFor(() => expect(lynx.getAttribute('aria-pressed')).toBe('true'));
    expect(bear.getAttribute('aria-pressed')).toBe('false');
    stopGreeting();
    await waitFor(() => expect(lynx.getAttribute('aria-pressed')).toBe('false'));
  });

  it('ignores a late error from a clip it already switched away from', async () => {
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    render(<HomeChooser onBegin={vi.fn()} starting={false} />);
    const lynx = screen.getByRole('button', { name: /Lyssna på Lodjuret$/ });
    const bear = screen.getByRole('button', { name: /Lyssna på Björnen$/ });
    fireEvent.click(lynx);
    await waitFor(() => expect(lynx.getAttribute('aria-pressed')).toBe('true'));
    fireEvent.click(bear);
    await waitFor(() => expect(bear.getAttribute('aria-pressed')).toBe('true'));
    // The lynx clip fails late (a 404 arriving after the switch).
    act(() => MockAudio.instances[0].emit('error'));
    expect(bear.getAttribute('aria-pressed')).toBe('true');
    expect(lynx.getAttribute('aria-pressed')).toBe('false');
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
  it('prefers the landing hero CTA over chooser card CTAs', () => {
    document.body.innerHTML =
      '<div class="ot-land-hero"><button class="ot-land-cta">Prata med Räven</button></div>' +
      '<div class="ot-choose-card"><button class="ot-choose-cta">Prata med Lodjuret</button></div>';
    expect(focusStartControl()).toBe(true);
    expect(document.activeElement?.textContent).toBe('Prata med Räven');
    document.body.innerHTML = '';
  });
  it('falls back to the first chooser card CTA and reports when missing', () => {
    document.body.innerHTML =
      '<div class="ot-choose-card"><button class="ot-choose-cta">Prata med Lodjuret</button></div>';
    expect(focusStartControl()).toBe(true);
    expect(document.activeElement?.textContent).toBe('Prata med Lodjuret');
    document.body.innerHTML = '<div class="ot-land"></div>';
    expect(focusStartControl()).toBe(false);
    document.body.innerHTML = '';
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
