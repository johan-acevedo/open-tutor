import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import StartMenu from './components/StartMenu';

afterEach(() => cleanup());

it('shows the switch entry plus about and privacy behind the hamburger', () => {
  const onSwitch = vi.fn();
  render(<StartMenu switchLabel="Byt elev" onSwitch={onSwitch} />);
  expect(screen.queryByRole('button', { name: 'Byt elev' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Meny' }));
  fireEvent.click(screen.getByRole('button', { name: 'Byt elev' }));
  expect(onSwitch).toHaveBeenCalledTimes(1);
});

it('uses the upper band switch label', () => {
  render(<StartMenu switchLabel="Byt person" onSwitch={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: 'Meny' }));
  expect(screen.getByRole('button', { name: 'Byt person' })).toBeDefined();
});

it('opens the about and privacy notes', () => {
  render(<StartMenu switchLabel="Byt elev" onSwitch={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: 'Meny' }));
  fireEvent.click(screen.getByRole('button', { name: 'Om tjänsten' }));
  expect(screen.getByLabelText('Om tjänsten')).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Integritet' }));
  expect(screen.getByLabelText('Integritet')).toBeDefined();
});
