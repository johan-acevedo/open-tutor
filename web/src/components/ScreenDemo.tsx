import { useRef, useState } from 'react';
import Board from './Board';
import type { BoardItem } from '../protocol';
import type { PageAnswer, PageShellMessage } from './PageCard';
import { divisionBody, divisionPatch, klockanBody, klockanPatch } from 'virtual:screen-demo';

// Dev-only route (?screen-demo=1): two example pages as page items, no LiveKit.
// Buttons apply that example's patch, a reveal and a point to the current page.
const ITEMS: BoardItem[] = [
  { id: 'demo-klockan', kind: 'page', title: 'Vad är klockan?', body: klockanBody },
  { id: 'demo-division', kind: 'page', title: 'Pris per kilo', body: divisionBody },
];

const OPS: Record<string, { patch: string; reveal: string; point: string }> = {
  'demo-klockan': { patch: klockanPatch, reveal: 'val', point: 'klocka' },
  'demo-division': { patch: divisionPatch, reveal: 'stolen', point: 'stolen' },
};

export default function ScreenDemo() {
  const [activeId, setActiveId] = useState('demo-klockan');
  const [answers, setAnswers] = useState<PageAnswer[]>([]);
  const sends = useRef(new Map<string, (msg: PageShellMessage) => void>());

  const ops = OPS[activeId];
  const sendCurrent = (msg: PageShellMessage) => sends.current.get(activeId)?.(msg);

  return (
    <div className="ot-demo">
      <header className="ot-demo-bar">
        <strong>Skärm-demo</strong>
        <button type="button" onClick={() => ops && sendCurrent({ ot: 'patch', html: ops.patch })}>
          Visa patch
        </button>
        <button type="button" onClick={() => ops && sendCurrent({ ot: 'reveal', id: ops.reveal })}>
          Avslöja
        </button>
        <button type="button" onClick={() => ops && sendCurrent({ ot: 'point', id: ops.point })}>
          Peka
        </button>
      </header>
      <section className="ot-board ot-demo-board" aria-label="Whiteboard">
        <Board
          learnerName="Demo"
          items={ITEMS}
          focused={null}
          onItemMounted={() => {}}
          onResourceClosed={() => {}}
          activeItemId={activeId}
          registerPageFrame={(id, send) => {
            if (send) sends.current.set(id, send);
            else sends.current.delete(id);
          }}
          onPageAnswer={(answer) => setAnswers((prev) => [...prev, answer])}
          onCurrentChange={setActiveId}
        />
      </section>
      {answers.length > 0 && (
        <footer className="ot-demo-answers" aria-label="Svar från barnet">
          {answers.map((a, i) => (
            <div key={i}>
              page-answer: {a.page} · {a.part} = {a.value} ({a.kind})
            </div>
          ))}
        </footer>
      )}
    </div>
  );
}
