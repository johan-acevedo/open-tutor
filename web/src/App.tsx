import { useCallback, useEffect, useRef, useState } from 'react';
import { layoutMode, mapAvatarState } from './avatarState';
import { BAND_PATHS, bandConfig, bandFromPath, bandFromSearch, explicitHostBand, normalizeAliasUrl, resolveBand, type BandId } from './bands';
import { bandUrl } from './bandLinks';
import { BandProvider } from './BandContext';
import { getLastProfileId, getLastProfileIdForBand, listProfiles, newProfileId, rememberLastProfileId } from './db';
import type { Profile } from './db';
import { useSession } from './useSession';
import { initAnalytics, pageOpened } from './analytics';
import Brand from './components/Brand';
import LandingPage from './components/LandingPage';
import ChooserPage from './components/ChooserPage';
import HouseholdPicker from './components/HouseholdPicker';
import { PaperMast, PaperPage } from './components/Paper';
import { focusStartControl } from './focus';
import { stopGreeting } from './components/greetingAudio';
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

function locationBand(pathname: string): BandId {
  try {
    return resolveBand({
      hostname: window.location.hostname,
      search: window.location.search,
      pathname,
    });
  } catch {
    return 'primary';
  }
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
  // The route (URL path) is the source of truth: every navigation sets the
  // band from the new location, so the greeting, the companion and the
  // session request always agree on one band.
  const [band, setBand] = useState<BandId>(() => locationBand(pathOf()));
  const [route, setRoute] = useState<string>(() => pathOf());
  // Household picker overlay (siblings on one device) and a forced chooser
  // ("+ Någon ny" goes to the 3-card page even with remembered learners).
  const [pickerOpen, setPickerOpen] = useState(false);
  const [forceChooser, setForceChooser] = useState(false);
  const session = useSession(mobile, band);
  // The user chose or navigated to a band this page load (picker, chooser
  // card, cross-band link, Back): a late /api/config must not override it.
  const choseBandRef = useRef(false);
  const phaseRef = useRef(session.phase);
  phaseRef.current = session.phase;

  const navigate = useCallback((path: string, opts?: { keepPrefill?: boolean }) => {
    // The href owns the query: a cross-band link drops ?band=, so in-app
    // navigation lands on exactly the href's path+query, never with a
    // stale testing override attached.
    const qIndex = path.indexOf('?');
    const lower = (qIndex >= 0 ? path.slice(0, qIndex) : path).toLowerCase();
    const search = qIndex >= 0 ? path.slice(qIndex) : '';
    try {
      window.history.pushState(null, '', lower + search);
    } catch {
      /* ignore */
    }
    choseBandRef.current = true;
    // The paper pages scroll on the document: a new page starts at the top
    // (the privacy page's back button sits at the bottom).
    try {
      document.documentElement.scrollTop = 0;
      document.body.scrollTop = 0;
    } catch {
      /* ignore */
    }
    // An explicit user navigation wins over a pending in-call-switch
    // prefill and clears it; the prefill effect's own redirect keeps it.
    if (!opts?.keepPrefill) session.clearPrefill();
    setRoute(lower);
    setBand(locationBand(lower));
    setPickerOpen(false);
  }, [session.clearPrefill]);

  // Alias paths (/raven, /lodjuret, /bjornen, /vuxen, /studier) normalize to the
  // canonical band path without a reload or a history entry. The query
  // string and fragment survive: ?band= and #anchors are not dropped.
  useEffect(() => {
    let search = '';
    let hash = '';
    let pathname = route;
    try {
      search = window.location.search || '';
      hash = window.location.hash || '';
      pathname = window.location.pathname || route;
    } catch {
      /* ignore */
    }
    const normalized = normalizeAliasUrl(pathname, search, hash);
    if (normalized) {
      try {
        window.history.replaceState(null, '', normalized);
      } catch {
        /* ignore */
      }
      setRoute(BAND_PATHS[bandFromPath(pathname) ?? 'primary']);
    }
  }, [route]);

  useEffect(() => {
    const onPop = () => {
      // Back/Forward restores the URL, but the band stays fixed while a
      // call is underway: the session request and the profile writes
      // already captured the call band, so a Back press must not move the
      // theme under a connecting/live/ending screen. The band follows the
      // URL again once back on the start pages (profiles) or the end card.
      const next = pathOf();
      choseBandRef.current = true;
      setRoute(next);
      if (phaseRef.current === 'profiles' || phaseRef.current === 'ended') {
        setBand(locationBand(next));
      }
      // Back on the start pages is an explicit navigation: a pending switch
      // prefill loses. During a call it must survive: an acknowledged in-call
      // switch lands on the prefilled learner when the room closes.
      if (phaseRef.current === 'profiles' || phaseRef.current === 'ended') session.clearPrefill();
      setPickerOpen(false);
      setForceChooser(false);
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
    // session.clearPrefill is a stable callback; the listener never re-subscribes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Back during a call keeps the call band (see onPop). When the start page
  // or end card returns (call ended, or the start request failed), the band
  // follows the URL again, so the page never shows one band under another
  // band's path.
  useEffect(() => {
    if (session.phase !== 'profiles' && session.phase !== 'ended') return;
    let named: BandId | null = null;
    try {
      named = bandFromSearch(window.location.search) ?? bandFromPath(route);
    } catch {
      named = null;
    }
    if (named && named !== band) setBand(named);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.phase, route]);

  // Server-advertised default band (TUTOR_BAND, via /api/config): only for
  // testing on hosts whose name picks no band, and only when nothing else
  // names one. Ignored once the user has chosen (or a call is underway): a
  // late response must never switch the theme under a connecting screen.
  useEffect(() => {
    let cancelled = false;
    fetch('/api/config')
      .then((res) => (res.ok ? res.json() : null))
      .then((config: { band?: string } | null) => {
        if (cancelled || choseBandRef.current) return;
        if (phaseRef.current !== 'profiles') return;
        let named: BandId | null = null;
        try {
          named =
            bandFromSearch(window.location.search) ??
            bandFromPath(window.location.pathname) ??
            explicitHostBand(window.location.hostname);
        } catch {
          return;
        }
        if (named) return;
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
  // After the picker closes onto a new start view (pick or "+ Någon ny"),
  // move focus to that view's start control.
  const focusStartAfterPickerRef = useRef(false);
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

  // The start pages are warm light paper; the call views stay dark. The
  // browser chrome follows (index.html carries the paper default).
  const paperView = phase === 'profiles';
  useEffect(() => {
    try {
      document.querySelector('meta[name="theme-color"]')?.setAttribute('content', paperView ? '#f6f1e7' : '#171411');
    } catch {
      /* ignore */
    }
    // Paper pages scroll on the document (iOS URL-bar collapse, status-bar
    // tap to top); the call view keeps its fixed viewport (paper.css).
    try {
      document.documentElement.classList.toggle('ot-doc-scroll', paperView);
    } catch {
      /* ignore */
    }
  }, [paperView]);

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

  /** Band nav: a band page, or the front door (/) for Åk 1–6. Same target
   *  as the rendered href, so other query parameters stay. On / a
   *  remembered Åk 1–6 learner is greeted by name; anyone else gets the
   *  nameless front door (never another band's companion under "Åk 1–6"). */
  function navigateTo(target: BandId | '/') {
    if (target === '/' || target === 'primary') {
      const lastId = getLastProfileIdSafe();
      const learner = lastId ? profiles.find((p) => p.id === lastId && p.name.trim() !== '') : undefined;
      setForceChooser(!learner || (learner.band ?? 'primary') !== 'primary');
      try {
        const url = new URL(window.location.href);
        url.pathname = '/';
        url.searchParams.delete('band');
        navigate(url.pathname + url.search);
      } catch {
        navigate('/');
      }
      return;
    }
    try {
      const url = new URL(bandUrl(target, window.location.href));
      navigate(url.pathname + url.search);
    } catch {
      navigate(BAND_PATHS[target]);
    }
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
    choseBandRef.current = true;
    // A card start stops the greeting clip first (see LandingPage.begin).
    stopGreeting();
    session.prepareStart();
    if (target !== band) setBand(target);
    beginCall({ id: newProfileId(), name: '', grade: null, band: target, notes: [], createdAt: Date.now() }, target);
  }

  /** Household picker choice: the picked profile and its band drive the
   *  route, the greeting and the start request together, as one piece of
   *  state. Showing their band view in place is not enough: the URL path
   *  must name the band too, or the greeting and request disagree. A legacy
   *  profile without a band stays in the current band; remembering it under
   *  that band's key (not just overall) is what makes the greeting and the
   *  start request theirs instead of the previously remembered learner's. */
  function pickHousehold(p: Profile) {
    const target = p.band ?? band;
    rememberLastProfileId(p.id, target);
    setPickerOpen(false);
    setForceChooser(false);
    session.clearProfilesOpen();
    focusStartAfterPickerRef.current = true;
    choseBandRef.current = true;
    if (BAND_PATHS[target] !== route) navigate(BAND_PATHS[target]);
    else if (target !== band) setBand(target);
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
    focusStartAfterPickerRef.current = true;
    if (route !== '/') navigate('/');
    setForceChooser(true);
  }

  // After the picker closes onto a new start view, move focus to that
  // view's start control (the opener is gone with the old view).
  useEffect(() => {
    if (pickerOpen || !focusStartAfterPickerRef.current) return;
    focusStartAfterPickerRef.current = false;
    focusStartControl();
  }, [pickerOpen]);

  // After an in-call switch the prefilled learner's band drives the route,
  // the same rule as a picker choice: B's greeting, companion and start
  // request must agree, not A's route with B's name.
  useEffect(() => {
    if (phase !== 'profiles' || pickerOpen) return;
    const prefillId = session.prefillId;
    if (!prefillId) return;
    const next = profiles.find((pr) => pr.id === prefillId);
    const target = next?.band;
    if (!target) return;
    choseBandRef.current = true;
    // The prefill redirect keeps the prefill: it is the navigation the
    // prefill itself asked for. Any other navigation clears it (see navigate).
    if (BAND_PATHS[target] !== route) navigate(BAND_PATHS[target], { keepPrefill: true });
    else if (target !== band) setBand(target);
    // navigate / pickHousehold own their deps; profiles/route/band re-run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, pickerOpen, session.prefillId, profiles, route, band]);

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
      // The band's remembered learner counts only while they still belong
      // to this band: a legacy learner picked here and later stamped with
      // another band (their first call ran there) is not assumed here.
      const perBand = getLastProfileIdForBand(routeBand);
      const perBandProfile = perBand ? profiles.find((p) => p.id === perBand) : undefined;
      assumeId = perBandProfile && (perBandProfile.band ?? routeBand) === routeBand ? perBand ?? undefined : undefined;
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
    // A pending in-call-switch prefill shows the prefilled learner's start
    // view, never the generic chooser: the prefill would be dropped.
    !session.prefillId &&
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
        <PrivacyPage onBack={() => navigate('/')} onNavigate={navigateTo} />
      )}

      {phase === 'profiles' && !isPrivacy && pickerOpen && (
        <PaperPage>
          <PaperMast onNavigate={navigateTo} />
          <main className="tp-wrap">
            <HouseholdPicker
              profiles={profiles}
              band={band}
              onPick={pickHousehold}
              onNew={pickerNew}
              onBack={() => {
                // Back also lands on a new start view (the opener is gone
                // with the old view), so focus moves to its start control
                // instead of falling back to <body>.
                focusStartAfterPickerRef.current = true;
                setPickerOpen(false);
                session.clearProfilesOpen();
              }}
            />
          </main>
        </PaperPage>
      )}

      {phase === 'profiles' && !isPrivacy && !pickerOpen && showChooser && (
        <ChooserPage onBegin={beginInBand} starting={false} onNavigate={navigateTo} />
      )}

      {phase === 'profiles' && !isPrivacy && !pickerOpen && !showChooser && (
        <LandingPage
          profiles={profiles}
          band={config}
          onPick={(p) => beginCall(p, band)}
          onStartGesture={session.prepareStart}
          starting={false}
          startOpen={session.profilesOpen}
          assumeId={assumeId}
          onSwitch={openPicker}
          onNotYou={openPicker}
          ignoreLastId={routeBand !== null}
          onBandLink={navigateTo}
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
