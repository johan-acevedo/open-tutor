import { useEffect, useRef, useState } from 'react';
import type { ScreenDeckSnapshot } from '../screen';

type Props = {
  learnerName: string;
  snapshot: ScreenDeckSnapshot | null;
  busy: boolean;
  onAttachCanvas: (canvas: HTMLCanvasElement | null) => void;
  onDraft: (pageId: string, revision: string, text: string) => Promise<void>;
  onSubmit: (pageId: string, revision: string) => Promise<void>;
  onGoTo: (index: number) => Promise<void>;
};

/** Fixed one-page workspace. The controller owns all drawing and persistence. */
export default function ScreenBoard({
  learnerName,
  snapshot,
  busy,
  onAttachCanvas,
  onDraft,
  onSubmit,
  onGoTo,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [text, setText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const page = snapshot?.pages[snapshot.current];
  const pageKey = page ? `${page.id}:${page.revision}` : '';
  const storedDraft = page && snapshot ? snapshot.drafts[pageKey] ?? '' : '';

  useEffect(() => {
    onAttachCanvas(canvasRef.current);
    return () => onAttachCanvas(null);
  }, [onAttachCanvas]);

  useEffect(() => {
    setText(storedDraft);
    // Only follow page identity or an external restored draft, not each local keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageKey]);

  async function submit(): Promise<void> {
    if (!page || submitting) return;
    setSubmitting(true);
    try {
      await onDraft(page.id, page.revision, text);
      await onSubmit(page.id, page.revision);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="ot-screen-board">
      {!page && (
        <div className="ot-board-empty" role="status" aria-label="Whiteboard">
          <h1 className="ot-board-empty-greeting">Hej {learnerName}!</h1>
          <p>Här hamnar det vi jobbar med.</p>
          <span>{busy ? 'Skärmen förbereder en sida …' : 'Säg hej — tutorn och skärmen hjälper dig här.'}</span>
        </div>
      )}

      <canvas
        ref={canvasRef}
        className="ot-screen-canvas"
        hidden={!page}
        role="img"
        aria-label={page ? `${page.subject}: ${page.title}` : 'Tom arbetsyta'}
      />

      {page && snapshot && (
        <div className={`ot-screen-controls${page.kind === 'homework' ? ' homework' : ''}`}>
          <nav className="ot-screen-pager" aria-label="Sidnavigering">
            <button type="button" onClick={() => void onGoTo(snapshot.current - 1)} disabled={snapshot.current <= 0}>
              ← Föregående
            </button>
            <span aria-live="polite">Sida {snapshot.current + 1} av {snapshot.pages.length}</span>
            <button
              type="button"
              onClick={() => void onGoTo(snapshot.current + 1)}
              disabled={snapshot.current >= snapshot.pages.length - 1}
            >
              Nästa →
            </button>
          </nav>
          {page.kind !== 'homework' && (
            <>
          <label className="ot-screen-answer">
            <span>{page.answerLabel || 'Ditt svar'}</span>
            <textarea
              value={text}
              rows={2}
              maxLength={500}
              placeholder="Skriv här …"
              onChange={(event) => {
                const next = event.target.value;
                setText(next);
                void onDraft(page.id, page.revision, next);
              }}
              onKeyDown={(event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
                  event.preventDefault();
                  void submit();
                }
              }}
            />
          </label>
          <button
            type="button"
            className="ot-screen-submit"
            disabled={submitting || !text.trim()}
            onClick={() => void submit()}
          >
            {submitting ? 'Skickar …' : 'Skicka till Räven'}
          </button>
            </>
          )}
        </div>
      )}
      {busy && page && <div className="ot-screen-working" role="status">Skärmen förbereder …</div>}
    </div>
  );
}
