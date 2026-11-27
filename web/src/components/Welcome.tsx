import { useEffect } from 'react';
import type { BandConfig, BandId } from '../bands';
import type { Profile } from '../db';
import { t, type SvKey } from '../locales/sv';
import { useStartAction, type StartAction } from './useStartAction';
import { stopGreeting } from './greetingAudio';
import { ListenButton, Notebook, PaperTitle, PriceAnchor, StartButton } from './Paper';

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
  /** Shared start decision (the menu's switch entry uses the same flow). */
  action?: StartAction;
  /** "Inte {name}?": open the household picker instead of the nameless view. */
  onNotYou?: () => void;
  /** On a band route: never assume a learner remembered from another band. */
  ignoreLastId?: boolean;
}

const TITLE: Record<BandId, [SvKey, SvKey, SvKey]> = {
  primary: ['landing.familyTitlePrefix', 'landing.familyTitleAccent', 'landing.familyTitleSuffix'],
  middle: ['landing.middleTitlePrefix', 'landing.middleTitleAccent', 'landing.middleTitleSuffix'],
  upper: ['landing.upperTitlePrefix', 'landing.upperTitleAccent', 'landing.upperTitleSuffix'],
};

const INTRO: Record<BandId, SvKey> = {
  primary: 'landing.introPrimary',
  middle: 'landing.introMiddle',
  upper: 'landing.introUpper',
};

/** Band page hero: headline, band intro, the single start action, a quiet
 *  listen control and the exercise book. A returning visit greets by name
 *  ("Hej Alva!") with an inline not-you link; the tutor asks for the name
 *  by voice after starting. Copy lives in web/src/locales/sv.ts. */
export default function Welcome({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId, action, onNotYou, ignoreLastId }: Props) {
  const fallback = useStartAction({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId, ignoreLastId });
  const start = action ?? fallback;
  // A band change (late /api/config) or leaving the page stops the clip,
  // so no stale greeting keeps playing under another companion.
  useEffect(() => () => stopGreeting(), [band.id]);

  // Starting the call stops the greeting clip first; the start flow itself
  // (audio unlock, then profile pick) is untouched.
  function begin() {
    stopGreeting();
    start.begin();
  }

  const [prefix, accent, suffix] = TITLE[band.id];
  return (
    <header className="tp-hero tp-wrap">
      <div className="tp-hero-copy">
        <PaperTitle prefix={prefix} accent={accent} suffix={suffix} />
        <p className="tp-lede">{t(INTRO[band.id])}</p>
        {!start.firstVisit && (
          <p className="tp-hello">
            <span className="tp-hello-name">{start.bubble}</span>
            <button type="button" className="tp-notyou" onClick={onNotYou ?? start.showFirstVisit}>
              {start.notYou}
            </button>
          </p>
        )}
        <div className="tp-cta-area">
          <div className="tp-cta-row">
            <StartButton band={band} label={start.ctaLabel} disabled={starting} onClick={begin} />
            <ListenButton band={band} greeting={start.bubble} />
          </div>
          <PriceAnchor />
        </div>
      </div>
      <Notebook band={band} />
    </header>
  );
}
