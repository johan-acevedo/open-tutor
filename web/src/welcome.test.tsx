import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { bandConfig } from './bands';
import { helloAudioUrl } from './bands';
import type { Profile } from './db';
import Welcome from './components/Welcome';
import { MockAudio } from './components/mockAudio';
import { preloadGreeting, resetGreetingForTests } from './components/greetingAudio';

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
  resetGreetingForTests();
});

function profile(over: Partial<Profile> = {}): Profile {
  return { id: 'p1', name: 'Elsa', grade: 4, notes: [], createdAt: 0, ...over };
}

it('first visit shows the listen control and one start button, no name field or grid', () => {
  render(<Welcome profiles={[]} band={bandConfig('primary')} onPick={() => {}} starting={false} />);
  // No visible bubble: the greeting lives in the listen button's name.
  expect(screen.getByRole('button', { name: /Hör rösten\s*– Räven/ })).toBeDefined();
  expect(screen.queryByText('Hej Elsa!')).toBeNull();
  expect(screen.getByRole('button', { name: 'Prata med Räven' })).toBeDefined();
  expect(screen.queryByRole('textbox')).toBeNull();
  expect(screen.queryByRole('listbox')).toBeNull();
});

it('starts nameless with a blank in-memory profile and unlocks audio first', () => {
  const order: string[] = [];
  const pick = vi.fn();
  render(
    <Welcome profiles={[]} band={bandConfig('primary')} onPick={(p: Profile) => { order.push('pick'); pick(p); }} starting={false} onStartGesture={() => order.push('unlock')} />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Prata med Räven' }));
  expect(order).toEqual(['unlock', 'pick']);
  expect(pick).toHaveBeenCalledTimes(1);
  const started = pick.mock.calls[0][0] as Profile;
  expect(started.name).toBe('');
  expect(started.grade).toBeNull();
  expect(started.id).toBeTruthy();
});

it('returning visit assumes the same student with the same button', () => {
  localStorage.setItem('open-tutor-last-profile', 'p1');
  const pick = vi.fn();
  render(
    <Welcome profiles={[profile()]} band={bandConfig('primary')} onPick={pick} starting={false} />,
  );
  expect(screen.getByText('Hej Elsa!')).toBeDefined();
  expect(screen.getByRole('button', { name: 'Prata med Räven' })).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Prata med Räven' }));
  expect(pick).toHaveBeenCalledWith(profile());
});

it('returning visit keeps the name and the not-you link in one paragraph', () => {
  localStorage.setItem('open-tutor-last-profile', 'p1');
  render(
    <Welcome profiles={[profile()]} band={bandConfig('primary')} onPick={() => {}} starting={false} />,
  );
  const hello = document.querySelector('p.tp-hello');
  expect(hello).not.toBeNull();
  expect(hello?.textContent).toContain('Hej Elsa!');
  const cta = screen.getByRole('button', { name: 'Prata med Räven' });
  const notYou = screen.getByRole('button', { name: 'Inte Elsa?' });
  // The greeting shares its paragraph with the not-you link; the start
  // button sits beside the listen control in the CTA row.
  expect(notYou.parentElement).toBe(hello);
  expect(cta.parentElement?.className).toContain('tp-cta-row');
});

it('the wrong-person link returns to the nameless first-visit page', () => {
  localStorage.setItem('open-tutor-last-profile', 'p1');
  const pick = vi.fn();
  render(
    <Welcome profiles={[profile()]} band={bandConfig('primary')} onPick={pick} starting={false} />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Inte Elsa?' }));
  expect(screen.getByRole('button', { name: /Hör rösten\s*– Räven/ })).toBeDefined();
  expect(screen.queryByText('Hej Elsa!')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Prata med Räven' }));
  expect(pick).toHaveBeenCalledTimes(1);
  expect((pick.mock.calls[0][0] as Profile).name).toBe('');
});

it('opens the nameless first visit directly when asked', () => {
  localStorage.setItem('open-tutor-last-profile', 'p1');
  render(
    <Welcome profiles={[profile()]} band={bandConfig('primary')} onPick={() => {}} starting={false} startOpen />,
  );
  expect(screen.getByRole('button', { name: /Hör rösten\s*– Räven/ })).toBeDefined();
  expect(screen.queryByText('Hej Elsa!')).toBeNull();
});

it('names the band companion on the start button', () => {
  render(
    <Welcome profiles={[]} band={bandConfig('middle')} onPick={() => {}} starting={false} />,
  );
  expect(screen.getByRole('button', { name: 'Prata med Linnea' })).toBeDefined();
  cleanup();
  render(
    <Welcome profiles={[]} band={bandConfig('upper')} onPick={() => {}} starting={false} />,
  );
  expect(screen.getByRole('button', { name: 'Prata med Björnen' })).toBeDefined();
});

it('prefills the assumed student after an in-call switch', () => {
  const profiles = [profile(), profile({ id: 'p2', name: 'Noa', grade: null })];
  const pick = vi.fn();
  // Last visit was Elsa, but the switch armed Noa: Noa is assumed.
  localStorage.setItem('open-tutor-last-profile', 'p1');
  render(
    <Welcome profiles={profiles} band={bandConfig('primary')} onPick={pick} starting={false} assumeId="p2" />,
  );
  expect(screen.getByText('Hej Noa!')).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Prata med Räven' }));
  expect(pick).toHaveBeenCalledWith(profiles[1]);
});

describe('listen control', () => {
  beforeEach(() => {
    resetGreetingForTests();
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
  });

  function listen(label: RegExp | string) {
    return screen.getByRole('button', { name: label });
  }

  it('is a button whose name is the visible label plus the hidden companion', () => {
    render(<Welcome profiles={[]} band={bandConfig('primary')} onPick={() => {}} starting={false} />);
    const b = listen(/Hör rösten\s*– Räven/);
    expect(b.getAttribute('aria-pressed')).toBe('false');
    expect(b.textContent).toContain('Hör rösten');
    expect(b.getAttribute('title')).toBe('Lyssna på Räven');
  });

  it('names the other companions on their bands', () => {
    render(<Welcome profiles={[]} band={bandConfig('middle')} onPick={() => {}} starting={false} />);
    expect(listen(/Hör rösten\s*– Linnea/)).toBeDefined();
    cleanup();
    render(<Welcome profiles={[]} band={bandConfig('upper')} onPick={() => {}} starting={false} />);
    expect(listen(/Hör rösten\s*– Björnen/)).toBeDefined();
  });

  it('plays the band greeting on tap, stops and rewinds on the next tap', async () => {
    render(<Welcome profiles={[]} band={bandConfig('primary')} onPick={() => {}} starting={false} />);
    const b = listen(/Hör rösten\s*– Räven/);
    expect(MockAudio.instances).toHaveLength(0);
    fireEvent.click(b);
    expect(MockAudio.instances).toHaveLength(1);
    expect(MockAudio.instances[0].src).toBe(helloAudioUrl('primary'));
    expect(MockAudio.instances[0].preload).toBe('auto');
    await waitFor(() => expect(b.getAttribute('aria-pressed')).toBe('true'));
    expect(b.textContent).toContain('Spelar…');
    MockAudio.instances[0].currentTime = 1.4;
    fireEvent.click(b);
    expect(MockAudio.instances[0].paused).toBe(true);
    expect(MockAudio.instances[0].currentTime).toBe(0);
    expect(b.getAttribute('aria-pressed')).toBe('false');
    expect(b.textContent).toContain('Hör rösten');
  });

  it('preloads on pointer/focus intent and reuses the clip on click without autoplaying', async () => {
    render(<Welcome profiles={[]} band={bandConfig('primary')} onPick={() => {}} starting={false} />);
    const b = listen(/Hör rösten\s*– Räven/);
    expect(MockAudio.instances).toHaveLength(0);
    fireEvent.pointerEnter(b);
    expect(MockAudio.instances).toHaveLength(1);
    expect(MockAudio.instances[0].paused).toBe(true);
    expect(MockAudio.instances[0].preload).toBe('auto');
    expect(MockAudio.instances[0].loadCalls).toBe(1);
    // Repeated intent events and the click itself reuse the same Audio element.
    fireEvent.focus(b);
    fireEvent.pointerDown(b);
    expect(MockAudio.instances).toHaveLength(1);
    expect(MockAudio.instances[0].loadCalls).toBe(1);
    fireEvent.click(b);
    expect(MockAudio.instances).toHaveLength(1);
    await waitFor(() => expect(b.getAttribute('aria-pressed')).toBe('true'));
    // Preloading another band while a clip is already playing must not interrupt it.
    preloadGreeting('middle');
    expect(MockAudio.instances).toHaveLength(1);
    expect(MockAudio.instances[0].paused).toBe(false);
    expect(b.getAttribute('aria-pressed')).toBe('true');
  });

  it('stops the clip when the call starts, keeping unlock before pick', async () => {
    const order: string[] = [];
    const pick = vi.fn();
    render(
      <Welcome profiles={[]} band={bandConfig('primary')} onPick={(p: Profile) => { order.push('pick'); pick(p); }} starting={false} onStartGesture={() => order.push('unlock')} />,
    );
    const b = listen(/Hör rösten\s*– Räven/);
    fireEvent.click(b);
    await waitFor(() => expect(b.getAttribute('aria-pressed')).toBe('true'));
    fireEvent.click(screen.getByRole('button', { name: 'Prata med Räven' }));
    expect(MockAudio.instances[0].paused).toBe(true);
    expect(b.getAttribute('aria-pressed')).toBe('false');
    expect(order).toEqual(['unlock', 'pick']);
    expect(pick).toHaveBeenCalledTimes(1);
  });

  it('its accessible name starts with the visible label', () => {
    render(<Welcome profiles={[]} band={bandConfig('primary')} onPick={() => {}} starting={false} />);
    const b = listen(/Hör rösten\s*– Räven/);
    const visible = b.querySelector('.tp-listen-label')?.textContent ?? '';
    expect(visible).toContain('Hör rösten');
    expect(screen.getByRole('button', { name: /Hör rösten\s*– Räven/ })).toBe(b);
  });

  it('stops the clip when the band changes or the page unmounts', async () => {
    const { rerender, unmount } = render(
      <Welcome profiles={[]} band={bandConfig('primary')} onPick={() => {}} starting={false} />,
    );
    fireEvent.click(listen(/Hör rösten\s*– Räven/));
    await waitFor(() => expect(MockAudio.instances[0].paused).toBe(false));
    rerender(<Welcome profiles={[]} band={bandConfig('middle')} onPick={() => {}} starting={false} />);
    expect(MockAudio.instances[0].paused).toBe(true);
    expect(listen(/Hör rösten\s*– Linnea/).getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(listen(/Hör rösten\s*– Linnea/));
    await waitFor(() => expect(MockAudio.instances.at(-1)!.paused).toBe(false));
    unmount();
    expect(MockAudio.instances.at(-1)!.paused).toBe(true);
  });

  it('ignores a late error from a clip it already switched away from', async () => {
    const { rerender } = render(
      <Welcome profiles={[]} band={bandConfig('primary')} onPick={() => {}} starting={false} />,
    );
    fireEvent.click(listen(/Hör rösten\s*– Räven/));
    await waitFor(() => expect(MockAudio.instances.length).toBe(1));
    rerender(<Welcome profiles={[]} band={bandConfig('middle')} onPick={() => {}} starting={false} />);
    const lynxListen = listen(/Hör rösten\s*– Linnea/);
    fireEvent.click(lynxListen);
    await waitFor(() => expect(lynxListen.getAttribute('aria-pressed')).toBe('true'));
    // The Räven clip fails late (a 404 arriving after the switch).
    act(() => MockAudio.instances[0].emit('error'));
    expect(lynxListen.getAttribute('aria-pressed')).toBe('true');
  });
});
