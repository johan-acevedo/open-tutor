import { BANDS, BAND_IDS } from '../bands';
import type { BandId } from '../bands';
import { t } from '../locales/sv';
import { stopGreeting, toggleGreeting, usePlayingGreetingBand } from './greetingAudio';

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

/** A calm round listen control on each portrait: dark frosted disc, cream
 *  speaker, apricot while that companion's clip plays. The comic "Hej!"
 *  bubble stays on the single-band pages, where there is one companion;
 *  three of them in a row competed with the three start buttons. */
function ListenIcon() {
  return (
    <span className="ot-choose-listen" aria-hidden="true">
      <svg className="ot-land-spk" viewBox="0 0 52 48">
        <path d="M6 18 H14 L25 9 V39 L14 30 H6 Z" fill="currentColor" stroke="currentColor" strokeWidth="3" strokeLinejoin="round" />
        <path d="M31 17 a10 10 0 0 1 0 14" fill="none" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" />
        <path d="M36 11 a18 18 0 0 1 0 26" fill="none" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" />
        <path d="M41 6 a26 26 0 0 1 0 36" fill="none" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" opacity=".55" />
      </svg>
    </span>
  );
}

/** The single-domain front door: one landing page with three equal-weight
 *  companion cards. Each card starts the call in one tap (the band switches
 *  in place first). The portrait is one big button that plays that
 *  companion's hello clip; the round speaker on it says so. */
export default function HomeChooser({ onBegin, starting }: Props) {
  const playingBand = usePlayingGreetingBand();
  return (
    <div className="ot-choose">
      <div className="ot-choose-head">
        {/* "prata med." never splits: a break lands before the accent word
            or earlier, never leaving "med." alone on a line. */}
        <h1 className="ot-land-title">
          {t('landing.titlePrefix')}
          <span className="ot-nowrap">
            <span className="ot-land-accent">{t('landing.titleAccent')}</span>
            {t('landing.titleSuffix')}
            <span className="ot-land-dot">{t('landing.titlePeriod')}</span>
          </span>
        </h1>
        <p className="ot-land-sub">{t('landing.unifiedIntro')}</p>
      </div>
      <h2 className="ot-sr-only">{t('landing.chooserTitle')}</h2>
      <ul className="ot-choose-cards">
        {BAND_IDS.map((id) => {
          const band = BANDS[id];
          const playing = playingBand === id;
          return (
            <li key={id} className="ot-choose-card" data-companion={id}>
              <button
                type="button"
                className={`ot-choose-portrait${playing ? ' is-playing' : ''}`}
                onClick={() => toggleGreeting(id)}
                aria-pressed={playing}
                aria-label={t('landing.listenAria', { greeting: band.copy.welcomeBubble, companion: band.companion.name })}
                title={t('landing.listenTitle', { companion: band.companion.name })}
              >
                <img className="ot-choose-fig" src={band.companion.hero} alt="" aria-hidden="true" />
                <ListenIcon />
              </button>
              <div className="ot-choose-body">
                <h3 className="ot-choose-aud">{t(AUDIENCE[id])}</h3>
                <p className="ot-choose-with">{t('landing.withCompanion', { companion: band.companion.name })}</p>
                <button
                  type="button"
                  className="ot-choose-cta"
                  disabled={starting}
                  onClick={() => {
                    // A card starts the call: stop the greeting clip first so
                    // no stale greeting keeps playing under the new session.
                    stopGreeting();
                    onBegin(id);
                  }}
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
                  {t(CTA[id])}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
