import { useState } from 'react';
import type { BandConfig } from '../bands';
import { getLastProfileId, newProfileId } from '../db';
import type { Profile } from '../db';
import { sv } from '../locales/sv';

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
};

function bubbleText(template: string, name: string): string {
  return template.replace('{name}', name);
}

/** Voice-first start. First visit: the companion, a static welcome bubble and
 *  one start button — no name field, no profile grid, no speaking animation
 *  before the call. The tutor asks for the name by voice after starting.
 *  Later visits assume the same student; the
 *  small not-you link and the menu's switch entry both return to
 *  the nameless first-visit page. Profiles stay in browser storage. Copy lives
 *  in web/src/locales/sv.ts (band.* keys). */
export default function Welcome({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId }: Props) {
  const lastId = getLastProfileId();
  const assumed =
    (assumeId ? profiles.find((p) => p.id === assumeId) : undefined) ??
    profiles.find((p) => p.id === lastId && p.name.trim() !== '') ??
    null;
  const [showFirst, setShowFirst] = useState(false);
  const firstVisit = startOpen || showFirst || !assumed || assumed.name.trim() === '';

  function beginNameless() {
    if (starting) return;
    onStartGesture?.();
    // No stored profile yet: the call starts with no name, and the tutor's
    // set_learner_name tool creates (or attaches to) the stored profile by
    // voice early in the call. An aborted call leaves nothing behind.
    onPick({ id: newProfileId(), name: '', grade: null, notes: [], createdAt: Date.now() });
  }

  function beginAssumed(profile: Profile) {
    if (starting) return;
    onStartGesture?.();
    onPick(profile);
  }

  const copy = band.copy;
  return (
    <div className="ot-start">
      <div className="ot-start-companion" aria-hidden="true">
        <img
          src={band.companion.poses.greeting}
          alt=""
          onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
        />
      </div>
      {firstVisit ? (
        <>
          <p className="ot-start-bubble" role="status">
            {copy.welcomeBubble}
          </p>
          <button
            type="button"
            className="ot-start-btn"
            disabled={starting}
            onClick={beginNameless}
          >
            {starting ? sv['welcome.starting'] : copy.startButton}
          </button>
          <p className="ot-start-note">
            {sv['welcome.voiceNote']}
          </p>
        </>
      ) : (
        <>
          <p className="ot-start-bubble" role="status">
            {bubbleText(copy.returningBubble, assumed.name)}
          </p>
          <button
            type="button"
            className="ot-start-btn"
            disabled={starting}
            onClick={() => beginAssumed(assumed)}
          >
            {starting ? sv['welcome.starting'] : copy.startButton}
          </button>
          <p className="ot-start-note">
            <button type="button" className="ot-link-btn" onClick={() => setShowFirst(true)}>
              {bubbleText(copy.notYou, assumed.name)}
            </button>
          </p>
        </>
      )}
    </div>
  );
}
