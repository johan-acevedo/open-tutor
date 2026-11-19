import { expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import TopMenu from './TopMenu';

it('offers the student switch behind the menu and calls it', () => {
  const onSwitchStudent = vi.fn();
  render(
    <TopMenu items={[]} dragOver={false} onCamera={() => {}} onFiles={() => {}} onSwitchStudent={onSwitchStudent} switchLabel="Byt elev" />,
  );
  // Closed menu shows no leave action.
  expect(screen.queryByRole('button', { name: 'Byt elev' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Meny' }));
  fireEvent.click(screen.getByRole('button', { name: 'Byt elev' }));
  expect(onSwitchStudent).toHaveBeenCalledTimes(1);
  cleanup();
});

it('hides the switch when no handler is given', () => {
  render(<TopMenu items={[]} dragOver={false} onCamera={() => {}} onFiles={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: 'Meny' }));
  expect(screen.queryByRole('button', { name: 'Byt elev' })).toBeNull();
  cleanup();
});
