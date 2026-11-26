import { useCallback, useEffect, useRef, useState } from 'react';
import { layoutMode, mapAvatarState } from './avatarState';
import { BAND_PATHS, bandConfig, bandFromPath, currentBand, type BandId } from './bands';
import { BandProvider } from './BandContext';
import { getLastProfileId, getLastProfileIdForBand, listProfiles, newProfileId, rememberLastProfileId } from './db';
import type { Profile } from './db';
import { useSession } from './useSession';
import { initAnalytics, pageOpened } from './analytics';
import Brand from './components/Brand';
import LandingPage, { HowSteps, LandingFooter } from './components/LandingPage';
import HomeChooser from './components/HomeChooser';
import HouseholdPicker from './components/HouseholdPicker';
import PrivacyPage from './components/PrivacyPage';
import CallStage from './components/CallStage';
import BottomBar from './components/BottomBar';
import PhoneStage from './components/PhoneStage';
import TopMenu from './components/TopMenu';
import EndCard from './components/EndCard';
import HomeworkTray from './components/HomeworkTray';
import ScreenDemo from './components/ScreenDemo';
import { useViewport } from './useViewport';
import { usePhoneStage } from './phoneStage';
import { htmlLang, t } from './locales/sv';

function pathOf(): string {
  try {
    return (window.location.pathname || '/').toLowerCase();
  } catch {
    return '/';
  }
}

/** A tutor.* host names its band explicitly; any other host leaves the band
 *  to the path, ?band= or server default. */
function explicitHostBand(hostname: string): BandId | null {
  const host = (hostname || '').toLowerCase();
  if (host.startsWith('tutor2.')) return 'middle';
  if (host.startsWith('tutor3.')) return 'upper';
  if (host.startsWith('tutor.')) return 'primary';
  return null;
}

function canonicalPathFor(path: string): string | null {
  const band = bandFromPath(path);
  if (!band) return null;
  return BAND_PATHS[band];
}

export default function App() {
  // The page language follows the active locale (Swedish for now).
  useEffect(() => {
    try {
      document.documentElement.lang = htmlLang;
    } catch {
      /* ignore */
    }
  }, []);
  // Product analytics warm up once: a no-op until /api/config names a key.
  useEffect(() => {
    void initAnalytics().then(() => pageOpened());
  }, []);
  // Dev-only Smart Screen demo: ?screen-demo=1 shows two example pages with
  // patch/reveal/point buttons, no LiveKit session.
  const screenDemo = (() => {
    try {
      return new URLSearchParams(window.location.search).get('screen-demo') === '1';
    } catch {
      return false;
    }
  })();
  const { mobile, portrait, keyboard } = useViewport();
  // Single-domain flow (precedence: ?band= > path > host prefix >
  // server TUTOR_BAND > default). The band stays fixed during a call:
  // switching happens only on the start pages, in place, without reload.
  const [band, setBand] = useState<BandId>(() => {
    try {
      return currentBand(window.location.hostname, window.location.search, window.location.pathname);
    } catch {
      return 'primary';
    }
  });
  const [route, setRoute] = useState<string>(() => pathOf());
  // Household picker overlay (siblings on one device) and a forced chooser
  // ("+ Någon ny" goes to the 3-card page even with remembered learners).
  const [pickerOpen, setPickerOpen] = useState(false);
  const [forceChooser, setForceChooser] = useState(false);

  const navigate = useCallback((path: string) => {
    try {
      window.history.pushState(null, '', path);
    } catch {
      /* ignore */
    }
    setRoute(path.toLowerCase());
    setPickerOpen(false);
  }, []);

  // Alias paths (/raven, /lodjuret, /bjornen, /vuxen) normalize to the
  // canonical band path without a reload or a history entry.
  useEffect(() => {
    const canon = canonicalPathFor(route);
    if (canon && route !== canon) {
      try {
        window.history.replaceState(null, '', canon);
      } catch {
        /* ignore */
      }
      setRoute(canon);
    }
  }, [route]);

  useEffect(() => {
    const onPop = () => {
      setRoute(pathOf());
      setPickerOpen(false);
      setForceChooser(false);
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let hasOverride = false;
    try {
      hasOverride =
        new URLSearchParams(window.location.search).has('band') ||
        bandFromPath(window.location.pathname) !== null ||
        explicitHostBand(window.location.hostname) !== null;
    } catch {
      hasOverride = true;
    }
    if (hasOverride) return;
    fetch('/api/config')
      .then((res) => (res.ok ? res.json() : null))
      .then((config: { band?: string } | null) => {
        if (!cancelled && (config?.band === 'primary' || config?.band === 'middle' || config?.band === 'upper')) {
          setBand(config.band);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  const config = bandConfig(band);
  const session = useSession(mobile, band);
  // Narrow portrait phones get the two-view stage: big fox, or item + fox strip.
  const phonePortrait = mobile && portrait;
  const stage = usePhoneStage({
    hasItem: session.items.length > 0,
    itemSignal: session.boardSignal,
  });
  if (screenDemo) return <BandProvider band={band}><ScreenDemo /></BandProvider>;
  const { phase, profile } = session;
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const cameraRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (phase === 'profiles') {
      void listProfiles().then(setProfiles);
    }
  }, [phase]);

  // Menu "Byt elev" ends the call, then the household picker takes over from
  // the nameless start the session flow would otherwise show.
  useEffect(() => {
    if (phase === 'profiles' && session.profilesOpen && !pickerOpen) {
      session.clearProfilesOpen();
      setForceChooser(false);
      setPickerOpen(true);
    }
    // session.profilesOpen / clearProfilesOpen are stable enough.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, session.profilesOpen]);

  // On / with a remembered learner, open that learner's band view (theme +
  // companion follow them). Only on the start pages, never during a call.
  useEffect(() => {
    if (phase !== 'profiles' || pickerOpen || forceChooser) return;
    if (bandFromPath(route) !== null) return;
    if (route !== '/') return;
    const lastId = getLastProfileId();
    if (!lastId) return;
    const learner = profiles.find((p) => p.id === lastId && p.name.trim() !== '');
    if (learner?.band && learner.band !== band) setBand(learner.band);
  }, [phase, pickerOpen, forceChooser, profiles, route, band]);

  const inSession = phase === 'live' || phase === 'ending' || phase === 'connecting';
  const showBottomBar = phase === 'live' || phase === 'ending';
  const mode = layoutMode(session.items.length);
  const avatar = mapAvatarState({
    agentState: session.agentState,
    tutorMode: session.tutorMode,
    hasPending: session.items.some((i) => i.kind === 'pending'),
    hasSpokenFirst: session.hasSpokenFirst,
    isTeaching: mode === 'teaching',
    micBlocked: session.micBlocked,
  });

  function focusChatInput() {
    document.querySelector<HTMLInputElement>('.ot-chat-input')?.focus();
  }

  /** Start a call, stamping the band on a stored profile and remembering it
   *  overall and per band. A nameless start is remembered once the tutor
   *  learns the name by voice (see useSession applyName). */
  function beginCall(p: Profile, callBand: BandId) {
    if (p.name.trim() !== '') rememberLastProfileId(p.id, callBand);
    setForceChooser(false);
    setPickerOpen(false);
    void session.start(p, callBand);
  }

  /** One-tap start from a chooser card: switch band in place, then start
   *  exactly like the hero button (audio unlock first). */
  function beginInBand(target: BandId) {
    if (phase !== 'profiles') return;
    session.prepareStart();
    if (target !== band) setBand(target);
    beginCall({ id: newProfileId(), name: '', grade: null, band: target, notes: [], createdAt: Date.now() }, target);
  }

  /** Household picker choice: switch band/theme in place, show their start. */
  function pickHousehold(p: Profile) {
    const target = p.band ?? band;
    if (target !== band) setBand(target);
    rememberLastProfileId(p.id, p.band);
    setPickerOpen(false);
    setForceChooser(false);
    session.clearProfilesOpen();
  }

  function openPicker() {
    session.showFirstVisit();
    session.clearProfilesOpen();
    setForceChooser(false);
    setPickerOpen(true);
  }

  function pickerNew() {
    setPickerOpen(false);
    session.clearProfilesOpen();
    // "+ Någon ny" always lands on the 3-card chooser, nameless.
    if (route !== '/') navigate('/');
    setForceChooser(true);
  }

  const homeworkTray = session.homeworkDraft ? (
    <HomeworkTray
      draft={session.homeworkDraft}
      busy={session.homeworkSending}
      onCamera={() => cameraRef.current?.click()}
      onFiles={() => fileRef.current?.click()}
      onCancel={() => session.setHomeworkDraft(null)}
      onSend={() => void session.sendHomework()}
      onRemove={(index) => {
        const draft = session.homeworkDraft;
        if (draft?.kind !== 'files') return;
        const files = draft.files.filter((_, i) => i !== index);
        session.setHomeworkDraft(files.length ? { ...draft, files } : { kind: 'picker' });
      }}
    />
  ) : null;

  const isPrivacy = route === '/integritet';
  const routeBand = bandFromPath(route);
  // /integritet is its own page; everywhere else the profiles phase shows the
  // start pages below. On a band route the remembered learner of that band is
  // assumed (Hej {name}!); on / the overall last learner is assumed.
  let assumeId: string | null | undefined = session.prefillId;
  if (!assumeId && phase === 'profiles' && !isPrivacy) {
    if (routeBand) {
      assumeId = getLastProfileIdForBand(routeBand) ?? undefined;
      if (!assumeId) {
        const overall = (() => {
          try {
            return getLastProfileId();
          } catch {
            return null;
          }
        })();
        const match = overall ? profiles.find((p) => p.id === overall && p.name.trim() !== '' && (p.band ?? 'primary') === routeBand) : undefined;
        assumeId = match?.id;
      }
    }
  }
  function getLastProfileIdSafe(): string | null {
    try {
      return getLastProfileId();
    } catch {
      return null;
    }
  }

  const showChooser =
    phase === 'profiles' &&
    !isPrivacy &&
    !pickerOpen &&
    !routeBand &&
    (route === '/' ? (forceChooser || !profiles.some((p) => p.id === getLastProfileIdSafe() && p.name.trim() !== '')) : true);

  return (
    <BandProvider band={band}>
    <div
      data-band={band}
      className={`ot-root${mobile ? ' ot-phone' : ''}${phonePortrait ? ' ot-phone-portrait' : ''}${keyboard ? ' ot-keyboard' : ''}${inSession ? ' ot-in-session' : ''}`}
    >
      {phase !== 'profiles' && (
        <header className="ot-topbar">
          <div className="ot-topbar-inner">
            <Brand />
            {inSession && (
              <div className="ot-topbar-right">
                <TopMenu
                  items={session.items}
                  dragOver={session.dragOver}
                  onCamera={() => cameraRef.current?.click()}
                  onFiles={() => fileRef.current?.click()}
                  onSwitchStudent={() => void session.leaveToProfiles()}
                  switchLabel={config.copy.switchStudent}
                />
              </div>
            )}
          </div>
        </header>
      )}

      {phase === 'profiles' && isPrivacy && (
        <PrivacyPage onBack={() => navigate('/')} />
      )}

      {phase === 'profiles' && !isPrivacy && pickerOpen && (
        <div className="ot-land">
          <header className="ot-land-top">
            <div className="ot-land-topinner">
              <Brand />
            </div>
          </header>
          <div className="ot-land-scroll">
            <HouseholdPicker
              profiles={profiles}
              band={routeBand ?? band}
              onPick={pickHousehold}
              onNew={pickerNew}
              onBack={() => {
                setPickerOpen(false);
                session.clearProfilesOpen();
              }}
            />
          </div>
        </div>
      )}

      {phase === 'profiles' && !isPrivacy && !pickerOpen && showChooser && (
        <div className="ot-land">
          <header className="ot-land-top">
            <div className="ot-land-topinner">
              <Brand />
            </div>
          </header>
          <div className="ot-land-scroll">
            <div className="ot-land-hero ot-land-hero-choose">
              <HomeChooser onBegin={beginInBand} starting={false} />
            </div>
            <HowSteps band={bandConfig('primary')} />
            <LandingFooter />
          </div>
        </div>
      )}

      {phase === 'profiles' && !isPrivacy && !pickerOpen && !showChooser && (
        <LandingPage
          profiles={profiles}
          band={config}
          onPick={(p) => beginCall(p, routeBand ?? band)}
          onStartGesture={session.prepareStart}
          starting={false}
          startOpen={session.profilesOpen}
          assumeId={assumeId}
          onSwitch={openPicker}
          onNotYou={openPicker}
          ignoreLastId={routeBand !== null}
        />
      )}

      {phase === 'connecting' && (
        <div className="ot-endcard" role="status">
          <p>{t('app.connecting')}</p>
        </div>
      )}

      {(phase === 'live' || phase === 'ending') && profile && phonePortrait && (
        <PhoneStage
          learnerName={profile.name}
          items={session.items}
          focused={session.focused}
          mode={mode}
          // The homework tray lives on the board surface, so it needs the item view.
          stage={session.homeworkDraft ? { ...stage, view: 'item', foxView: false } : stage}
          pose={avatar.pose}
          pill={avatar.pill}
          caption={session.caption}
          captionFading={session.captionFading}
          activeItemId={session.activeItemId}
          onItemMounted={session.onItemMounted}
          onResourceClosed={(id) => void session.resourceClosed(id)}
          onItemFailed={session.onItemFailed}
          registerPageFrame={session.registerPageFrame}
          onPageAnswer={session.sendPageAnswer}
          overlay={homeworkTray}
        />
      )}

      {(phase === 'live' || phase === 'ending') && profile && !phonePortrait && (
        <CallStage
          learnerName={profile.name}
          items={session.items}
          focused={session.focused}
          mode={mode}
          pose={avatar.pose}
          pill={avatar.pill}
          caption={session.caption}
          captionFading={session.captionFading}
          activeItemId={session.activeItemId}
          onItemMounted={session.onItemMounted}
          onResourceClosed={(id) => void session.resourceClosed(id)}
          onItemFailed={session.onItemFailed}
          registerPageFrame={session.registerPageFrame}
          onPageAnswer={session.sendPageAnswer}
          overlay={homeworkTray}
        />
      )}

      {phase === 'ended' && profile && (
        <EndCard
          learnerName={profile.name}
          notes={session.sessionNotes.length > 0 ? session.sessionNotes : profile.notes.slice(-3)}
          onBack={() => {
            const target = profile.band ? BAND_PATHS[profile.band] : '/';
            session.backToProfiles();
            if (target !== route) navigate(target);
          }}
          band={profile.band ?? band}
          endReason={session.endReason}
        />
      )}

      {session.micBlocked && showBottomBar && (
        <div className="ot-banner ot-banner-amber" role="alert">
          <span aria-hidden="true">⚠️</span>
          <span>{t('app.micBlockedText')}</span>
          <button
            type="button"
            onClick={() => {
              void session.retryMic().then(() => focusChatInput());
            }}
          >
            {t('app.retry')}
          </button>
        </div>
      )}
      {(session.audioBlocked || session.resumeNeeded) && showBottomBar && (
        <div className="ot-banner ot-banner-amber" role="alert">
          <button type="button" onClick={() => void session.resumeMedia()}>
            {session.resumeNeeded ? t('app.resumeContinue') : t('app.resumeListen')}
          </button>
        </div>
      )}

      {session.connBanner === 'reconnecting' && (
        <div className="ot-banner ot-banner-amber" role="alert">
          <span>{t('app.reconnecting')}</span>
        </div>
      )}

      {session.connBanner === 'disconnected' && (
        <div className="ot-banner ot-banner-amber" role="alert">
          <span>{t('app.disconnected')}</span>
          <button type="button" onClick={() => profile && void session.start(profile)}>
            {t('app.restart')}
          </button>
        </div>
      )}

      {phase === 'ending' && (
        <div className="ot-banner ot-banner-info" role="status">
          <span>{t('app.ending')}</span>
        </div>
      )}

      {session.toast && (
        <div className="ot-toast" role="alert">
          {session.toast}
        </div>
      )}

      {session.lastSent && showBottomBar && <div className="ot-sent-chip">{t('app.youPrefix')} {session.lastSent}</div>}

      {showBottomBar && (
        <BottomBar
          micEnabled={session.micEnabled}
          mobile={mobile}
          micBlocked={session.micBlocked}
          sending={session.sending || phase === 'ending'}
          ending={phase === 'ending'}
          onSendText={(t) => void session.sendChat(t)}
          onToggleMic={() => void session.toggleMic()}
          onAttach={() => (mobile ? session.setHomeworkDraft({ kind: 'picker' }) : fileRef.current?.click())}
          onEnd={() => void session.endSession()}
        />
      )}

      <input
        ref={fileRef}
        type="file"
        hidden
        aria-hidden="true"
        tabIndex={-1}
        accept="image/*,.pdf,application/pdf"
        multiple
        onChange={(e) => {
          if (e.target.files && e.target.files.length > 0) {
            if (mobile) session.queueFiles(e.target.files);
            else void session.addFiles(e.target.files, 'photo');
          }
          e.target.value = '';
        }}
      />
      <input
        ref={cameraRef}
        type="file"
        hidden
        accept="image/*"
        capture="environment"
        aria-label={t('app.cameraInputAria')}
        onChange={(event) => {
          if (event.target.files?.length) session.queueFiles(event.target.files);
          event.target.value = '';
        }}
      />
      <audio ref={session.audioRef} aria-hidden="true" autoPlay />
    </div>
    </BandProvider>
  );
}
