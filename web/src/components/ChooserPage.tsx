import { bandConfig, type BandId } from '../bands';
import { t } from '../locales/sv';
import Brand from './Brand';
import HomeChooser from './HomeChooser';
import { HowSteps, LandingFooter } from './LandingPage';

type Props = {
  /** Begin a call in this band (switches band in place, then starts). */
  onBegin: (band: BandId) => void;
  starting: boolean;
};

/** The single-domain front door: a quiet header (brand plus an Integritet
 *  link, visible before any call button), the three companion cards, the
 *  how-it-works steps and the footer. The header link is a plain text link,
 *  never a pill row above the headline. */
export default function ChooserPage({ onBegin, starting }: Props) {
  return (
    <div className="ot-land">
      <header className="ot-land-top">
        <div className="ot-land-topinner">
          <Brand />
          <div className="ot-land-topright">
            <a className="ot-choose-privacy" href="/integritet">
              {t('landing.headerPrivacy')}
            </a>
          </div>
        </div>
      </header>
      <div className="ot-land-scroll">
        <div className="ot-land-hero ot-land-hero-choose">
          <HomeChooser onBegin={onBegin} starting={starting} />
        </div>
        <HowSteps band={bandConfig('primary')} />
        <LandingFooter />
      </div>
    </div>
  );
}
