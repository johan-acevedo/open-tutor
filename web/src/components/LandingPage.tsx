import { useState } from 'react';
import '@fontsource/plus-jakarta-sans/400.css';
import '@fontsource/plus-jakarta-sans/500.css';
import '@fontsource/plus-jakarta-sans/600.css';
import '@fontsource/plus-jakarta-sans/700.css';
import '@fontsource/plus-jakarta-sans/800.css';
import '@fontsource/caveat/600.css';
import type { BandConfig, BandId } from '../bands';
import type { Profile } from '../db';
import { t, type SvKey } from '../locales/sv';
import Welcome from './Welcome';
import StartMenu, { type StartPanel } from './StartMenu';
import { useStartAction } from './useStartAction';

type Props = {
  profiles: Profile[];
  band: BandConfig;
  onPick: (profile: Profile) => void;
  starting: boolean;
  onStartGesture?: () => void;
  /** Open the nameless first-visit view directly (menu leave flow). */
  startOpen?: boolean;
  /** After an in-call switch: assume this student instead of the last one. */
  assumeId?: string | null;
  /** Menu switch entry: return to the nameless first-visit view. */
  onSwitch: () => void;
};

const PAPER: Record<BandId, SvKey> = {
  primary: 'landing.paperPrimary',
  middle: 'landing.paperMiddle',
  upper: 'landing.paperUpper',
};

const ROWS: Record<BandId, [SvKey, SvKey, SvKey]> = {
  primary: ['landing.row1Primary', 'landing.row2Primary', 'landing.row3Primary'],
  middle: ['landing.row1Middle', 'landing.row2Middle', 'landing.row3Middle'],
  upper: ['landing.row1Upper', 'landing.row2Upper', 'landing.row3Upper'],
};

const OPS: Record<BandId, [SvKey, SvKey]> = {
  primary: ['landing.op1Primary', 'landing.op2Primary'],
  middle: ['landing.op1Middle', 'landing.op2Middle'],
  upper: ['landing.op1Upper', 'landing.op2Upper'],
};

// Static voice bars beside the speaking pose: the call has not started, so
// nothing here may move.
const BARS = [22, 48, 72, 40, 60, 28, 50, 18];

/** The three "how it works" cards: paper task, talking companion, mini board. */
function Steps({ band }: { band: BandConfig }) {
  const rows = ROWS[band.id];
  const ops = OPS[band.id];
  return (
    <section className="ot-land-how" id="sa-funkar-det">
      <h2 className="ot-land-howtitle">{t('landing.howTitle')}</h2>
      <div className="ot-land-cards">
        <article className="ot-land-card">
          <div className="ot-land-pic">
            <span className="ot-land-num" aria-hidden="true">1</span>
            <div className="ot-land-paper">{t(PAPER[band.id])}</div>
          </div>
          <div className="ot-land-cardtxt">
            <h3>{t('landing.step1Title')}</h3>
            <p>{t('landing.step1Text')}</p>
          </div>
        </article>
        <article className="ot-land-card">
          <div className="ot-land-pic">
            <span className="ot-land-num" aria-hidden="true">2</span>
            <div className="ot-land-talk">
              <img src={band.companion.poses.speaking} alt="" aria-hidden="true" />
              <div className="ot-land-wave" aria-hidden="true">
                {BARS.map((h, i) => (
                  <i key={i} style={{ height: h }} />
                ))}
              </div>
            </div>
          </div>
          <div className="ot-land-cardtxt">
            <h3>{t('landing.step2Title', { companion: band.companion.name })}</h3>
            <p>{t('landing.step2Text', { companion: band.companion.name })}</p>
          </div>
        </article>
        <article className="ot-land-card">
          <div className="ot-land-pic">
            <span className="ot-land-num" aria-hidden="true">3</span>
            <div className="ot-land-mini">
              <div className="ot-land-eq">{t(rows[0])}</div>
              <div className="ot-land-op" aria-hidden="true">{t(ops[0])}</div>
              <div className="ot-land-eq ot-land-eq-on">{t(rows[1])}</div>
              <div className="ot-land-op" aria-hidden="true">{t(ops[1])}</div>
              <div className="ot-land-eq">{t(rows[2])}</div>
            </div>
          </div>
          <div className="ot-land-cardtxt">
            <h3>{t('landing.step3Title')}</h3>
            <p>{t('landing.step3Text')}</p>
          </div>
        </article>
      </div>
    </section>
  );
}

/** The start (landing) page: top bar, hero, how-it-works, footer. The menu
 *  open and panel state lives here so the nav links and the footer open the
 *  same about/privacy panels as the hamburger menu. */
export default function LandingPage({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId, onSwitch }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [panel, setPanel] = useState<StartPanel>(null);
  const start = useStartAction({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId });

  function openPanel(next: 'about' | 'privacy') {
    setPanel(next);
    setMenuOpen(true);
  }

  return (
    <div className="ot-land">
      <header className="ot-land-top">
        <div className="ot-land-brand">
          <span className="ot-land-mark" aria-hidden="true" />
          <span>Open Tutor</span>
        </div>
        <nav className="ot-land-links" aria-label={t('landing.navLabel')}>
          <a href="#sa-funkar-det">{t('landing.howTitle')}</a>
          <button type="button" onClick={() => openPanel('about')}>
            {t('startmenu.about')}
          </button>
          <button type="button" onClick={() => openPanel('privacy')}>
            {t('startmenu.privacy')}
          </button>
        </nav>
        <div className="ot-land-topright">
          <button type="button" className="ot-land-ghost" disabled={starting} onClick={start.begin}>
            {start.ctaLabel}
          </button>
          <StartMenu
            switchLabel={band.copy.switchStudent}
            onSwitch={onSwitch}
            open={menuOpen}
            onOpenChange={setMenuOpen}
            panel={panel}
            onPanelChange={setPanel}
          />
        </div>
      </header>
      <div className="ot-land-scroll">
        <Welcome
          profiles={profiles}
          band={band}
          onPick={onPick}
          starting={starting}
          onStartGesture={onStartGesture}
          startOpen={startOpen}
          assumeId={assumeId}
          action={start}
        />
        <Steps band={band} />
        <footer className="ot-land-foot">
          <p>{t('landing.footerText')}</p>
          <button type="button" onClick={() => openPanel('privacy')}>
            {t('landing.footerPrivacy')} <span aria-hidden="true">→</span>
          </button>
        </footer>
      </div>
    </div>
  );
}
