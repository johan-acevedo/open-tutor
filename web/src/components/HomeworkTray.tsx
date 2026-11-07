import { useEffect, useState } from 'react';

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
          alt="Förhandsvisning av läxan"
          onError={(event) => {
            event.currentTarget.hidden = true;
          }}
        />
      )}
      <span>{file.name || 'Foto'}</span>
    </>
  );
}

export default function HomeworkTray({ draft, busy, onCamera, onFiles, onRemove, onCancel, onSend }: Props) {
  return (
    <section className="ot-homework-tray" aria-label="Lägg till läxa" aria-busy={busy}>
      <h2>{draft.kind === 'picker' ? 'Visa mig din läxa' : 'Redo att skicka?'}</h2>
      {draft.kind === 'files' && (
        <ul>
          {draft.files.map((file, index) => (
            <li key={`${file.name}-${index}`}>
              <FilePreview file={file} />
              <button
                type="button"
                disabled={busy}
                onClick={() => onRemove(index)}
                aria-label={`Ta bort ${file.name || 'foto'}`}
              >
                Ta bort
              </button>
            </li>
          ))}
        </ul>
      )}
      {draft.kind === 'text' && <p className="ot-draft-text">{draft.text}</p>}
      {draft.kind !== 'text' && (
        <div className="ot-tray-actions">
          <button type="button" disabled={busy} onClick={onCamera}>
            {draft.kind === 'picker' ? 'Fota läxan' : 'Ta om foto'}
          </button>
          <button type="button" disabled={busy} onClick={onFiles}>
            Välj bild eller PDF
          </button>
        </div>
      )}
      <div className="ot-tray-actions">
        <button type="button" disabled={busy} onClick={onCancel}>
          Avbryt
        </button>
        {draft.kind !== 'picker' && (
          <button type="button" className="ot-primary" disabled={busy} onClick={onSend}>
            {busy ? 'Skickar…' : 'Skicka till tutorn'}
          </button>
        )}
      </div>
      <p className="ot-tray-hint">Kontrollera att texten går att läsa innan du skickar.</p>
    </section>
  );
}
