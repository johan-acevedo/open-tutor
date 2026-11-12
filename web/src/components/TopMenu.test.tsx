import { describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach } from 'vitest';
import TopMenu from './TopMenu';
import type { RuntimeInfo } from '../runtimeInfo';

afterEach(() => cleanup());

const noop = vi.fn();

function openMenu(runtime: RuntimeInfo | null) {
  const shown = render(<TopMenu items={[]} dragOver={false} runtime={runtime} onCamera={noop} onFiles={noop} />);
  fireEvent.click(shown.getByRole('button', { name: 'Meny' }));
  fireEvent.click(shown.getByRole('button', { name: 'Sessionsinfo' }));
  return shown;
}

const workerRuntime: RuntimeInfo = {
  version: 1,
  sections: [
    {
      title: 'Språkmodell',
      fields: [{ label: 'Modell', value: 'muse-spark-1.3-contributor' }],
    },
  ],
};

describe('TopMenu sessionsinfo', () => {
  it('shows a pending message until worker metadata arrives', () => {
    const shown = openMenu(null);
    expect(shown.getByText(/väntar på sessionsinfo/i)).toBeTruthy();
    expect(shown.queryByText('muse-spark-1.3-contributor')).toBeNull();
  });

  it('shows worker sections and appends the browser Screen section', () => {
    const shown = openMenu(workerRuntime);
    expect(shown.queryByText(/väntar på sessionsinfo/i)).toBeNull();
    expect(shown.getByText('muse-spark-1.3-contributor')).toBeTruthy();
    expect(shown.getByText('Skärm (webbläsare)')).toBeTruthy();
    expect(shown.getByText('deepseek-v4.1-flash')).toBeTruthy();
  });

  it('expands and collapses accessibly', () => {
    const shown = openMenu(null);
    const toggle = shown.getByRole('button', { name: 'Sessionsinfo' });
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(shown.queryByText(/väntar på sessionsinfo/i)).toBeNull();
  });

  it('keeps the rest of the menu working', () => {
    const shown = openMenu(workerRuntime);
    expect(shown.getByText(/inkorg/i)).toBeTruthy();
    expect(shown.getByRole('button', { name: 'Fota läxan' })).toBeTruthy();
    expect(shown.getByRole('button', { name: 'Om Open Tutor' })).toBeTruthy();
  });
});
