import { useEffect } from 'react';

/**
 * Hold a screen wake lock while `active` (a live lesson) and the page is
 * visible. Feature-detected: browsers without the Screen Wake Lock API
 * (or that deny it) run the lesson unchanged. The lock only blocks
 * automatic dimming; the child can still lock manually or switch apps.
 */
export function useWakeLock(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    if (typeof document === 'undefined' || typeof navigator === 'undefined') return;
    const api = navigator.wakeLock;
    if (!api || typeof api.request !== 'function') return;

    let cancelled = false;
    let requestId = 0;
    let sentinel: WakeLockSentinel | null = null;

    const onRelease = () => {
      if (sentinel) {
        sentinel.removeEventListener('release', onRelease);
        sentinel = null;
      }
      // No re-request here. Re-acquisition happens on foreground return only,
      // so a system release (low battery, manual lock) never spins a retry loop.
    };

    const request = async () => {
      if (cancelled) return;
      if (document.visibilityState !== 'visible') return;
      const id = ++requestId;
      try {
        const next = await api.request('screen');
        if (cancelled || id !== requestId) {
          // Resolved after end/unmount or superseded: never hold it past the lesson.
          await next.release().catch(() => undefined);
          return;
        }
        // Replace any stale handle without leaking it.
        if (sentinel && sentinel !== next) {
          const stale = sentinel;
          sentinel = null;
          stale.removeEventListener('release', onRelease);
          await stale.release().catch(() => undefined);
        }
        sentinel = next;
        next.addEventListener('release', onRelease);
      } catch {
        // Unsupported, denied, or low battery: the lesson continues without it.
      }
    };

    const onVisibility = () => {
      if (document.visibilityState === 'visible') void request();
    };

    document.addEventListener('visibilitychange', onVisibility);
    void request();

    return () => {
      cancelled = true;
      requestId += 1;
      document.removeEventListener('visibilitychange', onVisibility);
      const held = sentinel;
      sentinel = null;
      if (held) {
        held.removeEventListener('release', onRelease);
        void held.release().catch(() => undefined);
      }
    };
  }, [active]);
}
