import { useEffect, useRef, useState } from 'react';
import type { BoardItem } from '../protocol';

export const IMAGE_MOUNT_TIMEOUT_MS = 4000;

type CardProps = {
  item: BoardItem;
  onMounted: (id: string) => void;
  onResourceClosed?: (id: string) => void;
  /** Immediate failure signal so a board RPC is rejected, not timed out. */
  onFailed?: (id: string, message: string) => void;
};

function useReportMounted(item: BoardItem, onMounted: (id: string) => void, waitForImage = false) {
  const ref = useRef<HTMLDivElement | null>(null);
  const done = useRef<BoardItem | null>(null);
  const finish = () => {
    if (done.current !== item) {
      done.current = item;
      onMounted(item.id);
    }
  };
  useEffect(() => {
    if (waitForImage) {
      const t = window.setTimeout(finish, IMAGE_MOUNT_TIMEOUT_MS);
      return () => window.clearTimeout(t);
    }
    const node = ref.current;
    if (!node) {
      finish();
      return;
    }
    let raf = 0;
    raf = requestAnimationFrame(() => finish());
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item]);
  return { ref, finish };
}

/** Visible content-box size of the board scroll surface around a card. */
function scrollAvail(wrap: HTMLElement | null): { w: number; h: number } | null {
  const scroller = wrap?.closest<HTMLElement>('.ot-board-scroll');
  if (!scroller) return null;
  const style = window.getComputedStyle(scroller);
  const padX = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
  const padY = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
  return { w: scroller.clientWidth - padX, h: scroller.clientHeight - padY };
}

function ImageCard({ item, onMounted }: CardProps) {
  if (item.kind !== 'image') return null;
  const { ref, finish } = useReportMounted(item, onMounted, true);
  return (
    <article className="ot-bcard" ref={ref} data-board-id={item.id} aria-label={item.title ?? item.alt}>
      {item.title && <h2>{item.title}</h2>}
      <img className="ot-image-full" src={item.url} alt={item.alt} onLoad={finish} onError={finish} />
    </article>
  );
}

function PendingCard({ item, onMounted }: CardProps) {
  if (item.kind !== 'pending') return null;
  const { ref } = useReportMounted(item, onMounted);
  const [availH, setAvailH] = useState<number | null>(null);
  useEffect(() => {
    const wrap = ref.current;
    if (!wrap) return;
    const compute = () => setAvailH(scrollAvail(wrap)?.h ?? null);
    compute();
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      const scroller = wrap.closest('.ot-board-scroll');
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
  const minHeight =
    item.height == null ? undefined : availH == null ? item.height : Math.min(item.height, Math.max(1, Math.floor(availH)));
  return (
    <article
      className="ot-bcard ot-bcard-pending"
      ref={ref}
      data-board-id={item.id}
      aria-label={item.title}
      style={minHeight ? { minHeight } : undefined}
    >
      <div className="ot-pending" role="status">
        Ritar…
      </div>
    </article>
  );
}

function ResourceCard({ item, onMounted, onResourceClosed }: CardProps) {
  if (item.kind !== 'resource') return null;
  const { ref } = useReportMounted(item, onMounted);
  return (
    <article className="ot-bcard" ref={ref} data-board-id={item.id} aria-label={item.title}>
      <h2>{item.title}</h2>
      {item.source && <div className="ot-resource-meta">Källa: {item.source}</div>}
      {item.embedUrl ? (
        <iframe
          className="ot-resource-frame"
          title={item.title}
          src={item.embedUrl}
          allow="autoplay; fullscreen; encrypted-media"
          allowFullScreen
        />
      ) : (
        <a className="ot-resource-open" href={item.url} target="_blank" rel="noopener noreferrer">
          Öppna i ny flik
        </a>
      )}
      {item.prompt && <div className="ot-prompt-chip">Fundera på: {item.prompt}</div>}
      <div>
        <button type="button" className="ot-klar-btn" onClick={() => onResourceClosed?.(item.id)}>
          Klar – prata vidare
        </button>
      </div>
    </article>
  );
}

function HomeworkCard({ item, onMounted }: CardProps) {
  if (item.kind !== 'homework') return null;
  const { ref } = useReportMounted(item, onMounted);
  return (
    <article className="ot-bcard" ref={ref} data-board-id={item.id} aria-label={item.title}>
      <div className="ot-paper">
        <h3>{item.title}</h3>
        {item.images?.map((src, i) => (
          <img key={i} src={src} alt={`Inlämnad bild ${i + 1}`} />
        ))}
        {item.text && <p>{item.text}</p>}
      </div>
    </article>
  );
}

export default function BoardCard(props: CardProps) {
  switch (props.item.kind) {
    case 'image':
      return <ImageCard {...props} />;
    case 'pending':
      return <PendingCard {...props} />;
    case 'resource':
      return <ResourceCard {...props} />;
    case 'homework':
      return <HomeworkCard {...props} />;
    case 'page':
      // Pages are rendered by PageCard in Board (they need a frame registry),
      // never through the generic card switch.
      return null;
    default:
      return null;
  }
}
