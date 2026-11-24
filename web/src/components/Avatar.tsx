import { useEffect, useState } from 'react';
import type { Pill, Pose } from '../avatarState';
import { useBand } from '../BandContext';
import { t } from '../locales/sv';

type Props = {
  pose: Pose;
  pill: Pill | null;
  caption: string;
  captionFading: boolean;
  decorative?: boolean;
};

/** Fallback silhouette shown when a pose image is missing (404). */
export function AvatarFallback() {
  return (
    <div className="ot-avatar-fallback" role="img" aria-label={t('avatar.tutorLabel')}>
      <svg width="120" height="120" viewBox="0 0 120 120" aria-hidden="true">
        <circle cx="60" cy="44" r="22" fill="#9BA3B4" />
        <ellipse cx="60" cy="96" rx="34" ry="24" fill="#9BA3B4" />
      </svg>
    </div>
  );
}

/**
 * The tutor's current pose image. Shared by the desktop companion, the big
 * phone fox and the round fox head in the phone strip, so a pose that has not
 * shipped yet falls back everywhere.
 */
export function PoseImage({ pose, decorative }: { pose: Pose; decorative?: boolean }) {
  const { companion } = useBand();
  const src = companion.poses[pose];
  const [missing, setMissing] = useState(false);
  // A pose image may be absent (e.g. working.webp before it ships); when the
  // pose changes, retry the new image instead of sticking on the fallback.
  useEffect(() => setMissing(false), [src]);
  if (missing) return <AvatarFallback />;
  return (
    <img
      className="ot-avatar-img"
      src={src}
      alt={decorative ? '' : t('avatar.tutorLabel')}
      onError={() => setMissing(true)}
    />
  );
}

export function PillIcon({ pill }: { pill: Pill }) {
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
        <circle cx="8" cy="8" r="6.5" fill="none" stroke="var(--ot-cyan)" strokeWidth="2" />
        <circle cx="8" cy="8" r="2.5" fill="var(--ot-cyan)" />
      </svg>
    );
  }
  if (pill.icon === 'sparkle') {
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M8 0l1.8 5.2L15 7l-5.2 1.8L8 14l-1.8-5.2L1 7l5.2-1.8z" fill="var(--ot-violet)" />
      </svg>
    );
  }
  if (pill.icon === 'pencil') {
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M11 1l4 4-8.5 8.5L2 15l1.5-4.5z" fill="none" stroke="var(--ot-violet)" strokeWidth="1.8" />
      </svg>
    );
  }
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="6" fill="none" stroke="var(--ot-text-dim)" strokeWidth="2" />
    </svg>
  );
}

export default function Avatar({ pose, pill, caption, captionFading, decorative }: Props) {
  // Whitespace-only counts as empty too: :empty would miss it, and the
  // bubble must still go compact (the caption pipeline already trims, this
  // is belt and braces). The live region stays mounted either way so the
  // first caption is announced; it collapses with height:0 (never hidden
  // from assistive tech) so it never leaves the accessibility tree.
  const empty = caption.trim() === '';
  return (
    <>
      {/* One comic speech bubble by the head (landing language: light paper
          fill, dark outline, tail toward the head, never covering the face):
          the state as a small line on top, the live caption under it. With
          no caption the bubble shows only the state, compact. */}
      {!decorative && (
        <div className={`ot-say${empty ? ' ot-say-empty' : ''}`}>
          {pill && (
            <div className="ot-say-state" role="status" aria-label={pill.label}>
              <PillIcon pill={pill} />
              <span>{pill.label}</span>
            </div>
          )}
          <div
            className={`ot-say-text${captionFading ? ' ot-caption-fading' : ''}${empty ? ' ot-text-empty' : ''}`}
            aria-live="polite"
          >
            {caption}
          </div>
        </div>
      )}
      <div className={`ot-companion ot-pose-${pose}`}>
        <PoseImage pose={pose} decorative={decorative} />
      </div>
    </>
  );
}
