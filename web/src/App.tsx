import { useEffect, useRef, useState } from 'react';
import { layoutMode, mapAvatarState } from './avatarState';
import { listProfiles } from './db';
import type { Profile } from './db';
import { useSession } from './useSession';
import ProfilePicker from './components/ProfilePicker';
import Avatar from './components/Avatar';
import Board from './components/Board';
import BottomBar from './components/BottomBar';
import EndCard from './components/EndCard';

function pillLabel(p: Profile): string {
  return p.grade <= 9 ? `${p.name} · åk ${p.grade}` : `${p.name} · gy ${p.grade - 9}`;
}

export default function App() {
  const session = useSession();
  const { phase, profile } = session;
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (phase === 'profiles') {
      void listProfiles().then(setProfiles);
    }
  }, [phase]);

  const inSession = phase === 'live' || phase === 'ending' || phase === 'connecting';
  const showBottomBar = phase === 'live' || phase === 'ending';
  const mode = layoutMode(session.items.length);
  const lastTopic = profile && profile.notes.length > 0 ? (profile.notes[profile.notes.length - 1].topic ?? null) : null;

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

  return (
    <div className="ot-root">
      <header className="ot-topbar">
        <div className="ot-wordmark">Open Tutor</div>
        {profile && inSession && (
          <div className="ot-learner-pill" aria-label="Inloggad profil">
            {pillLabel(profile)}
          </div>
        )}
      </header>

      {phase === 'profiles' && (
        <ProfilePicker profiles={profiles} onPick={(p) => void session.start(p)} starting={false} />
      )}

      {phase === 'connecting' && (
        <div className="ot-endcard" role="status">
          <p>Ansluter till tutorn…</p>
        </div>
      )}

      {(phase === 'live' || phase === 'ending') && profile && (
        <main className={`ot-main ot-main-${mode}`}>
          <section className="ot-board" aria-label="Whiteboard">
            <Board
              learnerName={profile.name}
              lastTopic={lastTopic}
              items={session.items}
              focused={session.focused}
              onItemMounted={session.onItemMounted}
              onDiagramRendered={session.onDiagramRendered}
              onResourceClosed={(id) => void session.resourceClosed(id)}
              dragOver={session.dragOver}
            />
          </section>
          <aside className="ot-avatar-col" aria-label="Tutor">
            <Avatar pose={avatar.pose} pill={avatar.pill} caption={session.caption} captionFading={session.captionFading} />
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
          micBlocked={session.micBlocked}
          sending={session.sending || phase === 'ending'}
          onSendText={(t) => void session.sendChat(t)}
          onToggleMic={() => void session.toggleMic()}
          onAttach={() => fileRef.current?.click()}
          onEnd={() => void session.endSession()}
        />
      )}

      <input
        ref={fileRef}
        type="file"
        hidden
        aria-hidden="true"
        tabIndex={-1}
        accept=".pdf,.png,.jpg,.jpeg,.webp"
        multiple
        onChange={(e) => {
          if (e.target.files && e.target.files.length > 0) {
            void session.addFiles(e.target.files, 'photo');
          }
          e.target.value = '';
        }}
      />
      <audio ref={session.audioRef} aria-hidden="true" />
    </div>
  );
}
