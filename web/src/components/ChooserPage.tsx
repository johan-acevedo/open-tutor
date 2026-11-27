import { useEffect, type ReactNode } from 'react';
import { BANDS, type BandId } from '../bands';
import { t } from '../locales/sv';
import { BandSections, Hero, PaperFooter, PaperMast, PaperPage, type StartProps } from './Paper';
import { stopGreeting } from './greetingAudio';

type Props = {
  /** Begin a call in this band (switches band in place, then starts). */
  onBegin: (band: BandId) => void;
  starting: boolean;
  /** In-app navigation for the band nav. */
  onNavigate?: (target: BandId) => void;
  /** The household menu, when the device remembers someone (App decides). */
  menu?: ReactNode;
};

/** The front door (/) for a first visit: the Åk 1–6 page in the parent
 *  voice (Räven). The other audiences are one tap away in the masthead's
 *  band nav; there is no switch inside the hero. */
export default function ChooserPage({ onBegin, starting, onNavigate, menu }: Props) {
  const band = BANDS.primary;
  // Leaving the front door stops the hello, so it never keeps playing under
  // a different companion.
  useEffect(() => () => stopGreeting(), []);
  const start: StartProps = {
    label: starting ? t('welcome.starting') : band.copy.startButton,
    disabled: starting,
    onStart: () => {
      // Starting the call stops the greeting clip first.
      stopGreeting();
      onBegin('primary');
    },
  };
  return (
    <PaperPage>
      <PaperMast active="primary" onNavigate={onNavigate} right={menu} />
      <main>
        <Hero band={band} start={start} />
        <BandSections band={band} start={start} />
      </main>
      <PaperFooter />
    </PaperPage>
  );
}
