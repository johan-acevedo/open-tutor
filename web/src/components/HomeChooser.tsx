import { useState } from 'react';
import { BANDS } from '../bands';
import type { BandId } from '../bands';
import { t } from '../locales/sv';
import { ListenButton, Notebook, PaperTitle, PriceAnchor, StartButton } from './Paper';
import { stopGreeting } from './greetingAudio';

/** The two grundskola companions on the front door. Gymnasiet and adults
 *  have their own page (/gymnasiet), linked quietly further down. */
export const FAMILY_BANDS: BandId[] = ['primary', 'middle'];

const AUDIENCE = { primary: 'landing.audiencePrimary', middle: 'landing.audienceMiddle', upper: 'landing.crossUpperLink' } as const;

type Props = {
  /** Begin a call in this band (switches band in place, then starts). */
  onBegin: (band: BandId) => void;
  starting: boolean;
  /** Controlled selection (ChooserPage lets the steps follow it). */
  band?: BandId;
  onBandChange?: (band: BandId) => void;
};

/** Front door hero for grundskola families: the headline, a discreet
 *  two-way switch (Åk 1–6 · Räven | Högstadiet · Lodjuret), one dark start
 *  button that begins the call in one tap, a quiet listen control, the
 *  honest price anchor, and the squared exercise book that follows the
 *  switch. */
export default function HomeChooser({ onBegin, starting, band: bandProp, onBandChange }: Props) {
  const [inner, setInner] = useState<BandId>('primary');
  const selected = bandProp ?? inner;
  const band = BANDS[selected];

  function choose(next: BandId) {
    if (next === selected) return;
    // A different companion: its predecessor's hello must not keep playing.
    stopGreeting();
    if (bandProp === undefined) setInner(next);
    onBandChange?.(next);
  }

  return (
    <header className="tp-hero tp-wrap">
      <div className="tp-hero-copy">
        <PaperTitle prefix="landing.familyTitlePrefix" accent="landing.familyTitleAccent" suffix="landing.familyTitleSuffix" />
        <p className="tp-lede">{t('landing.familyIntro')}</p>
        <div className="tp-switch" role="group" aria-label={t('landing.switchLabel')}>
          {FAMILY_BANDS.map((id) => (
            <button
              key={id}
              type="button"
              className="tp-switch-opt"
              aria-pressed={id === selected}
              aria-label={`${t(AUDIENCE[id])} · ${BANDS[id].companion.name}`}
              onClick={() => choose(id)}
            >
              <span>{t(AUDIENCE[id])}</span>
              <span className="tp-switch-sep" aria-hidden="true"> · </span>
              <span className="tp-switch-who">{BANDS[id].companion.name}</span>
            </button>
          ))}
        </div>
        <div className="tp-cta-area">
          <div className="tp-cta-row">
            <StartButton
              band={band}
              label={starting ? t('welcome.starting') : band.copy.startButton}
              disabled={starting}
              onClick={() => {
                // Starting the call stops the greeting clip first, so no
                // stale hello keeps playing under the new session.
                stopGreeting();
                onBegin(selected);
              }}
            />
            <ListenButton band={band} greeting={band.copy.welcomeBubble} />
          </div>
          <PriceAnchor />
        </div>
      </div>
      <Notebook band={band} />
    </header>
  );
}
