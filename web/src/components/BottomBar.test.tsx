import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import BottomBar from './BottomBar';

afterEach(() => cleanup());

function props(overrides: Partial<React.ComponentProps<typeof BottomBar>> = {}) {
  return {
    micEnabled: true,
    micBlocked: false,
    sending: false,
    ending: false,
    onSendText: vi.fn(),
    onToggleMic: vi.fn(),
    onAttach: vi.fn(),
    onEnd: vi.fn(),
    ...overrides,
  };
}

describe('BottomBar dock', () => {
  it('renders the dock with attach, text field, mic and Avsluta', () => {
    render(<BottomBar {...props()} />);
    expect(screen.getByRole('contentinfo', { name: 'Samtalskontroller' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Lägg till läxa — välj fil' })).toBeTruthy();
    expect(screen.getByPlaceholderText('Skriv här om du vill…')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Stäng av mikrofonen' })).toBeTruthy();
    const end = screen.getByRole('button', { name: 'Avsluta sessionen' });
    expect(end.textContent).toContain('Avsluta');
  });

  it('Avsluta in the dock ends the session', () => {
    const onEnd = vi.fn();
    render(<BottomBar {...props({ onEnd })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Avsluta sessionen' }));
    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it('locks Avsluta while the call is ending', () => {
    const onEnd = vi.fn();
    render(<BottomBar {...props({ ending: true, onEnd })} />);
    const end = screen.getByRole('button', { name: 'Avsluta sessionen' });
    expect((end as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(end);
    expect(onEnd).not.toHaveBeenCalled();
  });

  it('shows the mic state: live, muted, blocked', () => {
    const { rerender } = render(<BottomBar {...props({ micEnabled: true })} />);
    expect(screen.getByRole('button', { name: 'Stäng av mikrofonen' }).className).toContain('live');

    rerender(<BottomBar {...props({ micEnabled: false })} />);
    const muted = screen.getByRole('button', { name: 'Mikrofon av — sätt på mikrofonen' });
    expect(muted.className).toContain('muted');
    expect(muted.getAttribute('aria-pressed')).toBe('false');

    rerender(<BottomBar {...props({ micBlocked: true })} />);
    const blocked = screen.getByRole('button', { name: 'Mikrofon blockerad' });
    expect(blocked.className).toContain('blocked');
  });

  it('toggles the mic on click', () => {
    const onToggleMic = vi.fn();
    render(<BottomBar {...props({ onToggleMic })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Stäng av mikrofonen' }));
    expect(onToggleMic).toHaveBeenCalledTimes(1);
  });

  it('sends on Enter and clears the field', () => {
    const onSendText = vi.fn();
    render(<BottomBar {...props({ onSendText })} />);
    const input = screen.getByPlaceholderText('Skriv här om du vill…') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '  hej  ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSendText).toHaveBeenCalledWith('hej');
    expect(input.value).toBe('');
  });

  it('does not send empty text or while sending', () => {
    const onSendText = vi.fn();
    const { rerender } = render(<BottomBar {...props({ onSendText })} />);
    const input = screen.getByPlaceholderText('Skriv här om du vill…');
    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSendText).not.toHaveBeenCalled();

    rerender(<BottomBar {...props({ onSendText, sending: true })} />);
    fireEvent.change(screen.getByPlaceholderText('Skriv här om du vill…'), {
      target: { value: 'hej' },
    });
    fireEvent.keyDown(screen.getByPlaceholderText('Skriv här om du vill…'), { key: 'Enter' });
    expect(onSendText).not.toHaveBeenCalled();
  });

  it('offers the send button on mobile once there is a draft', () => {
    const onSendText = vi.fn();
    render(<BottomBar {...props({ onSendText, mobile: true })} />);
    expect(screen.queryByRole('button', { name: 'Skicka' })).toBeNull();
    fireEvent.change(screen.getByPlaceholderText('Skriv här om du vill…'), {
      target: { value: 'hej' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Skicka' }));
    expect(onSendText).toHaveBeenCalledWith('hej');
  });

  it('wires the attach button to the picker handler', () => {
    const onAttach = vi.fn();
    render(<BottomBar {...props({ onAttach })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Lägg till läxa — välj fil' }));
    expect(onAttach).toHaveBeenCalledTimes(1);
  });
});
