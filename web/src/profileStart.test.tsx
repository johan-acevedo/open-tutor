import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Profile } from './db';
import ProfilePicker from './components/ProfilePicker';

const { create } = vi.hoisted(() => ({ create: vi.fn() }));
vi.mock('./db', () => ({ createProfile: create }));
afterEach(() => cleanup());

it('unlocks audio before saving a new profile and accepts only one pending start', async () => {
  const events: string[] = [];
  let finish: (profile: Profile) => void = () => {};
  create.mockImplementation(() => {
    events.push('persist');
    return new Promise<Profile>((resolve) => { finish = resolve; });
  });
  const pick = vi.fn();
  render(<ProfilePicker profiles={[]} starting={false} onPick={pick} onStartGesture={() => events.push('unlock')} />);
  fireEvent.change(screen.getByLabelText('Förnamn'), { target: { value: 'Leo' } });
  const start = screen.getByRole('button', { name: 'Starta' });
  fireEvent.click(start);
  fireEvent.click(start);
  expect(events).toEqual(['unlock', 'persist']);
  finish({ id: 'fictional', name: 'Leo', grade: 4, notes: [], createdAt: 0 });
  await waitFor(() => expect(pick).toHaveBeenCalledTimes(1));
});
