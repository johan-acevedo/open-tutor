import { useRef, useState } from 'react';
import { t } from '../locales/sv';

type Props = {
  micEnabled: boolean;
  micBlocked: boolean;
  sending: boolean;
  onSendText: (text: string) => void;
  onToggleMic: () => void;
  onAttach: () => void;
  mobile?: boolean;
};

export default function BottomBar({
  micEnabled,
  micBlocked,
  sending,
  onSendText,
  onToggleMic,
  onAttach,
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
    ? t('bottombar.micBlocked')
    : micEnabled
      ? t('bottombar.micOff')
      : t('bottombar.micOn');

  return (
    <footer className="ot-bottombar" aria-label={t('bottombar.controlsLabel')}>
      <button
        type="button"
        className="ot-attach-btn"
        onClick={onAttach}
        aria-label={t('bottombar.attachAria')}
        title={t('bottombar.attachTitle')}
      >
        <span aria-hidden="true" className="ot-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 11.5 12.7 19.8a5.5 5.5 0 0 1-7.8-7.8L13.2 3.7a3.7 3.7 0 0 1 5.2 5.2l-8.3 8.3a1.85 1.85 0 0 1-2.6-2.6L14.6 7.5" />
          </svg>
        </span>
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
        placeholder={t('bottombar.inputPlaceholder')}
        aria-label={t('bottombar.inputAria')}
      />
      {mobile && draft.trim() && (
        <button type="button" className="ot-send-btn" disabled={sending} onClick={send}>
          {t('bottombar.send')}
        </button>
      )}
      <button
        type="button"
        className={`ot-mic-btn${micEnabled && !micBlocked ? ' live' : ' muted'}`}
        onClick={onToggleMic}
        aria-label={micLabel}
        title={micEnabled ? t('bottombar.micOnTitle') : t('bottombar.micOffTitle')}
        aria-pressed={micEnabled}
      >
        <span className="ot-mic-glyph" aria-hidden="true">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="2.5" width="6" height="11" rx="3" />
            <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3.5" />
          </svg>
        </span>
      </button>
    </footer>
  );
}
