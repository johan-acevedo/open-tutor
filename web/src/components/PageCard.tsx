import { useEffect, useMemo, useRef, useState } from 'react';
import type { BoardItem } from '../protocol';
import { composePage } from '../shell';

/** Messages the parent may pass to a page's shell (see screen/shell/shell.js). */
export type PageShellMessage =
  | { ot: 'patch'; html: string }
  | { ot: 'point'; id: string | null }
  | { ot: 'reveal'; id: string };

/** A submitted answer from ot-answer, ot-choice or ot-gap. */
export type PageAnswer = { page: string; part: string; value: string; kind: string };

type Props = {
  item: Extract<BoardItem, { kind: 'page' }>;
  onMounted: (id: string) => void;
  registerSend: (id: string, send: ((msg: PageShellMessage) => void) | null) => void;
  onAnswer: (answer: PageAnswer) => void;
};

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

export default function PageCard({ item, onMounted, registerSend, onAnswer }: Props) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const readyRef = useRef(false);
  const queueRef = useRef<PageShellMessage[]>([]);
  const [ready, setReady] = useState(false);
  const answerRef = useRef(onAnswer);
  answerRef.current = onAnswer;

  const srcDoc = useMemo(() => composePage(item.body), [item.body]);

  // Report the mount (frame element in the DOM) so board.show can ack;
  // the shell reports ready separately once the page is finished.
  useEffect(() => {
    let raf = 0;
    raf = requestAnimationFrame(() => onMounted(item.id));
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  useEffect(() => {
    const send = (msg: PageShellMessage) => {
      const win = frameRef.current?.contentWindow;
      if (readyRef.current && win) {
        win.postMessage(msg, '*');
      } else {
        queueRef.current.push(msg);
      }
    };
    registerSend(item.id, send);
    return () => registerSend(item.id, null);
  }, [item.id, registerSend]);

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      const frame = frameRef.current;
      // The frame is opaque (srcdoc + sandbox); only its window may talk to us.
      if (!frame || e.source !== frame.contentWindow) return;
      const m = e.data;
      if (!isRecord(m) || typeof m.ot !== 'string') return;
      if (m.ot === 'ready') {
        readyRef.current = true;
        setReady(true);
        const win = frame.contentWindow;
        if (win) {
          for (const msg of queueRef.current) win.postMessage(msg, '*');
        }
        queueRef.current = [];
      } else if (m.ot === 'answer') {
        // The shell sends { ot, id, value } (+index for ot-choice); it does not
        // say which tag answered, so kind stays 'answer' unless it ever does.
        answerRef.current({
          page: item.id,
          part: String(m.id ?? ''),
          value: String(m.value ?? ''),
          kind: typeof m.kind === 'string' && m.kind ? m.kind : 'answer',
        });
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [item.id]);

  return (
    <article
      className={`ot-bcard-page${ready ? ' is-ready' : ''}`}
      data-board-id={item.id}
      aria-label={item.title}
    >
      <iframe
        ref={frameRef}
        className="ot-page-frame"
        title={item.title}
        sandbox="allow-scripts"
        srcDoc={srcDoc}
      />
    </article>
  );
}
