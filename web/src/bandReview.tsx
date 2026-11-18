import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BandProvider } from './BandContext';
import { BANDS, bandFromSearch } from './bands';
import type { Pill, Pose } from './avatarState';
import Avatar from './components/Avatar';
import PageCard from './components/PageCard';
import BottomBar from './components/BottomBar';
import { useViewport } from './useViewport';
import './styles.css';
import './mobile.css';
import './bandStyles.css';

const poses: Pose[] = ['greeting', 'listening', 'speaking', 'thinking', 'working', 'waiting', 'pointing'];
const item = {
  kind: 'page', id: 'review-units', title: 'Enheter och samband',
  body: '<h1>Enheter och samband</h1><div class="card"><p class="big">sträcka = hastighet × tid</p></div><p>Vilken enhet mäter sträcka?</p><ot-answer id="unit" label="Ditt svar"></ot-answer>',
} satisfies Parameters<typeof PageCard>[0]['item'];

function Review() {
  const band = bandFromSearch(window.location.search) ?? 'middle';
  const [pose, setPose] = useState<Pose>('pointing');
  const [answer, setAnswer] = useState('');
  const { mobile } = useViewport();
  const speaking = pose === 'speaking' || pose === 'pointing';
  const preparing = pose === 'working' || pose === 'thinking';
  const pill: Pill = speaking
    ? { label: 'Pratar', icon: 'bars', tone: 'cyan', animateBars: true }
    : preparing
      ? { label: pose === 'working' ? 'Förbereder tavlan' : 'Tänker…', icon: pose === 'working' ? 'pencil' : 'sparkle', tone: 'violet', animateBars: false }
      : { label: pose === 'waiting' ? 'Väntar' : 'Lyssnar', icon: pose === 'waiting' ? 'circle' : 'ear', tone: pose === 'waiting' ? 'grey' : 'cyan', animateBars: false };
  return (
    <BandProvider band={band}>
      <div className={`ot-root${mobile ? ' ot-phone' : ''}`} data-band={band}>
        <header className="ot-topbar"><strong>{BANDS[band].companion.name}</strong><span>Design review</span></header>
        <nav className="ot-review-controls" aria-label="Pose">
          {poses.map(p => <button key={p} type="button" aria-pressed={pose === p} onClick={() => setPose(p)}>{p}</button>)}
        </nav>
        <main className="ot-main ot-main-teaching">
          <section className="ot-board">
            <PageCard item={item} onMounted={() => {}} registerSend={() => {}} onAnswer={a => setAnswer(a.value)} />
            <output>{answer}</output>
          </section>
          <aside className="ot-avatar-col">
            <Avatar pose={pose} pill={pill} caption={speaking ? 'Vi börjar med vad vi vet.' : ''} captionFading={false} />
          </aside>
        </main>
        <BottomBar mobile={mobile} micEnabled micBlocked={false} sending={false} onSendText={() => {}} onToggleMic={() => {}} onAttach={() => {}} />
      </div>
    </BandProvider>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Missing review root');
createRoot(root).render(<Review />);
