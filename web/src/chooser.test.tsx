import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import ChooserPage from './components/ChooserPage';
import HouseholdPicker from './components/HouseholdPicker';
import PrivacyPage from './components/PrivacyPage';
import EndCard from './components/EndCard';
import { focusStartControl } from './focus';
import type { Profile } from './db';
import { MockAudio } from './components/mockAudio';
import { resetGreetingForTests } from './components/greetingAudio';

afterEach(() => {
  cleanup();
  resetGreetingForTests();
  vi.unstubAllGlobals();
});

function profile(over: Partial<Profile> = {}): Profile {
  return { id: 'p1', name: 'Alva', grade: 4, band: 'primary', notes: [], createdAt: 0, ...over };
}

/** The h1 is built from three catalogue parts with NBSPs; compare plainly. */
function norm(s: string | null | undefined): string {
  return (s ?? '').replace(/ /g, ' ');
}

describe('ChooserPage', () => {
  it('is always the first-visit Räven page: no band switch, two start buttons', () => {
    const onBegin = vi.fn();
    render(<ChooserPage onBegin={onBegin} starting={false} />);
    expect(norm(screen.getByRole('heading', { level: 1 }).textContent)).toBe(
      'En lugn läxhjälp som pratar – och visar.',
    );
    expect(screen.queryByRole('group', { name: 'Välj årskurs' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Prata med Linnea' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Prata med Björnen' })).toBeNull();
    expect(screen.getAllByRole('button', { name: 'Prata med Räven' })).toHaveLength(2);
    // The hero is honest about the price from the start.
    expect(screen.getByText('Gratis medan vi testar')).toBeDefined();
    expect(screen.getByText('Inget konto')).toBeDefined();
  });

  it('both start buttons begin primary and stop the greeting', async () => {
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    const onBegin = vi.fn();
    render(<ChooserPage onBegin={onBegin} starting={false} />);
    const listen = screen.getAllByRole('button', { name: /Hör rösten\s*– Räven/ })[0];
    fireEvent.click(listen);
    await waitFor(() => expect(listen.getAttribute('aria-pressed')).toBe('true'));
    const buttons = screen.getAllByRole('button', { name: 'Prata med Räven' });
    fireEvent.click(buttons[0]);
    expect(MockAudio.instances[0].paused).toBe(true);
    expect(onBegin).toHaveBeenCalledTimes(1);
    expect(onBegin).toHaveBeenCalledWith('primary');
    fireEvent.click(buttons[1]);
    expect(onBegin).toHaveBeenCalledTimes(2);
    expect(onBegin).toHaveBeenNthCalledWith(2, 'primary');
  });

  it('the listen button plays the primary hello', () => {
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    render(<ChooserPage onBegin={vi.fn()} starting={false} />);
    const listen = screen.getAllByRole('button', { name: /Hör rösten\s*– Räven/ })[0];
    fireEvent.click(listen);
    expect(MockAudio.instances).toHaveLength(1);
    expect(MockAudio.instances[0].src).toContain('hello-primary.mp3');
  });

  it('leaving the front door stops the hello', async () => {
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
    const { unmount } = render(<ChooserPage onBegin={vi.fn()} starting={false} />);
    fireEvent.click(screen.getAllByRole('button', { name: /Hör rösten\s*– Räven/ })[0]);
    await waitFor(() => expect(MockAudio.instances.length).toBeGreaterThan(0));
    expect(MockAudio.instances[0].paused).toBe(false);
    unmount();
    expect(MockAudio.instances[0].paused).toBe(true);
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
    fireEvent.click(screen.getByRole('button', { name: 'Max · Linnea' }));
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

describe('ChooserPage mast', () => {
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
    const cta = screen.getAllByRole('button', { name: 'Prata med Räven' })[0];
    expect(link.compareDocumentPosition(cta) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('the band nav points at the other bands; the front door stays put', () => {
    const onNavigate = vi.fn();
    render(<ChooserPage onBegin={() => {}} starting={false} onNavigate={onNavigate} />);
    const nav = screen.getByRole('navigation', { name: 'Skolnivå' });
    expect(within(nav).getByRole('link', { name: 'Åk 1–6' }).getAttribute('href')).toBe('/');
    expect(within(nav).getByRole('link', { name: 'Högstadiet' }).getAttribute('href')).toBe('/hogstadiet');
    fireEvent.click(within(nav).getByRole('link', { name: 'Gymnasiet' }));
    expect(onNavigate).toHaveBeenCalledWith('upper');
    // Åk 1–6 is the page we are already on: no navigation.
    fireEvent.click(within(nav).getByRole('link', { name: 'Åk 1–6' }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });
});

describe('ChooserPage sections', () => {
  it('shows the primary steps and the planned price after them', () => {
    render(<ChooserPage onBegin={vi.fn()} starting={false} />);
    const steps = document.getElementById('sa-gar-det-till') as HTMLElement;
    expect(within(steps).getByText('Så går det till')).toBeDefined();
    expect(screen.getByRole('heading', { name: 'Så hjälper Talarum barnet framåt.' })).toBeDefined();
    expect(screen.getByRole('heading', { name: /Barnet löser själv/ })).toBeDefined();
    expect(screen.getAllByText('30 + 40 = 70').length).toBeGreaterThanOrEqual(1);
    const price = document.getElementById('pris') as HTMLElement;
    expect(steps.compareDocumentPosition(price) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(price).getByText('Gratis medan vi testar.')).toBeDefined();
    expect(within(price).getByText('0 kr')).toBeDefined();
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
      '<div class="tp-sec"><button class="tp-cta">Prata med Linnea</button></div>';
    expect(focusStartControl()).toBe(true);
    expect(document.activeElement?.textContent).toBe('Prata med Räven');
    document.body.innerHTML = '';
  });
  it('falls back to any start button and reports when missing', () => {
    document.body.innerHTML =
      '<div class="tp-sec"><button class="tp-cta">Prata med Linnea</button></div>';
    expect(focusStartControl()).toBe(true);
    expect(document.activeElement?.textContent).toBe('Prata med Linnea');
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

  it('going back is one button at the end, not a link at the top', () => {
    const onBack = vi.fn();
    render(<PrivacyPage onBack={onBack} />);
    expect(screen.queryByRole('link', { name: /Tillbaka/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Tillbaka till start' }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('the mast marks Integritet as current beside the band nav', () => {
    render(<PrivacyPage onBack={() => {}} />);
    const nav = screen.getByRole('navigation', { name: 'Skolnivå' });
    expect(within(nav).getByRole('link', { name: 'Åk 1–6' }).getAttribute('href')).toBe('/');
    expect(within(nav).getByRole('link', { name: 'Högstadiet' }).getAttribute('href')).toBe('/hogstadiet');
    const mast = document.querySelector('.tp-mast') as HTMLElement;
    expect(within(mast).getByRole('link', { name: 'Integritet' }).getAttribute('aria-current')).toBe('page');
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

describe('PrivacyPage honesty', () => {
  it('says the stored details travel with the call', () => {
    render(<PrivacyPage onBack={() => {}} />);
    expect(document.body.textContent).toContain('När ett samtal börjar skickas uppgifterna med');
  });
});
