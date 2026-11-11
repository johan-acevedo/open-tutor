import { useRef, useState } from 'react';

type Props = {
  micEnabled: boolean;
  micBlocked: boolean;
  sending: boolean;
  onSendText: (text: string) => void;
  onToggleMic: () => void;
  onAttach: () => void;
  onEnd: () => void;
  mobile?: boolean;
};

export default function BottomBar({
  micEnabled,
  micBlocked,
  sending,
  onSendText,
  onToggleMic,
  onAttach,
  onEnd,
  mobile,
}: Props) {
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLInputElement | null>(null);

  function send() {
    const text = draft.trim();
    if (!text || sending) return;
    onSendText(text);
    setDraft('');
    inputRef.current?.focus();
  }

  const micLabel = micBlocked
    ? 'Mikrofon blockerad'
    : micEnabled
      ? 'Stäng av mikrofonen'
      : 'Mikrofon av — sätt på mikrofonen';

  return (
    <footer className="ot-bottombar" aria-label="Samtalskontroller">
      <button
        type="button"
        className="ot-attach-btn"
        onClick={onAttach}
        aria-label="Lägg till läxa — välj fil"
        title="Lägg till läxa"
      >
        <span aria-hidden="true">📎</span>
      </button>
      <input
        ref={inputRef}
        className="ot-chat-input"
        type="text"
        enterKeyHint="send"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') send();
        }}
        placeholder="Skriv här om du vill…"
        aria-label="Skriv här om du vill"
      />
      {mobile && draft.trim() && (
        <button type="button" className="ot-send-btn" disabled={sending} onClick={send}>
          Skicka
        </button>
      )}
      <button
        type="button"
        className={`ot-mic-btn${micEnabled && !micBlocked ? ' live' : ' muted'}`}
        onClick={onToggleMic}
        aria-label={micLabel}
        title={micEnabled ? 'Mikrofon på' : 'Mikrofon av'}
        aria-pressed={micEnabled}
      >
        <span className="ot-mic-glyph" aria-hidden="true">
          🎙️
        </span>
      </button>
      {!mobile && (
        <button type="button" className="ot-end-btn" onClick={onEnd} aria-label="Avsluta sessionen">
          Avsluta
        </button>
      )}
    </footer>
  );
}
