import { useEffect } from 'react';
import type { BandConfig } from '../bands';
import type { Profile } from '../db';
import { useStartAction, type StartAction } from './useStartAction';
import { stopGreeting } from './greetingAudio';
import { Hero } from './Paper';

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
  /** Start handler shared with the closing call to action. */
  onBegin?: () => void;
  /** "Inte {name}?": open the household picker instead of the nameless view. */
  onNotYou?: () => void;
  /** On a band route: never assume a learner remembered from another band. */
  ignoreLastId?: boolean;
}

/** Band page hero: headline, band intro, the single start action, the
 *  labelled listen control and the showcase. A returning visit greets by
 *  name ("Hej Alva!") with an inline not-you link; the tutor asks for the
 *  name by voice after starting. Copy lives in web/src/locales/sv.ts. */
export default function Welcome({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId, action, onBegin, onNotYou, ignoreLastId }: Props) {
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

  const hello = !start.firstVisit ? (
    <p className="tp-hello">
      <span className="tp-hello-name">{start.bubble}</span>
      <button type="button" className="tp-notyou" onClick={onNotYou ?? start.showFirstVisit}>
        {start.notYou}
      </button>
    </p>
  ) : undefined;

  return <Hero band={band} hello={hello} start={{ label: start.ctaLabel, disabled: starting, onStart: onBegin ?? begin }} />;
}
