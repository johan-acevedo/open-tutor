import { useState } from 'react';
import { BANDS, BAND_PATHS, type BandId } from '../bands';
import { t } from '../locales/sv';
import HomeChooser from './HomeChooser';
import { PaperFooter, PaperMast, PaperPage, PriceSection, QuietLinks, SectionLink, StepsSection } from './Paper';

type Props = {
  /** Begin a call in this band (switches band in place, then starts). */
  onBegin: (band: BandId) => void;
  starting: boolean;
  /** In-app navigation for the quiet /gymnasiet link. */
  onNavigate?: (target: BandId | '/') => void;
};

/** The front door (/) speaks to grundskola families only: the hero with the
 *  two-way switch, the planned price list, the three steps, and one quiet
 *  link for upper-secondary students and adults. The header's Integritet
 *  link is a plain text link, never a pill row above the headline. */
export default function ChooserPage({ onBegin, starting, onNavigate }: Props) {
  const [band, setBand] = useState<BandId>('primary');
  return (
    <PaperPage>
      <PaperMast
        nav={
          <>
            <SectionLink to="sa-gar-det-till">{t('landing.howTitle')}</SectionLink>
            <SectionLink to="pris">{t('landing.navPrice')}</SectionLink>
          </>
        }
        right={
          <a className="tp-mast-link" href="/integritet">
            {t('landing.headerPrivacy')}
          </a>
        }
      />
      <main>
        <HomeChooser onBegin={onBegin} starting={starting} band={band} onBandChange={setBand} />
        <PriceSection audience="family" />
        <StepsSection band={BANDS[band]} />
        <QuietLinks
          onNavigate={onNavigate}
          links={[
            { lead: 'landing.crossUpperLead', label: 'landing.crossUpperLink', href: BAND_PATHS.upper, face: 'upper', target: 'upper' },
          ]}
        />
      </main>
      <PaperFooter />
    </PaperPage>
  );
}
