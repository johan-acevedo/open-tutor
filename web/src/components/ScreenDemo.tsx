import { useRef, useState } from 'react';
import Board from './Board';
import { useBand } from '../BandContext';
import BottomBar from './BottomBar';
import PhoneStage from './PhoneStage';
import type { BoardItem } from '../protocol';
import type { Pill } from '../avatarState';
import type { PageAnswer, PageShellMessage } from './PageCard';
import { usePhoneStage } from '../phoneStage';
import { useViewport } from '../useViewport';
import { divisionBody, divisionPatch, klockanBody, klockanPatch } from 'virtual:screen-demo';
import { sv, t } from '../locales/sv';

// Dev-only route (?screen-demo=1): two example pages as page items, no LiveKit.
// Buttons apply that example's patch, a reveal and a point to the current page.
// In phone portrait the demo plays the real two-view stage: it starts on the
// big companion with a greeting, the show-page button shows the page with the fox strip, and
// tapping the fox head goes back — so the phone layout can be checked here.
const ITEMS: BoardItem[] = [
  { id: 'demo-klockan', kind: 'page', title: sv['demo.klockanTitle'], body: klockanBody },
  { id: 'demo-division', kind: 'page', title: sv['demo.divisionTitle'], body: divisionBody },
];

const OPS: Record<string, { patch: string; reveal: string; point: string }> = {
  'demo-klockan': { patch: klockanPatch, reveal: 'val', point: 'klocka' },
  'demo-division': { patch: divisionPatch, reveal: 'stolen', point: 'stolen' },
};

// Long enough that both bubbles have to trim it (4 lines big, 3 lines in the strip).
const LONG_LINE: string = sv['demo.longLine'];
const SPEAKING: Pill = { label: sv['pill.speaking'], icon: 'bars', tone: 'cyan', animateBars: true };

export default function ScreenDemo() {
  const band = useBand();
  const { mobile, portrait } = useViewport();
  const phone = mobile && portrait;
  const [activeId, setActiveId] = useState('demo-klockan');
  const [said, setSaid] = useState(t('demo.greeting', { companion: band.companion.name }));
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
    <footer className="ot-demo-answers" aria-label={t('demo.answersLabel')}>
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
        {t('demo.showPatch')}
      </button>
      <button type="button" onClick={() => ops && sendCurrent({ ot: 'reveal', id: ops.reveal })}>
        {t('demo.reveal')}
      </button>
      <button type="button" onClick={() => ops && sendCurrent({ ot: 'point', id: ops.point })}>
        {t('demo.point')}
      </button>
    </>
  );

  if (phone) {
    return (
      <div data-band={band.id} className="ot-root ot-phone ot-phone-portrait">
        <header className="ot-demo-bar ot-demo-bar-phone">
          <strong>{t('demo.header')}</strong>
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
          ending={false}
          mobile
          onSendText={() => {}}
          onToggleMic={() => {}}
          onAttach={() => {}}
          onEnd={() => {}}
        />
      </div>
    );
  }

  return (
    <div data-band={band.id} className="ot-root ot-demo">
      <header className="ot-demo-bar">
        <strong>{t('demo.header')}</strong>
        {controls}
      </header>
      <section className="ot-board ot-demo-board" aria-label="Whiteboard">
        {board}
      </section>
      {answersList}
    </div>
  );
}
