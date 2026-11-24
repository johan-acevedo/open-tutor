import { useEffect } from 'react';
import type { BandConfig, BandId } from '../bands';
import type { Profile } from '../db';
import { t, type SvKey } from '../locales/sv';
import { useStartAction, type StartAction } from './useStartAction';
import { stopGreeting, toggleGreeting, useGreetingPlaying } from './greetingAudio';

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
  /** Shared start decision (the top bar ghost button fires the same begin). */
  action?: StartAction;
};

const INTRO: Record<BandId, SvKey> = {
  primary: 'landing.introPrimary',
  middle: 'landing.introMiddle',
  upper: 'landing.introUpper',
};

/** The comic bubble is a real button: tapping it plays the companion's spoken
 *  greeting, tapping again stops. The waves animate gently while the clip
 *  plays (see .ot-land-bubble.is-playing); nothing moves before the call.
 *  The bubble lives inside the figure wrapper so it scales with the image. */
function GreetingBubble({ band, label, long }: { band: BandConfig; label: string; long: boolean }) {
  const playing = useGreetingPlaying();
  // A band change (late /api/config) or leaving the landing stops the clip,
  // so no stale greeting keeps playing under another companion.
  useEffect(() => () => stopGreeting(), [band.id]);
  return (
    <button
      type="button"
      className={`ot-land-bubble${playing ? ' is-playing' : ''}${long ? ' is-long' : ''}`}
      aria-label={t('landing.listenAria', { greeting: label, companion: band.companion.name })}
      aria-pressed={playing}
      onClick={() => toggleGreeting(band.id)}
    >
      <svg className="ot-land-bubble-shape" viewBox="0 0 270 160" aria-hidden="true">
        <path
          d="M46 4 H224 A42 42 0 0 1 266 46 V58 A42 42 0 0 1 224 100 H196 L262 156 L150 100 H46 A42 42 0 0 1 4 58 V46 A42 42 0 0 1 46 4 Z"
          fill="var(--ot-paper)"
          stroke="#0b0d12"
          strokeWidth="5"
          strokeLinejoin="round"
        />
      </svg>
      <span className="ot-land-bubble-in" aria-hidden="true">
        {/* The outer wave reaches past x=48, so the viewBox leaves room:
            without it the wave's right edge is cut off. */}
        <svg className="ot-land-spk" viewBox="0 0 52 48">
          <path d="M6 18 H14 L25 9 V39 L14 30 H6 Z" fill="#12151b" stroke="#12151b" strokeWidth="3" strokeLinejoin="round" />
          <path d="M31 17 a10 10 0 0 1 0 14" fill="none" stroke="var(--ot-cyan)" strokeWidth="4.5" strokeLinecap="round" />
          <path d="M36 11 a18 18 0 0 1 0 26" fill="none" stroke="var(--ot-cyan)" strokeWidth="4.5" strokeLinecap="round" />
          <path d="M41 6 a26 26 0 0 1 0 36" fill="none" stroke="var(--ot-cyan)" strokeWidth="4.5" strokeLinecap="round" opacity=".55" />
        </svg>
        <span>{label}</span>
      </span>
    </button>
  );
}

/** Landing hero: headline, band intro, the single start action and the comic
 *  bubble over the companion. First visit shows the nameless view; later
 *  visits assume the same student with an inline not-you link on the same row
 *  as the button. The tutor asks for the name by voice after starting. Copy
 *  lives in web/src/locales/sv.ts. */
export default function Welcome({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId, action }: Props) {
  const fallback = useStartAction({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId });
  const start = action ?? fallback;

  // Starting the call stops the greeting clip first; the start flow itself
  // (audio unlock, then profile pick) is untouched.
  function begin() {
    stopGreeting();
    start.begin();
  }

  return (
    <div className="ot-land-hero">
      <div className="ot-land-grid" aria-hidden="true" />
      <div className="ot-land-glow" aria-hidden="true" />
      <div className="ot-land-copy">
        <h1 className="ot-land-title">
          {t('landing.titlePrefix')}
          <span className="ot-land-accent">{t('landing.titleAccent')}</span>
          {t('landing.titleSuffix')}
          <span className="ot-land-dot">{t('landing.titlePeriod')}</span>
        </h1>
        <p className="ot-land-sub">{t(INTRO[band.id])}</p>
        <div className="ot-land-cta-row">
          <button
            type="button"
            className="ot-land-cta"
            disabled={starting}
            onClick={begin}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
            {start.ctaLabel}
          </button>
          {!start.firstVisit && (
            <button type="button" className="ot-link-btn ot-land-notyou" onClick={start.showFirstVisit}>
              {start.notYou}
            </button>
          )}
        </div>
      </div>
      <div className="ot-land-stage">
        <div className="ot-land-fig">
          <img
            className="ot-land-heroimg"
            src={band.companion.hero}
            alt=""
            aria-hidden="true"
            onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
          />
          <GreetingBubble band={band} label={start.bubble} long={!start.firstVisit} />
        </div>
      </div>
    </div>
  );
}
