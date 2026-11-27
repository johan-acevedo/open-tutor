import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import App from './App';
import { resetGreetingForTests } from './components/greetingAudio';
import { saveProfile } from './db';
import type { Profile } from './db';

// App-level flows with the LiveKit session behind a controlled mock: the
// hook returns the fields App reads, and each test drives route, storage
// and profiles like the browser would.
const sessionMock = vi.hoisted(() => ({ useSession: vi.fn() }));
vi.mock('./useSession', () => ({
  useSession: (...args: unknown[]) => sessionMock.useSession(...args),
}));

function baseSession(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    phase: 'profiles',
    profile: null,
    items: [],
    activeItemId: null,
    boardSignal: 0,
    homeworkDraft: null,
    homeworkSending: false,
    queueFiles: vi.fn(),
    setHomeworkDraft: vi.fn(),
    sendHomework: vi.fn(),
    audioBlocked: false,
    resumeNeeded: false,
    resumeMedia: vi.fn(),
    prepareStart: vi.fn(),
    focused: null,
    sessionNotes: [],
    caption: '',
    captionFading: false,
    agentState: null,
    tutorMode: null,
    hasSpokenFirst: false,
    micEnabled: false,
    micBlocked: false,
    connBanner: null,
    toast: null,
    lastSent: null,
    dragOver: false,
    sending: false,
    audioRef: { current: null },
    start: vi.fn(async () => {}),
    sendChat: vi.fn(),
    toggleMic: vi.fn(),
    retryMic: vi.fn(),
    resourceClosed: vi.fn(),
    endSession: vi.fn(),
    backToProfiles: vi.fn(),
    leaveToProfiles: vi.fn(),
    showFirstVisit: vi.fn(),
    profilesOpen: false,
    clearProfilesOpen: vi.fn(),
    clearPrefill: vi.fn(),
    prefillId: null,
    endReason: null,
    addFiles: vi.fn(),
    addText: vi.fn(),
    onItemMounted: vi.fn(),
    registerPageFrame: vi.fn(),
    sendPageAnswer: vi.fn(),
    onItemFailed: vi.fn(),
    ...over,
  };
}

function stored(over: Partial<Profile> & { id: string }): Profile {
  return {
    name: '',
    grade: null,
    notes: [],
    createdAt: Date.now(),
    ...over,
  };
}

beforeEach(() => {
  vi.stubGlobal(
    'matchMedia',
    (query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  );
  if (typeof window.requestAnimationFrame !== 'function') {
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) =>
      window.setTimeout(() => cb(performance.now()), 16),
    );
    vi.stubGlobal('cancelAnimationFrame', (id: number) => window.clearTimeout(id));
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, json: async () => ({}) })),
  );
  window.history.replaceState(null, '', '/');
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  window.history.replaceState(null, '', '/');
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  resetGreetingForTests();
});

describe('household picker with a legacy profile (no band)', () => {
  it('greets and starts the picked profile, not the remembered one', async () => {
    await saveProfile(stored({ id: 't1-old', name: 'Alva', grade: 4, band: 'primary', createdAt: 1 }));
    // Saved before Profile.band existed: no band to show or remember under.
    await saveProfile(stored({ id: 't1-leg', name: 'Noa', createdAt: 2 }));
    localStorage.setItem('open-tutor-last-profile', 't1-old');
    localStorage.setItem('open-tutor-last-profile:primary', 't1-old');
    window.history.replaceState(null, '', '/ak1-6');
    const start = vi.fn(async (_p: Profile, _b: string) => {});
    sessionMock.useSession.mockReturnValue(baseSession({ start }));
    render(<App />);
    await waitFor(() => expect(screen.getByText('Hej Alva!')).toBeDefined());

    fireEvent.click(screen.getByRole('button', { name: 'Inte Alva?' }));
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Vem ska prata?' })).toBeDefined());
    fireEvent.click(screen.getByRole('button', { name: 'Noa' }));

    // The picked profile drives the greeting: the previously remembered
    // learner must not leak into the start view.
    await waitFor(() => expect(screen.getByText('Hej Noa!')).toBeDefined());

    const ctas = screen.getAllByRole('button', { name: 'Prata med Räven' });
    fireEvent.click(ctas[ctas.length - 1]);
    await waitFor(() => expect(start).toHaveBeenCalledTimes(1));
    expect(start.mock.calls[0][0]).toMatchObject({ id: 't1-leg', name: 'Noa' });
    // The legacy profile starts in the current band, so the start request
    // and the greeting agree (the stamp lands when the call starts).
    expect(start.mock.calls[0][1]).toBe('primary');
  });
});

describe('pending in-call-switch prefill on /', () => {
  it('shows the prefilled learner start view instead of the chooser', async () => {
    await saveProfile(stored({ id: 't2-b', name: 'Bo', createdAt: 3 }));
    window.history.replaceState(null, '', '/');
    sessionMock.useSession.mockReturnValue(baseSession({ prefillId: 't2-b' }));
    render(<App />);
    await waitFor(() => expect(screen.getByText('Hej Bo!')).toBeDefined());
    // The generic three-card chooser would drop the prefill.
    expect(screen.queryByRole('button', { name: 'Prata med Lodjuret' })).toBeNull();
    expect(screen.getAllByRole('button', { name: 'Prata med Räven' }).length).toBeGreaterThan(0);
  });

  it('redirects the prefill to its band, but an explicit navigation wins and clears it', async () => {
    await saveProfile(stored({ id: 't5-b', name: 'Bea', band: 'middle', createdAt: 5 }));
    window.history.replaceState(null, '', '/');
    // Like the real hook: clearing the prefill is visible on the next render.
    let prefill: string | null = 't5-b';
    const clearPrefill = vi.fn(() => {
      prefill = null;
    });
    sessionMock.useSession.mockImplementation(() => baseSession({ prefillId: prefill, clearPrefill }));
    render(<App />);

    // The prefill redirect takes the page to the prefilled learner's band…
    await waitFor(() => expect(window.location.pathname).toBe('/hogstadiet'));
    expect(clearPrefill).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByText('Hej Bea!')).toBeDefined());

    // …but the user tapping another band's quiet link wins: the prefill is
    // cleared, so the page is not yanked back.
    fireEvent.click(screen.getByRole('link', { name: /Läxhjälp med Räven/ }));
    await waitFor(() => expect(clearPrefill).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(window.location.pathname).toBe('/ak1-6'));
    expect(window.location.pathname).toBe('/ak1-6');
  });
});

describe('band during a call', () => {
  it('keeps the call band when Back is pressed while connecting', async () => {
    window.history.replaceState(null, '', '/ak1-6');
    sessionMock.useSession.mockReturnValue(
      baseSession({
        phase: 'connecting',
        profile: stored({ id: 't3-a', name: 'Alva', grade: 4, band: 'primary', createdAt: 1 }),
      }),
    );
    render(<App />);
    expect(document.querySelector('.ot-root')?.getAttribute('data-band')).toBe('primary');

    window.history.pushState(null, '', '/hogstadiet');
    fireEvent(window, new PopStateEvent('popstate'));
    await waitFor(() => expect(window.location.pathname).toBe('/hogstadiet'));
    // The session request already went out for primary: the theme must not
    // follow the popped URL under the connecting screen.
    expect(document.querySelector('.ot-root')?.getAttribute('data-band')).toBe('primary');
    expect(screen.getByText(/Ansluter/)).toBeDefined();
  });
});

describe('cross-band links', () => {
  it('navigates to exactly the href path+query, dropping ?band=', async () => {
    // A remembered middle-band learner: / shows their middle start page.
    await saveProfile(stored({ id: 't4-m', name: 'Mio', grade: 7, band: 'middle', createdAt: 4 }));
    localStorage.setItem('open-tutor-last-profile', 't4-m');
    window.history.replaceState(null, '', '/?band=middle');
    sessionMock.useSession.mockReturnValue(baseSession({}));
    render(<App />);
    await waitFor(() =>
      expect(document.querySelector('.ot-root')?.getAttribute('data-band')).toBe('middle'),
    );
    fireEvent.click(screen.getByRole('link', { name: /Läxhjälp med Räven/ }));
    await waitFor(() => expect(window.location.pathname).toBe('/ak1-6'));
    expect(window.location.search).toBe('');
    expect(document.querySelector('.ot-root')?.getAttribute('data-band')).toBe('primary');
  });
});

describe('household picker Back', () => {
  it('moves focus to the start control instead of dropping it to <body>', async () => {
    await saveProfile(stored({ id: 't6-old', name: 'Alva', grade: 4, band: 'primary', createdAt: 6 }));
    localStorage.setItem('open-tutor-last-profile', 't6-old');
    localStorage.setItem('open-tutor-last-profile:primary', 't6-old');
    window.history.replaceState(null, '', '/ak1-6');
    sessionMock.useSession.mockReturnValue(baseSession({}));
    render(<App />);
    await waitFor(() => expect(screen.getByText('Hej Alva!')).toBeDefined());

    const notYou = screen.getByRole('button', { name: 'Inte Alva?' });
    notYou.focus();
    fireEvent.click(notYou);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Vem ska prata?' })).toBeDefined());
    expect(document.activeElement?.textContent).toBe('Vem ska prata?');

    fireEvent.click(screen.getByRole('button', { name: /Tillbaka/ }));
    await waitFor(() => expect(screen.getByText('Hej Alva!')).toBeDefined());
    // The opener is gone with the old view: the new start view's start
    // control takes focus, never <body>.
    expect(document.activeElement?.textContent).toContain('Prata med Räven');
    expect(document.activeElement?.className).toContain('tp-cta');
  });
});

describe('final review edges', () => {
  it('follows the URL band again when a connecting call falls back to the start page', async () => {
    window.history.replaceState(null, '', '/ak1-6');
    let phase = 'connecting';
    sessionMock.useSession.mockImplementation(() =>
      baseSession({ phase, profile: stored({ id: 'e1', name: 'Alva', band: 'primary', createdAt: 1 }) }),
    );
    const view = render(<App />);
    window.history.pushState(null, '', '/hogstadiet');
    fireEvent(window, new PopStateEvent('popstate'));
    await waitFor(() => expect(window.location.pathname).toBe('/hogstadiet'));
    expect(document.querySelector('.ot-root')?.getAttribute('data-band')).toBe('primary');
    // The start request failed: back on the start page under /hogstadiet.
    phase = 'profiles';
    view.rerender(<App />);
    await waitFor(() =>
      expect(document.querySelector('.ot-root')?.getAttribute('data-band')).toBe('middle'),
    );
  });

  it('does not assume a learner on a band page once their profile belongs to another band', async () => {
    await saveProfile(stored({ id: 'e2', name: 'Noa', band: 'middle', createdAt: 2 }));
    // Picked here as a legacy profile earlier, then their first call ran in middle.
    localStorage.setItem('open-tutor-last-profile:primary', 'e2');
    window.history.replaceState(null, '', '/ak1-6');
    sessionMock.useSession.mockReturnValue(baseSession({}));
    render(<App />);
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Prata med Räven' }).length).toBeGreaterThan(0));
    expect(screen.queryByText('Hej Noa!')).toBeNull();
  });

  it('keeps a pending switch prefill when Back is pressed during the call', async () => {
    window.history.replaceState(null, '', '/ak1-6');
    const clearPrefill = vi.fn();
    sessionMock.useSession.mockReturnValue(
      baseSession({ phase: 'live', clearPrefill, profile: stored({ id: 'e3', name: 'Alva', band: 'primary', createdAt: 3 }) }),
    );
    render(<App />);
    window.history.pushState(null, '', '/');
    fireEvent(window, new PopStateEvent('popstate'));
    await waitFor(() => expect(window.location.pathname).toBe('/'));
    expect(clearPrefill).not.toHaveBeenCalled();
  });

  it('keeps unrelated query parameters on a cross-band click', async () => {
    window.history.replaceState(null, '', '/hogstadiet?kampanj=x&band=middle');
    sessionMock.useSession.mockReturnValue(baseSession({}));
    render(<App />);
    fireEvent.click(await screen.findByRole('link', { name: /Läxhjälp med Räven/ }));
    await waitFor(() => expect(window.location.pathname).toBe('/ak1-6'));
    expect(window.location.search).toBe('?kampanj=x');
  });
});
