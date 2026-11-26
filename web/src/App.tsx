import { useEffect, useRef, useState } from 'react';
import { layoutMode, mapAvatarState } from './avatarState';
import { bandConfig, currentBand, type BandId } from './bands';
import { BandProvider } from './BandContext';
import { listProfiles, rememberLastProfileId } from './db';
import type { Profile } from './db';
import { useSession } from './useSession';
import { initAnalytics, pageOpened } from './analytics';
import LandingPage from './components/LandingPage';
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
  // Age band for this page load: ?band= wins, else the remembered choice,
  // else the host (tutor2.* = middle school, tutor3.* = upper secondary + adults). A TUTOR_BAND set on
  // the server (/api/config) applies only when the page names no band.
  const [band, setBand] = useState<BandId>(() => {
    try {
      return currentBand(window.location.hostname, window.location.search);
    } catch {
      return 'primary';
    }
  });
  useEffect(() => {
    let cancelled = false;
    let hasOverride = false;
    try {
      hasOverride = new URLSearchParams(window.location.search).has('band');
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

  return (
    <BandProvider band={band}>
    <div
      data-band={band}
      className={`ot-root${mobile ? ' ot-phone' : ''}${phonePortrait ? ' ot-phone-portrait' : ''}${keyboard ? ' ot-keyboard' : ''}${inSession ? ' ot-in-session' : ''}`}
    >
      {phase !== 'profiles' && (
        <header className="ot-topbar">
          <div className="ot-topbar-inner">
            <div className="ot-land-brand">
              <span className="ot-land-mark" aria-hidden="true" />
              <span>Open Tutor</span>
            </div>
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

      {phase === 'profiles' && (
        <LandingPage
          profiles={profiles}
          band={config}
          onPick={(p) => {
            // A nameless start has no stored profile yet: the tutor's
            // set_learner_name tool remembers it once the name is known.
            if (p.name.trim() !== '') rememberLastProfileId(p.id);
            void session.start(p);
          }}
          onStartGesture={session.prepareStart}
          starting={false}
          startOpen={session.profilesOpen}
          assumeId={session.prefillId}
          onSwitch={session.showFirstVisit}
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
          onBack={session.backToProfiles}
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
