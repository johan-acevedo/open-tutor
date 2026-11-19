import { useEffect, useState } from 'react';
import { t } from '../locales/sv';

export type HomeworkDraft =
  | { kind: 'picker' }
  | { kind: 'files'; files: File[]; source: 'photo' | 'screenshot' }
  | { kind: 'text'; text: string };

type Props = {
  draft: HomeworkDraft;
  busy: boolean;
  onCamera: () => void;
  onFiles: () => void;
  onRemove: (index: number) => void;
  onCancel: () => void;
  onSend: () => void;
};

function FilePreview({ file }: { file: File }) {
  const [url, setUrl] = useState('');
  useEffect(() => {
    if (!file.type.startsWith('image/')) return;
    const objectUrl = URL.createObjectURL(file);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [file]);
  return (
    <>
      {url && (
        <img
          src={url}
          alt={t('tray.previewAlt')}
          onError={(event) => {
            event.currentTarget.hidden = true;
          }}
        />
      )}
      <span>{file.name || t('tray.fallbackName')}</span>
    </>
  );
}

export default function HomeworkTray({ draft, busy, onCamera, onFiles, onRemove, onCancel, onSend }: Props) {
  return (
    <section className="ot-homework-tray" aria-label={t('tray.label')} aria-busy={busy}>
      <h2>{draft.kind === 'picker' ? t('tray.pickerTitle') : t('tray.readyTitle')}</h2>
      {draft.kind === 'files' && (
        <ul>
          {draft.files.map((file, index) => (
            <li key={`${file.name}-${index}`}>
              <FilePreview file={file} />
              <button
                type="button"
                disabled={busy}
                onClick={() => onRemove(index)}
                aria-label={t('tray.removeAria', { name: file.name || t('tray.fallbackName') })}
              >
                {t('tray.remove')}
              </button>
            </li>
          ))}
        </ul>
      )}
      {draft.kind === 'text' && <p className="ot-draft-text">{draft.text}</p>}
      {draft.kind !== 'text' && (
        <div className="ot-tray-actions">
          <button type="button" disabled={busy} onClick={onCamera}>
            {draft.kind === 'picker' ? t('tray.photo') : t('tray.retake')}
          </button>
          <button type="button" disabled={busy} onClick={onFiles}>
            {t('tray.choose')}
          </button>
        </div>
      )}
      <div className="ot-tray-actions">
        <button type="button" disabled={busy} onClick={onCancel}>
          {t('tray.cancel')}
        </button>
        {draft.kind !== 'picker' && (
          <button type="button" className="ot-primary" disabled={busy} onClick={onSend}>
            {busy ? t('tray.sending') : t('tray.send')}
          </button>
        )}
      </div>
      <p className="ot-tray-hint">{t('tray.hint')}</p>
    </section>
  );
}
