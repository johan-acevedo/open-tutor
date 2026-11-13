import { useRef, useState } from 'react';
import Board from './Board';
import BottomBar from './BottomBar';
import PhoneStage from './PhoneStage';
import type { BoardItem } from '../protocol';
import type { Pill } from '../avatarState';
import type { PageAnswer, PageShellMessage } from './PageCard';
import { usePhoneStage } from '../phoneStage';
import { useViewport } from '../useViewport';
import { divisionBody, divisionPatch, klockanBody, klockanPatch } from 'virtual:screen-demo';

// Dev-only route (?screen-demo=1): two example pages as page items, no LiveKit.
// Buttons apply that example's patch, a reveal and a point to the current page.
// In phone portrait the demo plays the real two-view stage: it starts on the
// big fox with a greeting, "Visa sidan" shows the page with the fox strip, and
// tapping the fox head goes back — so the phone layout can be checked here.
const ITEMS: BoardItem[] = [
  { id: 'demo-klockan', kind: 'page', title: 'Vad är klockan?', body: klockanBody },
  { id: 'demo-division', kind: 'page', title: 'Pris per kilo', body: divisionBody },
];

const OPS: Record<string, { patch: string; reveal: string; point: string }> = {
  'demo-klockan': { patch: klockanPatch, reveal: 'val', point: 'klocka' },
  'demo-division': { patch: divisionPatch, reveal: 'stolen', point: 'stolen' },
};

const GREETING = 'Hej! Jag heter Räven. Vad jobbar du med idag?';
// Long enough that both bubbles have to trim it (4 lines big, 3 lines in the strip).
const LONG_LINE =
  'Titta på klockan på sidan. Den stora visaren pekar på tolv, och den lilla står på tre. ' +
  'Då är klockan tre, eller hur? Säg vad du tror att den lilla visaren betyder.';
const SPEAKING: Pill = { label: 'Pratar', icon: 'bars', tone: 'cyan', animateBars: true };

export default function ScreenDemo() {
  const { mobile, portrait } = useViewport();
  const phone = mobile && portrait;
  const [activeId, setActiveId] = useState('demo-klockan');
  const [said, setSaid] = useState(GREETING);
  const [answers, setAnswers] = useState<PageAnswer[]>([]);
  const sends = useRef(new Map<string, (msg: PageShellMessage) => void>());
  const stage = usePhoneStage({ hasItem: ITEMS.length > 0, itemSignal: 0, initial: 'fox' });

  const ops = OPS[activeId];
  const sendCurrent = (msg: PageShellMessage) => sends.current.get(activeId)?.(msg);

  function showItem() {
    stage.showItem();
    // The tutor talks about the page once it is up.
    setSaid(LONG_LINE);
  }

  const board = (
    <Board
      learnerName="Demo"
      items={ITEMS}
      focused={null}
      onItemMounted={() => {}}
      onResourceClosed={() => {}}
      mobile={phone}
      showEmptyState={!phone}
      activeItemId={activeId}
      registerPageFrame={(id, send) => {
        if (send) sends.current.set(id, send);
        else sends.current.delete(id);
      }}
      onPageAnswer={(answer) => setAnswers((prev) => [...prev, answer])}
      onCurrentChange={setActiveId}
    />
  );

  const answersList = answers.length > 0 && (
    <footer className="ot-demo-answers" aria-label="Svar från barnet">
      {answers.map((a, i) => (
        <div key={i}>
          page-answer: {a.page} · {a.part} = {a.value} ({a.kind})
        </div>
      ))}
    </footer>
  );

  const controls = (
    <>
      <button type="button" onClick={() => ops && sendCurrent({ ot: 'patch', html: ops.patch })}>
        Visa patch
      </button>
      <button type="button" onClick={() => ops && sendCurrent({ ot: 'reveal', id: ops.reveal })}>
        Avslöja
      </button>
      <button type="button" onClick={() => ops && sendCurrent({ ot: 'point', id: ops.point })}>
        Peka
      </button>
    </>
  );

  if (phone) {
    return (
      <div className="ot-root ot-phone ot-phone-portrait">
        <header className="ot-demo-bar ot-demo-bar-phone">
          <strong>Skärm-demo</strong>
          {controls}
        </header>
        <PhoneStage
          learnerName="Demo"
          items={ITEMS}
          focused={null}
          mode="teaching"
          stage={{ ...stage, showItem }}
          pose={stage.foxView ? 'greeting' : 'speaking'}
          pill={SPEAKING}
          caption={said}
          captionFading={false}
          activeItemId={activeId}
          onItemMounted={() => {}}
          onResourceClosed={() => {}}
          registerPageFrame={(id, send) => {
            if (send) sends.current.set(id, send);
            else sends.current.delete(id);
          }}
          onPageAnswer={(answer) => setAnswers((prev) => [...prev, answer])}
        />
        {answersList}
        <BottomBar
          micEnabled
          micBlocked={false}
          sending={false}
          mobile
          onSendText={() => {}}
          onToggleMic={() => {}}
          onAttach={() => {}}
        />
      </div>
    );
  }

  return (
    <div className="ot-demo">
      <header className="ot-demo-bar">
        <strong>Skärm-demo</strong>
        {controls}
      </header>
      <section className="ot-board ot-demo-board" aria-label="Whiteboard">
        {board}
      </section>
      {answersList}
    </div>
  );
}
