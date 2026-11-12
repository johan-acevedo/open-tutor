import { useEffect, useRef, useState } from 'react';
import type { BoardItem } from '../protocol';

export type MaterialItem = Extract<BoardItem, { kind: 'material' }>;

type Props = {
  item: MaterialItem;
  onMounted: (id: string) => void;
  onFailed: (id: string, message: string) => void;
};

type Status =
  | { phase: 'loading' }
  | { phase: 'ready'; attribution: string }
  | { phase: 'error'; message: string };

const FALLBACK_HEIGHT = 480;
const MIN_HEIGHT = 320;

/** Measure the visible board scroll surface this card sits in. */
function availHeight(wrap: HTMLElement | null): number | null {
  const scroller = wrap?.closest<HTMLElement>('.ot-board-scroll');
  if (!scroller) return null;
  const style = window.getComputedStyle(scroller);
  const padY = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
  const h = scroller.clientHeight - padY;
  return h >= 1 ? h : null;
}

function parseAttribution(raw: unknown): string | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const attribution = (raw as Record<string, unknown>).attribution;
  return typeof attribution === 'string' && attribution ? attribution : null;
}

/**
 * Original book section beside the fox: metadata first, then the packaged
 * page in a fully opaque frame (`sandbox=""` — no scripts, no same-origin).
 *
 * Readiness: `onMounted` fires only after metadata parses AND the frame's
 * `load` event fires for the current section. `onLoad` proves the top-level
 * document loaded — it says nothing about whether every image or stylesheet
 * inside finished, so image completeness is never claimed from it. Metadata
 * failure, frame error, unmount, or a superseding section reports `onFailed`
 * (or stays silent when superseded) so the RPC acknowledgement never claims
 * a section is visible when it is not.
 */
export default function MaterialSection({ item, onMounted, onFailed }: Props) {
  const sectionId = item.section_id;
  const pageUrl = `/materials/sections/${encodeURIComponent(sectionId)}/index.html`;
  const metaUrl = `/api/materials/sections/${encodeURIComponent(sectionId)}`;
  const [status, setStatus] = useState<Status>({ phase: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [frameH, setFrameH] = useState(FALLBACK_HEIGHT);
  const wrapRef = useRef<HTMLElement | null>(null);
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const seqRef = useRef(0);
  const liveRef = useRef(true);
  const failedRef = useRef(false);

  useEffect(() => {
    liveRef.current = true;
    return () => {
      liveRef.current = false;
    };
  }, []);

  // Responsive sizing: fill the available board surface height.
  useEffect(() => {
    const compute = () => {
      const h = availHeight(wrapRef.current);
      setFrameH(h == null ? FALLBACK_HEIGHT : Math.max(MIN_HEIGHT, Math.floor(h)));
    };
    compute();
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      const scroller = wrapRef.current?.closest('.ot-board-scroll');
      if (scroller) {
        ro = new ResizeObserver(compute);
        ro.observe(scroller);
      }
    }
    window.addEventListener('resize', compute);
    window.addEventListener('orientationchange', compute);
    return () => {
      ro?.disconnect();
      window.removeEventListener('resize', compute);
      window.removeEventListener('orientationchange', compute);
    };
  }, []);

  // Frame-level failure (jsdom and some browsers never route iframe errors
  // through React's onError, so this listens imperatively). A failed frame
  // rejects the acknowledgement; it never resolves it.
  useEffect(() => {
    if (status.phase !== 'ready') return;
    const el = frameRef.current;
    if (!el) return;
    const onErr = () => {
      if (!liveRef.current) return;
      failedRef.current = true;
      const message = 'Originalsidan kunde inte visas';
      setStatus({ phase: 'error', message });
      onFailed(item.id, message);
    };
    el.addEventListener('error', onErr);
    return () => el.removeEventListener('error', onErr);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status.phase, item.id, sectionId, attempt]);

  // Metadata fetch, scoped to this item + retry attempt. Stale responses
  // (a newer section replaced this one) are ignored, never acknowledged.
  useEffect(() => {
    const seq = ++seqRef.current;
    failedRef.current = false;
    setStatus({ phase: 'loading' });
    const ctrl = new AbortController();
    void (async () => {
      try {
        const res = await fetch(metaUrl, { signal: ctrl.signal });
        if (!res.ok) throw new Error(`Material ${res.status}`);
        const attribution = parseAttribution(await res.json());
        if (!attribution) throw new Error('Material metadata saknas');
        if (seqRef.current !== seq || !liveRef.current) return;
        setStatus({ phase: 'ready', attribution });
      } catch (err) {
        if (ctrl.signal.aborted || seqRef.current !== seq || !liveRef.current) return;
        const message = err instanceof Error ? err.message : 'Kunde inte hämta originalsidan';
        failedRef.current = true;
        setStatus({ phase: 'error', message });
        onFailed(item.id, message);
      }
    })();
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id, sectionId, attempt]);

  const ready = status.phase === 'ready';
  return (
    <article
      className="ot-bcard ot-bcard-material"
      ref={wrapRef}
      data-board-id={item.id}
      aria-label={item.title}
    >
      <figure className="ot-material-fig">
        {status.phase === 'loading' && (
          <div className="ot-pending" role="status">
            Hämtar originalsidan…
          </div>
        )}
        {status.phase === 'error' && (
          <div className="ot-material-error" role="alert">
            <p>{status.message}</p>
            <button type="button" className="ot-klar-btn" onClick={() => setAttempt((n) => n + 1)}>
              Försök igen
            </button>
          </div>
        )}
        {ready && (
          <iframe
            key={`${item.id}:${sectionId}:${attempt}`}
            ref={frameRef}
            className="ot-material-frame"
            title={item.title}
            src={pageUrl}
            sandbox=""
            referrerPolicy="no-referrer"
            style={{ height: frameH }}
            onLoad={() => {
              // Only the current section's first load counts: retries and
              // replacements remount the frame (key), and an earlier failure
              // already rejected this item's acknowledgement.
              if (failedRef.current || !liveRef.current) return;
              onMounted(item.id);
            }}
          />
        )}
        {status.phase === 'ready' && (
          <figcaption className="ot-material-attrib">Källa: {status.attribution}</figcaption>
        )}
      </figure>
    </article>
  );
}
