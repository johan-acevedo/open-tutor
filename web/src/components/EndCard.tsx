import type { Note } from '../protocol';
import { t } from '../locales/sv';

type Props = {
  learnerName: string;
  notes: Note[];
  onBack: () => void;
};

export default function EndCard({ learnerName, notes, onBack }: Props) {
  const last = notes.length > 0 ? notes[notes.length - 1] : null;
  return (
    <div className="ot-endcard">
      <h1>{learnerName.trim() !== '' ? t('end.greetingNamed', { name: learnerName }) : t('end.greetingAnon')}</h1>
      {(last?.topic || last?.next) && (
        <div className="ot-endcard-notes">
          {last?.topic && (
            <p>
              <strong>{t('end.topicLabel')}</strong> {last.topic}
            </p>
          )}
          {last?.clicked && (
            <p>
              <strong>{t('end.clickedLabel')}</strong> {last.clicked}
            </p>
          )}
          {last?.next && (
            <p>
              <strong>{t('end.nextLabel')}</strong> {last.next}
            </p>
          )}
        </div>
      )}
      <button type="button" className="ot-land-cta" onClick={onBack}>
        {t('end.back')}
      </button>
    </div>
  );
}
