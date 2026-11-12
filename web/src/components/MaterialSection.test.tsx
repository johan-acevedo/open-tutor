import { describe, expect, it, vi, afterEach } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import MaterialSection from './MaterialSection';

const ITEM = {
  id: 'm1',
  kind: 'material',
  title: 'A simple circuit',
  section_id: 'sec-ecd16baf9e4fee44',
} as const;

const META = {
  attribution: 'Siyavula — Grade 6 Book — A simple circuit — CC-BY — siyavula.com',
};

function mockFetchOnce(body: unknown, ok = true, status = 200) {
  const fetchMock = vi.fn(async () => ({ ok, status, json: async () => body }) as Response);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('MaterialSection', () => {
  it('derives the page URL from the validated section ID and keeps the frame opaque', async () => {
    const fetchMock = mockFetchOnce(META);
    const onMounted = vi.fn();
    const onFailed = vi.fn();
    const { container } = render(<MaterialSection item={{ ...ITEM }} onMounted={onMounted} onFailed={onFailed} />);

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/materials/sections/sec-ecd16baf9e4fee44',
      expect.anything(),
    );
    expect(screen.getByRole('status').textContent).toMatch(/hämtar originalsidan/i);

    const frame = (await screen.findByTitle('A simple circuit')) as HTMLIFrameElement;
    expect(frame.tagName).toBe('IFRAME');
    expect(frame.getAttribute('src')).toBe('/materials/sections/sec-ecd16baf9e4fee44/index.html');
    // Opaque sandbox: empty token list, no allow-scripts / allow-same-origin.
    expect(frame.getAttribute('sandbox')).toBe('');
    expect(container.querySelector('iframe[allow]')).toBeNull();
    expect(screen.getByText(/Siyavula — Grade 6 Book/)).toBeTruthy();

    // Mount alone is not readiness: no acknowledgement before the frame loads.
    expect(onMounted).not.toHaveBeenCalled();
    fireEvent.load(frame);
    expect(onMounted).toHaveBeenCalledWith('m1');
    expect(onFailed).not.toHaveBeenCalled();
  });

  it('reports failure without acknowledgement when metadata is missing', async () => {
    mockFetchOnce({ detail: 'Unknown section ID' }, false, 404);
    const onMounted = vi.fn();
    const onFailed = vi.fn();
    render(<MaterialSection item={{ ...ITEM }} onMounted={onMounted} onFailed={onFailed} />);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/material 404/i);
    expect(onFailed).toHaveBeenCalledWith('m1', expect.stringMatching(/404/));
    expect(onMounted).not.toHaveBeenCalled();
    expect(screen.queryByTitle('A simple circuit')).toBeNull();

    // Retry re-issues the metadata request; a late success still mounts visibly.
    mockFetchOnce(META);
    fireEvent.click(screen.getByRole('button', { name: /försök igen/i }));
    const frame = (await screen.findByTitle('A simple circuit')) as HTMLIFrameElement;
    fireEvent.load(frame);
    await waitFor(() => expect(onMounted).toHaveBeenCalledWith('m1'));
  });

  it('never acknowledges a superseded section after a race', async () => {
    let resolveFirst!: (v: unknown) => void;
    const first = new Promise((resolve) => {
      resolveFirst = resolve;
    });
    const fetchMock = vi.fn((url: string) => {
      if (url.includes('sec-ecd16baf9e4fee44')) return first as Promise<Response>;
      return Promise.resolve({ ok: true, status: 200, json: async () => META } as Response);
    });
    vi.stubGlobal('fetch', fetchMock);
    const onMounted = vi.fn();
    const onFailed = vi.fn();
    const { rerender } = render(
      <MaterialSection item={{ ...ITEM }} onMounted={onMounted} onFailed={onFailed} />,
    );
    // Rapid replacement before the first metadata arrives.
    rerender(
      <MaterialSection
        item={{ ...ITEM, id: 'm2', section_id: 'sec-6a9c825e9c3f2cd2' }}
        onMounted={onMounted}
        onFailed={onFailed}
      />,
    );
    resolveFirst({ ok: true, status: 200, json: async () => META });
    const frame = (await screen.findByTitle('A simple circuit')) as HTMLIFrameElement;
    expect(frame.getAttribute('src')).toBe('/materials/sections/sec-6a9c825e9c3f2cd2/index.html');
    // The stale first response must not acknowledge the replaced item.
    expect(onMounted).not.toHaveBeenCalledWith('m1');
    fireEvent.load(frame);
    expect(onMounted).toHaveBeenCalledWith('m2');
  });

  it('stays silent when unmounted before the frame loads', async () => {
    mockFetchOnce(META);
    const onMounted = vi.fn();
    const onFailed = vi.fn();
    const { unmount } = render(
      <MaterialSection item={{ ...ITEM }} onMounted={onMounted} onFailed={onFailed} />,
    );
    await screen.findByTitle('A simple circuit');
    unmount();
    expect(onMounted).not.toHaveBeenCalled();
    expect(onFailed).not.toHaveBeenCalled();
  });

  it('reports a frame error instead of acknowledging', async () => {
    mockFetchOnce(META);
    const onMounted = vi.fn();
    const onFailed = vi.fn();
    render(<MaterialSection item={{ ...ITEM }} onMounted={onMounted} onFailed={onFailed} />);
    const frame = (await screen.findByTitle('A simple circuit')) as HTMLIFrameElement;
    frame.dispatchEvent(new Event('error'));
    expect(onFailed).toHaveBeenCalledWith('m1', expect.any(String));
    expect(onMounted).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
  });
});
