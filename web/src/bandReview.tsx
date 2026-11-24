import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BandProvider } from './BandContext';
import { BANDS, bandFromSearch } from './bands';
import type { Pill, Pose } from './avatarState';
import Avatar from './components/Avatar';
import PageCard from './components/PageCard';
import BottomBar from './components/BottomBar';
import { useViewport } from './useViewport';
import { htmlLang, sv } from './locales/sv';
try { document.documentElement.lang = htmlLang; } catch { /* ignore */ }
import './styles.css';
import './mobile.css';
import './bandStyles.css';
import './callChrome.css';

const poses: Pose[] = ['greeting', 'listening', 'speaking', 'thinking', 'working', 'waiting', 'pointing'];
const item = {
  kind: 'page', id: 'review-units', title: sv['review.exampleTitle'],
  body: sv['review.exampleBody'],
} satisfies Parameters<typeof PageCard>[0]['item'];

function Review() {
  const band = bandFromSearch(window.location.search) ?? 'middle';
  const [pose, setPose] = useState<Pose>('pointing');
  const [answer, setAnswer] = useState('');
  const { mobile } = useViewport();
  const speaking = pose === 'speaking' || pose === 'pointing';
  const preparing = pose === 'working' || pose === 'thinking';
  const pill: Pill = speaking
    ? { label: sv['pill.speaking'], icon: 'bars', tone: 'cyan', animateBars: true }
    : preparing
      ? { label: pose === 'working' ? sv['review.preparing'] : sv['pill.thinking'], icon: pose === 'working' ? 'pencil' : 'sparkle', tone: 'violet', animateBars: false }
      : { label: pose === 'waiting' ? sv['pill.waiting'] : sv['pill.listening'], icon: pose === 'waiting' ? 'circle' : 'ear', tone: pose === 'waiting' ? 'grey' : 'cyan', animateBars: false };
  return (
    <BandProvider band={band}>
      <div className={`ot-root${mobile ? ' ot-phone' : ''}`} data-band={band}>
        <header className="ot-topbar"><div className="ot-topbar-inner"><strong>{BANDS[band].companion.name}</strong><span>Design review</span></div></header>
        <nav className="ot-review-controls" aria-label="Pose">
          {poses.map(p => <button key={p} type="button" aria-pressed={pose === p} onClick={() => setPose(p)}>{p}</button>)}
        </nav>
        <main className="ot-main ot-main-teaching">
          <section className="ot-board">
            <PageCard item={item} onMounted={() => {}} registerSend={() => {}} onAnswer={a => setAnswer(a.value)} />
            <output>{answer}</output>
          </section>
          <aside className="ot-avatar-col">
            <Avatar pose={pose} pill={pill} caption={speaking ? sv['review.exampleCaption'] : ''} captionFading={false} />
          </aside>
        </main>
        <BottomBar mobile={mobile} micEnabled micBlocked={false} sending={false} ending={false} onSendText={() => {}} onToggleMic={() => {}} onAttach={() => {}} onEnd={() => {}} />
      </div>
    </BandProvider>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Missing review root');
createRoot(root).render(<Review />);
