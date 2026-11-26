import { BANDS, BAND_IDS } from '../bands';
import type { BandId } from '../bands';
import { t } from '../locales/sv';
import { toggleGreeting } from './greetingAudio';

type Props = {
  /** Begin a call in this band (switches band in place, then starts). */
  onBegin: (band: BandId) => void;
  starting: boolean;
};

const AUDIENCE: Record<BandId, 'landing.audiencePrimary' | 'landing.audienceMiddle' | 'landing.audienceUpper'> = {
  primary: 'landing.audiencePrimary',
  middle: 'landing.audienceMiddle',
  upper: 'landing.audienceUpper',
};

const CTA: Record<BandId, 'band.primary.startButton' | 'band.middle.startButton' | 'band.upper.startButton'> = {
  primary: 'band.primary.startButton',
  middle: 'band.middle.startButton',
  upper: 'band.upper.startButton',
};

/** The single-domain front door: one landing page with three equal-weight
 *  companion cards. Each card starts the call in one tap (the band switches
 *  in place first). Tapping a face plays that companion's hello clip. */
export default function HomeChooser({ onBegin, starting }: Props) {
  return (
    <div className="ot-choose">
      <h1 className="ot-land-title">
        {t('landing.titlePrefix')}
        <span className="ot-land-accent">{t('landing.titleAccent')}</span>
        {t('landing.titleSuffix')}
        <span className="ot-land-dot">{t('landing.titlePeriod')}</span>
      </h1>
      <p className="ot-land-sub">{t('landing.unifiedIntro')}</p>
      <h2 className="ot-choose-title">{t('landing.chooserTitle')}</h2>
      <div className="ot-choose-cards">
        {BAND_IDS.map((id) => {
          const band = BANDS[id];
          return (
            <article key={id} className="ot-choose-card" data-band={id}>
              <button
                type="button"
                className="ot-choose-face"
                onClick={() => toggleGreeting(id)}
                aria-label={t('landing.listenAria', { greeting: band.copy.welcomeBubble, companion: band.companion.name })}
              >
                <img src={band.companion.face} alt="" aria-hidden="true" />
              </button>
              <div className="ot-choose-txt">
                <strong>{t(AUDIENCE[id])}</strong>
                <span>{t('landing.withCompanion', { companion: band.companion.name })}</span>
              </div>
              <button
                type="button"
                className="ot-land-cta ot-choose-cta"
                disabled={starting}
                onClick={() => onBegin(id)}
              >
                {t(CTA[id])}
              </button>
            </article>
          );
        })}
      </div>
    </div>
  );
}
