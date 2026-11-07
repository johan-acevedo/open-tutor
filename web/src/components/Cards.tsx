import { useEffect, useMemo, useRef } from 'react';
import katex from 'katex';
import type { BoardItem } from '../protocol';
import { renderMarkdown } from '../markdown';
import { sanitiseSvg } from '../svgSanitize';

export const IMAGE_MOUNT_TIMEOUT_MS = 4000;

type CardProps = {
  item: BoardItem;
  focusedStep?: number;
  onMounted: (id: string) => void;
  onResourceClosed?: (id: string) => void;
  revealThrough?: number;
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

function TextCard({ item, onMounted }: CardProps) {
  if (item.kind !== 'text') return null;
  const { ref } = useReportMounted(item, onMounted);
  const html = useMemo(() => renderMarkdown(item.markdown), [item.markdown]);
  return (
    <article className="ot-bcard ot-katex" ref={ref} data-board-id={item.id} aria-label={item.title ?? 'Text'}>
      {item.title && <h2>{item.title}</h2>}
      <div className="ot-md" dangerouslySetInnerHTML={{ __html: html }} />
    </article>
  );
}

function StepsCard({ item, focusedStep, onMounted, revealThrough }: CardProps) {
  if (item.kind !== 'steps') return null;
  const { ref } = useReportMounted(item, onMounted);
  const stepRefs = useRef(new Map<number, HTMLDivElement>());
  useEffect(() => {
    if (focusedStep !== undefined && revealThrough === undefined) {
      const el = stepRefs.current.get(focusedStep);
      if (el && typeof el.scrollIntoView === 'function') {
        el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }
  }, [focusedStep, revealThrough]);
  return (
    <article className="ot-bcard ot-katex" ref={ref} data-board-id={item.id} aria-label={item.title ?? 'Steg för steg'}>
      {item.title && <h2>{item.title}</h2>}
      <div className="ot-steps">
        {item.steps.map((s, i) => (
          <div className="ot-step-row" key={i} hidden={revealThrough !== undefined && i > revealThrough}>
            {i > 0 && (s.op || s.note) && (
              <div className="ot-step-transition">
                {s.op && (
                  <span
                    className="ot-op"
                    aria-label={`Operation: ${s.op}`}
                    dangerouslySetInnerHTML={{
                      __html: katex.renderToString(s.op, { displayMode: false, throwOnError: false }),
                    }}
                  />
                )}
                {s.note && <span className="ot-step-note">{s.note}</span>}
              </div>
            )}
            <div
              ref={(el) => {
                if (el) stepRefs.current.set(i, el);
                else stepRefs.current.delete(i);
              }}
              className={`ot-step-eq${focusedStep === i ? ' focused' : ''}`}
              data-step={i}
              dangerouslySetInnerHTML={{
                __html: katex.renderToString(s.tex, { displayMode: true, throwOnError: false }),
              }}
            />
            {i === 0 && s.note && <div className="ot-step-note">{s.note}</div>}
          </div>
        ))}
      </div>
    </article>
  );
}

function MindmapCard({ item, onMounted }: CardProps) {
  if (item.kind !== 'mindmap') return null;
  const { ref } = useReportMounted(item, onMounted);
  return (
    <article className="ot-bcard" ref={ref} data-board-id={item.id} aria-label={item.title ?? 'Tankekarta'}>
      {item.title && <h2>{item.title}</h2>}
      <div className="ot-mindmap">
        <div className="ot-mind-center">{item.center}</div>
        <div className="ot-mind-ideas">
          {item.ideas.map((idea, i) => (
            <div className="ot-mind-idea" key={i}>
              {idea}
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

function SvgCard({ item, onMounted }: CardProps) {
  if (item.kind !== 'svg') return null;
  const { ref } = useReportMounted(item, onMounted);
  const html = useMemo(() => sanitiseSvg(item.svg), [item.svg]);
  return (
    <article className="ot-bcard" ref={ref} data-board-id={item.id} aria-label={item.title ?? 'Bild'}>
      {item.title && <h2>{item.title}</h2>}
      <div className="ot-svg-wrap" dangerouslySetInnerHTML={{ __html: html }} />
    </article>
  );
}

const HTML_CSP =
  "default-src 'none'; script-src 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'unsafe-inline'; img-src data: https:";

function HtmlCard({ item, onMounted }: CardProps) {
  if (item.kind !== 'html') return null;
  const { ref } = useReportMounted(item, onMounted);
  const srcDoc = useMemo(
    () => `<meta http-equiv="Content-Security-Policy" content="${HTML_CSP}">\n${item.html}`,
    [item.html],
  );
  const height = item.height ?? 360;
  return (
    <article className="ot-bcard" ref={ref} data-board-id={item.id} aria-label={item.title ?? 'Interaktiv'}>
      {item.title && <h2>{item.title}</h2>}
      <iframe
        className="ot-html-frame"
        title={item.title ?? 'Interaktivt innehåll'}
        sandbox="allow-scripts"
        srcDoc={srcDoc}
        style={{ height }}
      />
    </article>
  );
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
  return (
    <article className="ot-bcard" ref={ref} data-board-id={item.id} aria-label={item.title}>
      <h2>{item.title}</h2>
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
    case 'text':
      return <TextCard {...props} />;
    case 'steps':
      return <StepsCard {...props} />;
    case 'mindmap':
      return <MindmapCard {...props} />;
    case 'svg':
      return <SvgCard {...props} />;
    case 'html':
      return <HtmlCard {...props} />;
    case 'image':
      return <ImageCard {...props} />;
    case 'pending':
      return <PendingCard {...props} />;
    case 'resource':
      return <ResourceCard {...props} />;
    case 'homework':
      return <HomeworkCard {...props} />;
    default:
      return null;
  }
}
