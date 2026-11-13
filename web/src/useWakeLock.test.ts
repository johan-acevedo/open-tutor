import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, renderHook } from '@testing-library/react';
import { useWakeLock } from './useWakeLock';

interface FakeSentinel extends EventTarget {
  released: boolean;
  release: () => Promise<void>;
}

function fakeSentinel(): FakeSentinel {
  const target = new EventTarget() as FakeSentinel;
  target.released = false;
  target.release = vi.fn(async () => {
    target.released = true;
    target.dispatchEvent(new Event('release'));
  });
  return target;
}

function mockWakeLock(impl: (type: string) => Promise<FakeSentinel>) {
  const request = vi.fn(impl);
  Object.defineProperty(window.navigator, 'wakeLock', {
    configurable: true,
    writable: true,
    value: { request },
  });
  return request;
}

function mockVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => state,
  });
}

function fireVisibility() {
  act(() => {
    document.dispatchEvent(new Event('visibilitychange'));
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  mockVisibility('visible');
});

describe('useWakeLock', () => {
  it('requests on live and releases on unmount', async () => {
    const held: FakeSentinel[] = [];
    const request = mockWakeLock(async () => {
      const s = fakeSentinel();
      held.push(s);
      return s;
    });
    mockVisibility('visible');

    const { unmount } = renderHook(({ active }: { active: boolean }) => useWakeLock(active), {
      initialProps: { active: true },
    });
    await act(async () => undefined);
    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith('screen');

    unmount();
    await act(async () => undefined);
    expect(held).toHaveLength(1);
    expect(held[0].release).toHaveBeenCalledTimes(1);
  });

  it('releases when the lesson ends', async () => {
    const held: FakeSentinel[] = [];
    mockWakeLock(async () => {
      const s = fakeSentinel();
      held.push(s);
      return s;
    });
    mockVisibility('visible');

    const { rerender } = renderHook(({ active }: { active: boolean }) => useWakeLock(active), {
      initialProps: { active: true },
    });
    await act(async () => undefined);
    expect(held).toHaveLength(1);

    rerender({ active: false });
    await act(async () => undefined);
    expect(held[0].release).toHaveBeenCalledTimes(1);
  });

  it('does nothing without the API and survives a denied request', async () => {
    Object.defineProperty(window.navigator, 'wakeLock', {
      configurable: true,
      writable: true,
      value: undefined,
    });
    mockVisibility('visible');
    const { unmount } = renderHook(({ active }: { active: boolean }) => useWakeLock(active), {
      initialProps: { active: true },
    });
    await act(async () => undefined);
    unmount();

    const request = mockWakeLock(async () => {
      throw new DOMException('denied', 'NotAllowedError');
    });
    const { unmount: unmountDenied } = renderHook(
      ({ active }: { active: boolean }) => useWakeLock(active),
      { initialProps: { active: true } },
    );
    await act(async () => undefined);
    expect(request).toHaveBeenCalledTimes(1);
    unmountDenied();
  });

  it('re-requests after a background/foreground cycle', async () => {
    const held: FakeSentinel[] = [];
    const request = mockWakeLock(async () => {
      const s = fakeSentinel();
      held.push(s);
      return s;
    });
    mockVisibility('visible');
    renderHook(({ active }: { active: boolean }) => useWakeLock(active), {
      initialProps: { active: true },
    });
    await act(async () => undefined);
    expect(request).toHaveBeenCalledTimes(1);

    // The browser releases the lock when hidden; the sentinel tells us.
    mockVisibility('hidden');
    act(() => {
      held[0].dispatchEvent(new Event('release'));
    });
    fireVisibility();
    await act(async () => undefined);
    expect(request).toHaveBeenCalledTimes(1);

    mockVisibility('visible');
    fireVisibility();
    await act(async () => undefined);
    expect(request).toHaveBeenCalledTimes(2);
  });

  it('releases a request that resolves after the lesson ended', async () => {
    let resolveRequest!: (s: FakeSentinel) => void;
    const pending = new Promise<FakeSentinel>((resolve) => {
      resolveRequest = resolve;
    });
    mockWakeLock(() => pending);
    mockVisibility('visible');

    const { unmount } = renderHook(({ active }: { active: boolean }) => useWakeLock(active), {
      initialProps: { active: true },
    });
    await act(async () => undefined);
    unmount();

    const late = fakeSentinel();
    await act(async () => {
      resolveRequest(late);
      await pending;
    });
    expect(late.release).toHaveBeenCalledTimes(1);
  });

  it('releases a replacement on end even if the old lock releases slowly', async () => {
    let finishRelease: () => void = () => undefined;
    const releasing = new Promise<void>((resolve) => { finishRelease = resolve; });
    const old = fakeSentinel();
    old.release = vi.fn(() => releasing);
    const replacement = fakeSentinel();
    const request = mockWakeLock(async () => old);
    request.mockResolvedValueOnce(old).mockResolvedValueOnce(replacement);
    mockVisibility('visible');
    const { unmount } = renderHook(() => useWakeLock(true));
    await act(async () => undefined);

    // Foreground can precede delivery of the old sentinel's release event.
    mockVisibility('hidden');
    fireVisibility();
    mockVisibility('visible');
    fireVisibility();
    await act(async () => undefined);
    expect(old.release).toHaveBeenCalledTimes(1);
    unmount();
    await act(async () => {
      finishRelease();
      await releasing;
    });
    expect(replacement.release).toHaveBeenCalledTimes(1);
  });
});
