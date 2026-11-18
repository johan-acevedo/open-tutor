import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { bandConfig } from './bands';
import type { Profile } from './db';
import Welcome from './components/Welcome';

const { create } = vi.hoisted(() => ({ create: vi.fn() }));
vi.mock('./db', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./db')>();
  return { ...actual, createProfile: create };
});
afterEach(() => cleanup());

function profile(over: Partial<Profile> = {}): Profile {
  return { id: 'p1', name: 'Elsa', grade: 4, notes: [], createdAt: 0, ...over };
}

it('first visit asks only for a first name, no grade picker', () => {
  render(<Welcome profiles={[]} band={bandConfig('primary')} onPick={() => {}} starting={false} />);
  expect(screen.getByRole('heading', { name: 'Vad heter du?' })).toBeDefined();
  expect(screen.queryByLabelText('Årskurs')).toBeNull();
  expect(screen.getByRole('button', { name: 'Starta' })).toHaveProperty('disabled', true);
  fireEvent.change(screen.getByLabelText('Förnamn'), { target: { value: 'Leo' } });
  expect(screen.getByRole('button', { name: 'Starta' })).toHaveProperty('disabled', false);
});

it('creates a profile with unknown grade and unlocks audio before persisting', async () => {
  const events: string[] = [];
  let finish: (profile: Profile) => void = () => {};
  create.mockImplementation(
    () =>
      new Promise<Profile>((resolve) => {
        finish = resolve;
      }),
  );
  const pick = vi.fn();
  render(
    <Welcome profiles={[]} band={bandConfig('primary')} onPick={pick} starting={false} onStartGesture={() => events.push('unlock')} />,
  );
  fireEvent.change(screen.getByLabelText('Förnamn'), { target: { value: 'Leo' } });
  const start = screen.getByRole('button', { name: 'Starta' });
  fireEvent.click(start);
  fireEvent.click(start);
  expect(events).toEqual(['unlock']);
  expect(create).toHaveBeenCalledWith('Leo');
  finish({ id: 'fictional', name: 'Leo', grade: null, notes: [], createdAt: 0 });
  await waitFor(() => expect(pick).toHaveBeenCalledTimes(1));
});

it('second visit assumes the same student with a short start', () => {
  const pick = vi.fn();
  render(
    <Welcome profiles={[profile()]} band={bandConfig('primary')} onPick={pick} starting={false} />,
  );
  fireEvent.click(screen.getByRole('button', { name: 'Hej Elsa, starta' }));
  expect(pick).toHaveBeenCalledWith(profile());
});

it('Byt elev lists stored students and adds a new one by name', async () => {
  const profiles = [profile(), profile({ id: 'p2', name: 'Leo', grade: null })];
  const pick = vi.fn();
  render(<Welcome profiles={profiles} band={bandConfig('primary')} onPick={pick} starting={false} />);
  fireEvent.click(screen.getByRole('button', { name: 'Byt elev' }));
  fireEvent.click(screen.getByRole('option', { name: /Elsa/ }));
  expect(pick).toHaveBeenCalledWith(profiles[0]);
});

it('the upper band switches the copy and keeps name-only start', () => {
  render(
    <Welcome profiles={[profile({ name: 'Bo', grade: null })]} band={bandConfig('upper')} onPick={() => {}} starting={false} />,
  );
  expect(screen.getByRole('button', { name: 'Hej Bo, starta' })).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Byt person' }));
  expect(screen.getByLabelText('Förnamn')).toBeDefined();
  expect(screen.queryByLabelText('Årskurs')).toBeNull();
});
