import { useState } from 'react';
import type { Profile } from '../db';
import { createProfile } from '../db';

type Props = {
  profiles: Profile[];
  onPick: (profile: Profile) => void;
  starting: boolean;
};

const GRADES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];

function gradeLabel(g: number): string {
  return g <= 9 ? `åk ${g}` : `gymnasiet åk ${g - 9}`;
}

export default function ProfilePicker({ profiles, onPick, starting }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(profiles[0]?.id ?? null);
  const [showNew, setShowNew] = useState(profiles.length === 0);
  const [name, setName] = useState('');
  const [grade, setGrade] = useState(4);

  const canStart = showNew ? name.trim().length > 0 : selectedId !== null;

  async function handleStart() {
    if (starting) return;
    if (showNew) {
      const trimmed = name.trim();
      if (!trimmed) return;
      const created = await createProfile(trimmed, grade);
      onPick(created);
    } else {
      const found = profiles.find((p) => p.id === selectedId);
      if (found) onPick(found);
    }
  }

  return (
    <div className="ot-profiles">
      <div className="ot-profiles-left">
        <h1>Vem pluggar idag?</h1>
        <div className="ot-profile-grid" role="listbox" aria-label="Välj profil">
          {profiles.map((p) => (
            <button
              key={p.id}
              type="button"
              role="option"
              aria-selected={selectedId === p.id && !showNew}
              className={`ot-profile-card${selectedId === p.id && !showNew ? ' selected' : ''}`}
              onClick={() => {
                setSelectedId(p.id);
                setShowNew(false);
              }}
            >
              <span aria-hidden="true">👤</span>
              <span>{p.name}</span>
              <span className="ot-grade">{gradeLabel(p.grade)}</span>
            </button>
          ))}
          <button
            type="button"
            role="option"
            aria-selected={showNew}
            className={`ot-profile-card${showNew ? ' selected' : ''}`}
            onClick={() => setShowNew(true)}
          >
            <span className="ot-plus" aria-hidden="true">
              +
            </span>
            <span>Ny här?</span>
          </button>
        </div>

        {showNew && (
          <div className="ot-new-fields">
            <label>
              Förnamn
              <input
                className="ot-text-field"
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Vad heter du?"
                aria-label="Förnamn"
                maxLength={40}
              />
            </label>
            <label>
              Årskurs
              <select
                className="ot-select-field"
                value={grade}
                onChange={(e) => setGrade(Number(e.target.value))}
                aria-label="Årskurs"
              >
                {GRADES.map((g) => (
                  <option key={g} value={g}>
                    {g <= 9 ? `Årskurs ${g}` : `Gymnasiet år ${g - 9}`}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        <button type="button" className="ot-start-btn" disabled={!canStart || starting} onClick={handleStart}>
          {starting ? 'Startar…' : 'Starta'}
        </button>
        <p className="ot-profiles-note">Sparas i den här webbläsaren. Ingen inloggning behövs.</p>
      </div>
      <div className="ot-profiles-side" aria-hidden="true">
        <img src="/character/greeting.webp" alt="" onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')} />
      </div>
    </div>
  );
}
