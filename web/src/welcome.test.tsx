import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { bandConfig } from './bands';
import { helloAudioUrl } from './bands';
import type { Profile } from './db';
import Welcome from './components/Welcome';
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

it('first visit shows the bubble and one start button, no name field or grid', () => {
  render(<Welcome profiles={[]} band={bandConfig('primary')} onPick={() => {}} starting={false} />);
  expect(screen.getByText('Hej!')).toBeDefined();
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

it('returning visit keeps the not-you link on the same row as the button', () => {
  localStorage.setItem('open-tutor-last-profile', 'p1');
  render(
    <Welcome profiles={[profile()]} band={bandConfig('primary')} onPick={() => {}} starting={false} />,
  );
  const cta = screen.getByRole('button', { name: 'Prata med Räven' });
  const notYou = screen.getByRole('button', { name: 'Inte Elsa?' });
  expect(cta.parentElement).toBe(notYou.parentElement);
  expect(cta.parentElement?.className).toContain('ot-land-cta-row');
});

it('the wrong-person link returns to the nameless first-visit page', () => {
  localStorage.setItem('open-tutor-last-profile', 'p1');
  const pick = vi.fn();
  render(
    <Welcome profiles={[profile()]} band={bandConfig('primary')} onPick={pick} starting={false} />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Inte Elsa?' }));
  expect(screen.getByText('Hej!')).toBeDefined();
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
  expect(screen.getByText('Hej!')).toBeDefined();
  expect(screen.queryByText('Hej Elsa!')).toBeNull();
});

it('names the band companion on the start button', () => {
  render(
    <Welcome profiles={[]} band={bandConfig('middle')} onPick={() => {}} starting={false} />,
  );
  expect(screen.getByRole('button', { name: 'Prata med Lodjuret' })).toBeDefined();
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

describe('greeting bubble', () => {
  beforeEach(() => {
    resetGreetingForTests();
    MockAudio.instances = [];
    vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
  });

  function bubble(label: RegExp | string) {
    return screen.getByRole('button', { name: label });
  }

  it('is a button that names the companion', () => {
    render(<Welcome profiles={[]} band={bandConfig('primary')} onPick={() => {}} starting={false} />);
    const b = bubble('Lyssna på Räven');
    expect(b.getAttribute('aria-pressed')).toBe('false');
    expect(b.textContent).toContain('Hej!');
  });

  it('names the other companions on their bands', () => {
    render(<Welcome profiles={[]} band={bandConfig('middle')} onPick={() => {}} starting={false} />);
    expect(bubble('Lyssna på Lodjuret')).toBeDefined();
    cleanup();
    render(<Welcome profiles={[]} band={bandConfig('upper')} onPick={() => {}} starting={false} />);
    expect(bubble('Lyssna på Björnen')).toBeDefined();
  });

  it('plays the band greeting on tap, stops on the next tap', async () => {
    render(<Welcome profiles={[]} band={bandConfig('primary')} onPick={() => {}} starting={false} />);
    const b = bubble('Lyssna på Räven');
    expect(MockAudio.instances).toHaveLength(0);
    fireEvent.click(b);
    expect(MockAudio.instances).toHaveLength(1);
    expect(MockAudio.instances[0].src).toBe(helloAudioUrl('primary'));
    await waitFor(() => expect(b.getAttribute('aria-pressed')).toBe('true'));
    fireEvent.click(b);
    expect(MockAudio.instances[0].paused).toBe(true);
    expect(b.getAttribute('aria-pressed')).toBe('false');
  });

  it('stops the clip when the call starts, keeping unlock before pick', async () => {
    const order: string[] = [];
    const pick = vi.fn();
    render(
      <Welcome profiles={[]} band={bandConfig('primary')} onPick={(p: Profile) => { order.push('pick'); pick(p); }} starting={false} onStartGesture={() => order.push('unlock')} />,
    );
    const b = bubble('Lyssna på Räven');
    fireEvent.click(b);
    await waitFor(() => expect(b.getAttribute('aria-pressed')).toBe('true'));
    fireEvent.click(screen.getByRole('button', { name: 'Prata med Räven' }));
    expect(MockAudio.instances[0].paused).toBe(true);
    expect(b.getAttribute('aria-pressed')).toBe('false');
    expect(order).toEqual(['unlock', 'pick']);
    expect(pick).toHaveBeenCalledTimes(1);
  });
});
