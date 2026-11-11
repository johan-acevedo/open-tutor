import { useEffect, useState } from 'react';
import type { Pill, Pose } from '../avatarState';

type Props = {
  pose: Pose;
  pill: Pill | null;
  caption: string;
  captionFading: boolean;
  decorative?: boolean;
  compact?: boolean;
  onToggleSize?: () => void;
};

/** Fallback silhouette shown when a pose image is missing (404). */
export function AvatarFallback() {
  return (
    <div className="ot-avatar-fallback" role="img" aria-label="Tutorn">
      <svg width="120" height="120" viewBox="0 0 120 120" aria-hidden="true">
        <circle cx="60" cy="44" r="22" fill="#9BA3B4" />
        <ellipse cx="60" cy="96" rx="34" ry="24" fill="#9BA3B4" />
      </svg>
    </div>
  );
}

function PillIcon({ pill }: { pill: Pill }) {
  if (pill.icon === 'bars') {
    return (
      <span className={`ot-bars${pill.animateBars ? ' animated' : ''}`} aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
    );
  }
  if (pill.icon === 'ear') {
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" fill="none" stroke="#22D3EE" strokeWidth="2" />
        <circle cx="8" cy="8" r="2.5" fill="#22D3EE" />
      </svg>
    );
  }
  if (pill.icon === 'sparkle') {
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M8 0l1.8 5.2L15 7l-5.2 1.8L8 14l-1.8-5.2L1 7l5.2-1.8z" fill="#A78BFA" />
      </svg>
    );
  }
  if (pill.icon === 'pencil') {
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M11 1l4 4-8.5 8.5L2 15l1.5-4.5z" fill="none" stroke="#A78BFA" strokeWidth="1.8" />
      </svg>
    );
  }
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="6" fill="none" stroke="#9BA3B4" strokeWidth="2" />
    </svg>
  );
}

export default function Avatar({ pose, pill, caption, captionFading, decorative, compact, onToggleSize }: Props) {
  const [missing, setMissing] = useState(false);
  // A pose image may be absent (e.g. working.webp before it ships); when the
  // pose changes, retry the new image instead of sticking on the fallback.
  useEffect(() => setMissing(false), [pose]);
  const toneClass = pill ? `ot-pill-${pill.tone}` : '';

  return (
    <>
      <div className={`ot-companion ot-pose-${pose}`}>
        {missing ? (
          <AvatarFallback />
        ) : (
          <img
            className="ot-avatar-img"
            src={`/character/${pose}.webp`}
            alt={decorative ? '' : 'Tutorn'}
            onError={() => setMissing(true)}
          />
        )}
        {onToggleSize && (
          <button
            type="button"
            className="ot-size-btn"
            aria-label={compact ? 'Gör tutorn större' : 'Gör tutorn mindre'}
            aria-pressed={compact}
            onClick={onToggleSize}
          >
            {compact ? '+' : '−'}
          </button>
        )}
      </div>
      <div className="ot-voice-bubble">
        {!decorative && pill && (
          <div className={`ot-pill ${toneClass}`} role="status" aria-label={pill.label}>
            <PillIcon pill={pill} />
            <span>{pill.label}</span>
          </div>
        )}
        {!decorative && (
          <div className={`ot-caption${captionFading ? ' ot-caption-fading' : ''}`} aria-live="polite">
            {caption}
          </div>
        )}
      </div>
    </>
  );
}
