import { useRef, useState } from 'react';
import type { BandConfig } from '../bands';
import { createProfile, getLastProfileId } from '../db';
import type { Profile } from '../db';

type Props = {
  profiles: Profile[];
  band: BandConfig;
  onPick: (profile: Profile) => void;
  starting: boolean;
  onStartGesture?: () => void;
  /** Open the switch/add list directly (menu leave flow). */
  startOpen?: boolean;
  /** After an in-call switch: assume this student instead of the last one. */
  assumeId?: string | null;
};

function gradeLabel(grade: number | null): string | null {
  if (grade == null) return null;
  return grade <= 9 ? `åk ${grade}` : `gymnasiet åk ${grade - 9}`;
}

/** Name-only start. First visit asks only "Vad heter du?"; later visits
 *  assume the same student ("Hej <name>, starta"). "Byt elev" switches or
 *  adds a student. Profiles stay in browser storage, no accounts. */
export default function Welcome({ profiles, band, onPick, starting, onStartGesture, startOpen, assumeId }: Props) {
  const lastId = getLastProfileId();
  const assumed =
    (assumeId ? profiles.find((p) => p.id === assumeId) : undefined) ??
    profiles.find((p) => p.id === lastId) ??
    profiles[0] ??
    null;
  const [switching, setSwitching] = useState(startOpen ?? false);
  const [name, setName] = useState('');
  const [creating, setCreating] = useState(false);
  const startPending = useRef(false);

  async function begin(profile: Profile) {
    if (starting || startPending.current) return;
    startPending.current = true;
    try {
      onStartGesture?.();
      onPick(profile);
    } finally {
      startPending.current = false;
    }
  }

  async function createAndBegin() {
    const trimmed = name.trim();
    if (!trimmed || starting || startPending.current) return;
    startPending.current = true;
    setCreating(true);
    try {
      onStartGesture?.();
      const created = await createProfile(trimmed);
      onPick(created);
    } finally {
      startPending.current = false;
      setCreating(false);
    }
  }

  const copy = band.copy;
  const showList = profiles.length === 0 || switching;

  return (
    <div className="ot-profiles">
      <div className="ot-profiles-left">
        {!showList && assumed && (
          <>
            <h1>
              Hej {assumed.name}!
            </h1>
            <button
              type="button"
              className="ot-start-btn"
              disabled={starting}
              onClick={() => void begin(assumed)}
            >
              {starting ? 'Startar…' : copy.startButton}
            </button>
            <p className="ot-profiles-note">
              <button type="button" className="ot-link-btn" onClick={() => setSwitching(true)}>
                {copy.switchStudent}
              </button>
            </p>
          </>
        )}

        {showList && (
          <>
            <h1>{profiles.length === 0 ? copy.landingTitle : copy.switchStudent}</h1>
            {profiles.length > 0 && (
              <div className="ot-profile-grid" role="listbox" aria-label={copy.switchStudent}>
                {profiles.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    role="option"
                    aria-selected={false}
                    className="ot-profile-card"
                    disabled={starting || creating}
                    onClick={() => void begin(p)}
                  >
                    <span aria-hidden="true">👤</span>
                    <span>{p.name}</span>
                    {gradeLabel(p.grade) && <span className="ot-grade">{gradeLabel(p.grade)}</span>}
                  </button>
                ))}
              </div>
            )}
            <div className="ot-new-fields">
              <label>
                {profiles.length === 0 ? copy.namePrompt : copy.newStudent}
                <input
                  className="ot-text-field"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={copy.landingTitle}
                  aria-label={copy.namePrompt}
                  maxLength={40}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') void createAndBegin();
                  }}
                />
              </label>
            </div>
            <button
              type="button"
              className="ot-start-btn"
              disabled={!name.trim() || starting || creating}
              onClick={() => void createAndBegin()}
            >
              {starting || creating ? 'Startar…' : copy.startButton}
            </button>
            {profiles.length > 0 && (
              <p className="ot-profiles-note">
                <button type="button" className="ot-link-btn" onClick={() => setSwitching(false)}>
                  Tillbaka
                </button>
              </p>
            )}
            <p className="ot-profiles-note">Sparas i den här webbläsaren. Ingen inloggning behövs.</p>
          </>
        )}
      </div>
      <div className="ot-profiles-side" aria-hidden="true">
        <img
          src={band.companion.greetingImage}
          alt=""
          onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
        />
      </div>
    </div>
  );
}
