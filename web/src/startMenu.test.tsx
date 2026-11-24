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
  fireEvent.click(screen.getByRole('button', { name: 'Om Open Tutor' }));
  expect(screen.getByLabelText('Om Open Tutor')).toBeDefined();
  fireEvent.click(screen.getByRole('button', { name: 'Integritet' }));
  expect(screen.getByLabelText('Integritet')).toBeDefined();
});

it('supports a lifted panel state opened from outside', () => {
  const onPanelChange = vi.fn();
  const { rerender } = render(
    <StartMenu switchLabel="Byt elev" onSwitch={() => {}} open panel={null} onPanelChange={onPanelChange} />,
  );
  expect(screen.queryByLabelText('Om Open Tutor')).toBeNull();
  rerender(
    <StartMenu switchLabel="Byt elev" onSwitch={() => {}} open panel="privacy" onPanelChange={onPanelChange} />,
  );
  expect(screen.getByLabelText('Integritet')).toBeDefined();
});
