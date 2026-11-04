import type { Note } from '../protocol';

type Props = {
  learnerName: string;
  notes: Note[];
  onBack: () => void;
};

export default function EndCard({ learnerName, notes, onBack }: Props) {
  const last = notes.length > 0 ? notes[notes.length - 1] : null;
  return (
    <div className="ot-endcard">
      <h1>Bra jobbat idag, {learnerName}!</h1>
      {(last?.topic || last?.next) && (
        <div className="ot-endcard-notes">
          {last?.topic && (
            <p>
              <strong>Det här pratade vi om:</strong> {last.topic}
            </p>
          )}
          {last?.clicked && (
            <p>
              <strong>Det här klickade:</strong> {last.clicked}
            </p>
          )}
          {last?.next && (
            <p>
              <strong>Nästa gång:</strong> {last.next}
            </p>
          )}
        </div>
      )}
      <button type="button" className="ot-start-btn" onClick={onBack}>
        Tillbaka till profiler
      </button>
    </div>
  );
}
