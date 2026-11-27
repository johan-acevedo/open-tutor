import { useRef, useState } from 'react';
import { BAND_PATHS, type BandConfig, type BandId } from '../bands';
import { bandUrl } from '../bandLinks';
import type { Profile } from '../db';
import { t } from '../locales/sv';
import Welcome from './Welcome';
import StartMenu, { type StartPanel } from './StartMenu';
import { useStartAction } from './useStartAction';
import { audienceOf, PaperFooter, PaperMast, PaperPage, PriceSection, QuietLinks, SectionLink, StepsSection, type QuietLink } from './Paper';

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
  /** Menu switch entry: open the household picker. */
  onSwitch: () => void;
  /** "Inte {name}?": open the household picker instead of the nameless view. */
  onNotYou?: () => void;
  /** On a band route: never assume a learner remembered from another band. */
  ignoreLastId?: boolean;
  /** Quiet cross-links: navigate in place instead of reloading. Only used on
   *  talarum-style hosts (no tutor.* prefix); on band hosts the links keep
   *  their href and the browser does the full load. */
  onBandLink?: (target: BandId | '/') => void;
}

function href(target: BandId): string {
  try {
    return bandUrl(target, window.location.href);
  } catch {
    return BAND_PATHS[target];
  }
}

/** The quiet links under each band page. Gymnasiet speaks to adults, so it
 *  points younger siblings to the family front door only. */
function crossLinks(band: BandId): QuietLink[] {
  const primary: QuietLink = { lead: 'landing.crossPrimaryLead', label: 'landing.crossPrimaryLink', href: href('primary'), face: 'primary', target: 'primary' };
  const middle: QuietLink = { lead: 'landing.crossMiddleLead', label: 'landing.crossMiddleLink', href: href('middle'), face: 'middle', target: 'middle' };
  const upper: QuietLink = { lead: 'landing.crossUpperLead', label: 'landing.crossUpperLink', href: href('upper'), face: 'upper', target: 'upper' };
  if (band === 'primary') return [middle, upper];
  if (band === 'middle') return [primary, upper];
  return [{ lead: 'landing.crossFamilyLead', label: 'landing.crossFamilyLink', href: '/', face: 'primary', target: '/' }];
}

/** A band page (/ak1-6, /hogstadiet, /gymnasiet, and / for a returning
 *  learner): masthead, hero, the planned price list, the steps, quiet
 *  cross-links and the footer. The menu keeps the switch entry and the
 *  short about and privacy notes. */
export default function LandingPage({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId, onSwitch, onNotYou, ignoreLastId, onBandLink }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [panel, setPanel] = useState<StartPanel>(null);
  const start = useStartAction({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId, ignoreLastId });
  const returnFocus = useRef<HTMLElement | null>(null);

  function changeMenuOpen(next: boolean) {
    setMenuOpen(next);
    if (!next && returnFocus.current?.isConnected) returnFocus.current.focus();
    if (!next) returnFocus.current = null;
  }

  return (
    <PaperPage>
      <PaperMast
        nav={
          <>
            <SectionLink to="sa-gar-det-till">{t('landing.howTitle')}</SectionLink>
            <SectionLink to="pris">{t('landing.navPrice')}</SectionLink>
            <a href="/integritet">{t('landing.headerPrivacy')}</a>
          </>
        }
        right={
          <StartMenu
            switchLabel={band.copy.switchStudent}
            onSwitch={onSwitch}
            open={menuOpen}
            onOpenChange={changeMenuOpen}
            panel={panel}
            onPanelChange={setPanel}
          />
        }
      />
      <main>
        <Welcome
          profiles={profiles}
          band={band}
          onPick={onPick}
          starting={starting}
          onStartGesture={onStartGesture}
          startOpen={startOpen}
          assumeId={assumeId}
          action={start}
          onNotYou={onNotYou}
          ignoreLastId={ignoreLastId}
        />
        <PriceSection audience={audienceOf(band.id)} />
        <StepsSection band={band} />
        <QuietLinks links={crossLinks(band.id)} onNavigate={onBandLink} />
      </main>
      <PaperFooter />
    </PaperPage>
  );
}
