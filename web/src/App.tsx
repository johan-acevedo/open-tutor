import { useEffect, useRef, useState } from 'react';
import { layoutMode, mapAvatarState } from './avatarState';
import { listProfiles } from './db';
import type { Profile } from './db';
import { useSession } from './useSession';
import ProfilePicker from './components/ProfilePicker';
import Avatar from './components/Avatar';
import Board from './components/Board';
import ScreenBoard from './components/ScreenBoard';
import BottomBar from './components/BottomBar';
import TopMenu from './components/TopMenu';
import EndCard from './components/EndCard';
import HomeworkTray from './components/HomeworkTray';
import { useViewport } from './useViewport';

export default function App() {
  const { mobile, keyboard } = useViewport();
  const session = useSession(mobile);
  const { phase, profile } = session;
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const cameraRef = useRef<HTMLInputElement | null>(null);
  const [smallCompanion, setSmallCompanion] = useState(false);

  useEffect(() => {
    if (phase === 'profiles') {
      void listProfiles().then(setProfiles);
    }
  }, [phase]);

  const inSession = phase === 'live' || phase === 'ending' || phase === 'connecting';
  const showBottomBar = phase === 'live' || phase === 'ending';
  const mode = layoutMode(session.screenDeck?.pages.length ?? session.items.length);
  const avatar = mapAvatarState({
    agentState: session.agentState,
    tutorMode: session.tutorMode,
    hasPending: session.screenBusy || session.items.some((i) => i.kind === 'pending'),
    hasSpokenFirst: session.hasSpokenFirst,
    isTeaching: mode === 'teaching',
    micBlocked: session.micBlocked,
  });

  function focusChatInput() {
    document.querySelector<HTMLInputElement>('.ot-chat-input')?.focus();
  }

  return (
    <div
      className={`ot-root${mobile ? ' ot-phone' : ''}${keyboard ? ' ot-keyboard' : ''}${smallCompanion ? ' ot-small-companion' : ''}${inSession ? ' ot-in-session' : ''}`}
    >
      <header className="ot-topbar">
        <div className="ot-wordmark">Open Tutor</div>
        <div className="ot-topbar-right">
          {inSession && (
            <button type="button" className="ot-end-btn ot-end-top" onClick={() => void session.endSession()} aria-label="Avsluta sessionen">
              Avsluta
            </button>
          )}
          {inSession && (
            <TopMenu
              items={session.items}
              dragOver={session.dragOver}
              onCamera={() => cameraRef.current?.click()}
              onFiles={() => fileRef.current?.click()}
            />
          )}
        </div>
      </header>

      {phase === 'profiles' && (
        <ProfilePicker
          profiles={profiles}
          onPick={(p) => void session.start(p)}
          onStartGesture={session.prepareStart}
          starting={false}
        />
      )}

      {phase === 'connecting' && (
        <div className="ot-endcard" role="status">
          <p>Ansluter till tutorn…</p>
        </div>
      )}

      {(phase === 'live' || phase === 'ending') && profile && (
        <main className={`ot-main ot-main-${mode}${session.screenDeck?.pages.length ? ' ot-main-screen' : ''}`}>
          <section className="ot-board" aria-label="Whiteboard">
            {session.screenDeck ? (
              <ScreenBoard
                learnerName={profile.name}
                snapshot={session.screenDeck}
                busy={session.screenBusy}
                onAttachCanvas={session.attachScreenCanvas}
                onDraft={session.setScreenAnswerDraft}
                onSubmit={session.submitScreenAnswer}
                onGoTo={session.goToScreenPage}
              />
            ) : (
              <Board
                learnerName={profile.name}
                items={session.items}
                focused={session.focused}
                onItemMounted={session.onItemMounted}
                onResourceClosed={(id) => void session.resourceClosed(id)}
                mobile={mobile}
                activeItemId={session.activeItemId}
                onEnd={() => void session.endSession()}
              />
            )}
            {session.homeworkDraft && (
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
            )}
          </section>
          <aside className="ot-avatar-col" aria-label="Tutor">
            <Avatar
              pose={avatar.pose}
              pill={avatar.pill}
              caption={session.caption}
              captionFading={session.captionFading}
              compact={smallCompanion}
              onToggleSize={mobile ? () => setSmallCompanion((small) => !small) : undefined}
            />
          </aside>
        </main>
      )}

      {phase === 'ended' && profile && (
        <EndCard
          learnerName={profile.name}
          notes={session.sessionNotes.length > 0 ? session.sessionNotes : profile.notes.slice(-3)}
          onBack={session.backToProfiles}
        />
      )}

      {session.micBlocked && showBottomBar && (
        <div className="ot-banner ot-banner-amber" role="alert">
          <span aria-hidden="true">⚠️</span>
          <span>Jag hör dig inte just nu. Du kan skriva här under.</span>
          <button
            type="button"
            onClick={() => {
              void session.retryMic().then(() => focusChatInput());
            }}
          >
            Försök igen
          </button>
        </div>
      )}
      {(session.audioBlocked || session.resumeNeeded) && showBottomBar && (
        <div className="ot-banner ot-banner-amber" role="alert">
          <button type="button" onClick={() => void session.resumeMedia()}>
            {session.resumeNeeded ? 'Fortsätt samtalet' : 'Tryck för att höra mig'}
          </button>
        </div>
      )}

      {session.connBanner === 'reconnecting' && (
        <div className="ot-banner ot-banner-amber" role="alert">
          <span>Tappade kontakten – försöker igen…</span>
        </div>
      )}

      {session.connBanner === 'disconnected' && (
        <div className="ot-banner ot-banner-amber" role="alert">
          <span>Tappade kontakten.</span>
          <button type="button" onClick={() => profile && void session.start(profile)}>
            Starta igen
          </button>
        </div>
      )}

      {phase === 'ending' && (
        <div className="ot-banner ot-banner-info" role="status">
          <span>Avslutar samtalet…</span>
        </div>
      )}

      {session.toast && (
        <div className="ot-toast" role="alert">
          {session.toast}
        </div>
      )}

      {session.lastSent && showBottomBar && <div className="ot-sent-chip">Du: {session.lastSent}</div>}

      {showBottomBar && (
        <BottomBar
          micEnabled={session.micEnabled}
          mobile={mobile}
          micBlocked={session.micBlocked}
          sending={session.sending || phase === 'ending'}
          onSendText={(t) => void session.sendChat(t)}
          onToggleMic={() => void session.toggleMic()}
          onAttach={() => (mobile ? session.setHomeworkDraft({ kind: 'picker' }) : fileRef.current?.click())}
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
        aria-label="Fota läxan"
        onChange={(event) => {
          if (event.target.files?.length) session.queueFiles(event.target.files);
          event.target.value = '';
        }}
      />
      <audio ref={session.audioRef} aria-hidden="true" autoPlay />
    </div>
  );
}
