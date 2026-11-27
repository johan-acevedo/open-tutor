import { useRef, useState } from 'react';
import type { BandConfig, BandId } from '../bands';
import type { Profile } from '../db';
import Welcome from './Welcome';
import StartMenu, { type StartPanel } from './StartMenu';
import { useStartAction } from './useStartAction';
import { stopGreeting } from './greetingAudio';
import { BandSections, PaperFooter, PaperMast, PaperPage } from './Paper';

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
  /** Band nav: navigate in place instead of reloading. Only used on
   *  talarum-style hosts (no tutor.* prefix); on band hosts the links keep
   *  their href and the browser does the full load. */
  onBandLink?: (target: BandId) => void;
}

/** A band page (/ak1-6, /hogstadiet, /gymnasiet, and / for a returning
 *  learner): masthead with the band nav, hero, the three steps, the planned
 *  price, a closing call to action and the footer. The menu (switch entry,
 *  short about and privacy notes) shows only once this device remembers
 *  someone: a first visit has nothing to switch between. */
export default function LandingPage({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId, onSwitch, onNotYou, ignoreLastId, onBandLink }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [panel, setPanel] = useState<StartPanel>(null);
  const start = useStartAction({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId, ignoreLastId });
  const returnFocus = useRef<HTMLElement | null>(null);
  const remembers = profiles.some((p) => p.name.trim() !== '');

  function changeMenuOpen(next: boolean) {
    setMenuOpen(next);
    if (!next && returnFocus.current?.isConnected) returnFocus.current.focus();
    if (!next) returnFocus.current = null;
  }

  function begin() {
    stopGreeting();
    start.begin();
  }

  return (
    <PaperPage>
      <PaperMast
        active={band.id}
        onNavigate={onBandLink}
        right={
          remembers ? (
            <StartMenu
              switchLabel={band.copy.switchStudent}
              onSwitch={onSwitch}
              open={menuOpen}
              onOpenChange={changeMenuOpen}
              panel={panel}
              onPanelChange={setPanel}
            />
          ) : undefined
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
          onBegin={begin}
          onNotYou={onNotYou}
          ignoreLastId={ignoreLastId}
        />
        <BandSections band={band} start={{ label: start.ctaLabel, disabled: starting, onStart: begin }} />
      </main>
      <PaperFooter />
    </PaperPage>
  );
}
