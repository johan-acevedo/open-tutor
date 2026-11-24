import { useState } from 'react';
import type { BandConfig } from '../bands';
import { getLastProfileId, newProfileId } from '../db';
import type { Profile } from '../db';
import { sv } from '../locales/sv';

export type StartActionInput = {
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

export type StartAction = {
  /** Nameless first-visit view (no usable remembered learner). */
  firstVisit: boolean;
  /** Comic bubble text for this visit. */
  bubble: string;
  /** CTA label ("Startar…" while starting). */
  ctaLabel: string;
  /** Not-you link text for the returning view. */
  notYou: string;
  /** Start the call: audio unlock first, then pick the profile. */
  begin: () => void;
  /** Show the nameless first-visit view (not-you link, menu switch entry). */
  showFirstVisit: () => void;
};

/** Shared start decision for the landing hero CTA and the top bar ghost
 *  button: both fire the exact same begin (audio unlock before profile
 *  pick, so the order is identical wherever the call starts). Later visits
 *  assume the same student; the not-you link returns to the nameless
 *  first-visit view. */
export function useStartAction({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId }: StartActionInput): StartAction {
  const lastId = getLastProfileId();
  const assumed =
    (assumeId ? profiles.find((p) => p.id === assumeId) : undefined) ??
    profiles.find((p) => p.id === lastId && p.name.trim() !== '') ??
    null;
  const [showFirst, setShowFirst] = useState(false);
  const firstVisit = startOpen || showFirst || !assumed || assumed.name.trim() === '';

  function begin() {
    if (starting) return;
    onStartGesture?.();
    if (firstVisit || !assumed) {
      // No stored profile yet: the call starts with no name, and the tutor's
      // set_learner_name tool creates (or attaches to) the stored profile by
      // voice early in the call. An aborted call leaves nothing behind.
      onPick({ id: newProfileId(), name: '', grade: null, notes: [], createdAt: Date.now() });
      return;
    }
    onPick(assumed);
  }

  const copy = band.copy;
  return {
    firstVisit,
    bubble: firstVisit ? copy.welcomeBubble : copy.returningBubble.replace('{name}', assumed?.name ?? ''),
    ctaLabel: starting ? sv['welcome.starting'] : copy.startButton,
    notYou: copy.notYou.replace('{name}', assumed?.name ?? ''),
    begin,
    showFirstVisit: () => setShowFirst(true),
  };
}
