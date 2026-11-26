import { useRef, useState } from 'react';
import '@fontsource/plus-jakarta-sans/400.css';
import '@fontsource/plus-jakarta-sans/500.css';
import '@fontsource/plus-jakarta-sans/600.css';
import '@fontsource/plus-jakarta-sans/700.css';
import '@fontsource/plus-jakarta-sans/800.css';
import '@fontsource/caveat/600.css';
import { BANDS, BAND_IDS, explicitHostBand, type BandConfig, type BandId } from '../bands';
import { bandUrl } from '../bandLinks';
import type { Profile } from '../db';
import { t, type SvKey } from '../locales/sv';
import Brand from './Brand';
import Welcome from './Welcome';
import StartMenu, { type StartPanel } from './StartMenu';
import { useStartAction } from './useStartAction';
import { stopGreeting } from './greetingAudio';

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
  /** "Inte {name}?": open the household picker instead of the nameless view. */
  onNotYou?: () => void;
  /** On a band route: never assume a learner remembered from another band. */
  ignoreLastId?: boolean;
  /** Cross-band link: navigate in place instead of reloading. Only used on
   *  talarum-style hosts (no tutor.* prefix); on band hosts the links keep
   *  their href and the browser does the host swap. */
  onBandLink?: (band: BandId) => void;
}

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


const BAND_TITLES: Record<BandId, SvKey> = {
  primary: 'landing.bandsTitlePrimary',
  middle: 'landing.bandsTitleMiddle',
  upper: 'landing.bandsTitleUpper',
};

const AUDIENCES: Record<BandId, SvKey> = {
  primary: 'landing.audiencePrimary',
  middle: 'landing.audienceMiddle',
  upper: 'landing.audienceUpper',
};

/** Cross-links to the other two bands: small cards in the step-card language,
 *  the whole card one link. Sits between the steps and the footer. */
function Bands({ band, onNavigate }: { band: BandConfig; onNavigate?: (target: BandId) => void }) {
  return (
    <section className="ot-land-bands">
      <h2 className="ot-land-bandstitle">{t(BAND_TITLES[band.id])}</h2>
      <div className="ot-land-bandcards">
        {BAND_IDS.filter((id) => id !== band.id).map((id) => (
          <a
            key={id}
            className="ot-land-bandcard"
            href={bandUrl(id, window.location.href)}
            aria-label={`${t(AUDIENCES[id])} ${t('landing.withCompanion', { companion: BANDS[id].companion.name })}`}
            onClick={(event) => {
              if (!onNavigate) return;
              if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
              // A tutor.* host swap still needs a full load; anywhere else
              // the band route is same-origin, so navigate in place.
              try {
                if (explicitHostBand(window.location.hostname) !== null) return;
              } catch {
                return;
              }
              event.preventDefault();
              onNavigate(id);
            }}
          >
            <img className="ot-land-bandface" data-companion={id} src={BANDS[id].companion.face} alt="" aria-hidden="true" />
            <span className="ot-land-bandtxt">
              <strong>{t(AUDIENCES[id])}</strong>
              <span>{t('landing.withCompanion', { companion: BANDS[id].companion.name })}</span>
            </span>
            <span className="ot-land-bandarrow" aria-hidden="true">→</span>
          </a>
        ))}
      </div>
    </section>
  );
}

/** The three "how it works" cards: paper task, talking companion, mini board. */
export function HowSteps({ band }: { band: BandConfig }) {
  const rows = ROWS[band.id];
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
            <p>{t('landing.step1Text', { companion: band.companion.name })}</p>
          </div>
        </article>
        <article className="ot-land-card">
          <div className="ot-land-pic">
            <span className="ot-land-num" aria-hidden="true">2</span>
            <div className="ot-land-talk">
              <img src={band.companion.poses.speaking} alt="" aria-hidden="true" />
              <div className="ot-land-chat" aria-hidden="true">
                <i /><i /><i />
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
              <div className="ot-land-eq ot-land-eq-on">{t(rows[1])}</div>
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

/** Landing footer: one calm line plus a real link to /integritet. */
export function LandingFooter() {
  return (
    <footer className="ot-land-foot">
      <p>{t('landing.footerText')}</p>
      <a href="/integritet">{t('landing.footerPrivacy')} <span aria-hidden="true">→</span></a>
    </footer>
  );
}

/** The start (landing) page: top bar, hero, how-it-works, footer. The menu
 *  open and panel state lives here so the nav links open the same
 *  about/privacy panels as the hamburger menu; the footer links to
 *  /integritet. */
export default function LandingPage({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId, onSwitch, onNotYou, ignoreLastId, onBandLink }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [panel, setPanel] = useState<StartPanel>(null);
  const start = useStartAction({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId, ignoreLastId });

  const returnFocus = useRef<HTMLElement | null>(null);

  function openPanel(next: 'about' | 'privacy') {
    // Remember the nav or footer trigger so closing the menu returns there.
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setPanel(next);
    setMenuOpen(true);
  }

  function changeMenuOpen(next: boolean) {
    setMenuOpen(next);
    if (!next && returnFocus.current?.isConnected) returnFocus.current.focus();
    if (!next) returnFocus.current = null;
  }

  // Starting the call stops the greeting clip first; the start flow itself
  // (audio unlock, then profile pick) is untouched.
  function begin() {
    stopGreeting();
    start.begin();
  }

  return (
    <div className="ot-land">
      <header className="ot-land-top">
        <div className="ot-land-topinner">
        <Brand />
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
          <button type="button" className="ot-land-ghost" disabled={starting} onClick={begin}>
            {start.ctaLabel}
          </button>
          <StartMenu
            switchLabel={band.copy.switchStudent}
            onSwitch={onSwitch}
            open={menuOpen}
            onOpenChange={changeMenuOpen}
            panel={panel}
            onPanelChange={setPanel}
          />
        </div>
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
          onNotYou={onNotYou}
          ignoreLastId={ignoreLastId}
        />
        <HowSteps band={band} />
        <Bands band={band} onNavigate={onBandLink} />
        <LandingFooter />
      </div>
    </div>
  );
}
