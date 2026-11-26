import { useEffect, useRef } from 'react';
import { BANDS, type BandId } from '../bands';
import { t } from '../locales/sv';
import type { Profile } from '../db';

type Props = {
  profiles: Profile[];
  /** Currently shown band (highlights which row belongs here). */
  band: BandId;
  onPick: (profile: Profile) => void;
  /** "+ Någon ny": go to the 3-card chooser / nameless start. */
  onNew: () => void;
  onBack: () => void;
};

function companionOf(profile: Profile): string | null {
  if (!profile.band) return null;
  return BANDS[profile.band]?.companion.name ?? null;
}

/** Calm household picker: one row per remembered learner ("Alva · Räven"),
 *  plus "+ Någon ny". Picking a learner switches band/theme in place and
 *  shows that learner's 1-tap start; nothing starts here. */
export default function HouseholdPicker({ profiles, band, onPick, onNew, onBack }: Props) {
  const titleRef = useRef<HTMLHeadingElement | null>(null);
  // Opening the picker moves focus to its heading; closing returns focus
  // to the opener (the start control) when it is still on screen. A pick
  // or "+ Någon ny" replaces the whole view, so the opener is gone and
  // the caller moves focus to the new view's start control instead.
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    titleRef.current?.focus();
    return () => {
      if (opener?.isConnected) opener.focus();
    };
  }, []);
  const sorted = [...profiles]
    .filter((p) => p.name.trim() !== '')
    .sort((a, b) => a.createdAt - b.createdAt);
  return (
    <div className="ot-picker">
      <h1 className="ot-picker-title" ref={titleRef} tabIndex={-1}>{t('picker.title')}</h1>
      <ul className="ot-picker-list">
        {sorted.map((p) => {
          const companion = companionOf(p);
          const label = companion
            ? t('picker.withCompanion', { name: p.name, companion })
            : p.name;
          return (
            <li key={p.id}>
              <button
                type="button"
                className={`ot-picker-row${p.band === band ? ' is-here' : ''}`}
                onClick={() => onPick(p)}
              >
                <span>{label}</span>
                <span aria-hidden="true">→</span>
              </button>
            </li>
          );
        })}
        <li>
          <button type="button" className="ot-picker-row is-new" onClick={onNew} title={t('picker.newHint')}>
            <span>{t('picker.new')}</span>
            <span aria-hidden="true">→</span>
          </button>
        </li>
      </ul>
      <button type="button" className="ot-link-btn" onClick={onBack}>
        ← {t('picker.back')}
      </button>
    </div>
  );
}
