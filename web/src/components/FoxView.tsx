import type { Pill, Pose } from '../avatarState';
import { captionTail } from '../useSession';
import { PillIcon, PoseImage } from './Avatar';

// The strip has room for about three lines, the big bubble for about four.
// Trimming to the tail keeps the latest words (the caption itself is already
// the tail of the tutor's speech) instead of cutting the end off.
const STRIP_CHARS = 100;
const HERO_CHARS = 150;

type Caption = {
  pose: Pose;
  pill: Pill;
  caption: string;
  captionFading: boolean;
};

/**
 * The big fox on a phone: it fills the screen and what it says sits in a light
 * bubble by its head, with the state pill (and "Visa sidan" when there is a
 * page behind it) in a row under the bubble.
 */
export function FoxHero({
  pose,
  pill,
  caption,
  captionFading,
  pageTitle,
  onShowPage,
}: Caption & { pageTitle?: string; onShowPage?: () => void }) {
  const line = captionTail(caption, HERO_CHARS);
  return (
    <div className={`ot-fox-hero ot-pose-${pose}`} data-phone-view="fox">
      <div className="ot-fox-hero-head">
        <div
          className={`ot-fox-bubble ot-fox-bubble-hero${captionFading ? ' ot-caption-fading' : ''}`}
          aria-live="polite"
        >
          {line}
        </div>
        <div className="ot-fox-hero-controls">
          <div className={`ot-pill ot-pill-${pill.tone}`} role="status" aria-label={pill.label}>
            <PillIcon pill={pill} />
            <span>{pill.label}</span>
          </div>
          {onShowPage && (
            <button
              type="button"
              className="ot-show-page"
              onClick={onShowPage}
              title={pageTitle ? `Visa sidan: ${pageTitle}` : 'Visa sidan'}
            >
              <span aria-hidden="true">▤</span> Visa sidan
            </button>
          )}
        </div>
      </div>
      <div className="ot-fox-hero-figure">
        <PoseImage pose={pose} />
      </div>
    </div>
  );
}

/**
 * The fox strip under a shown item: a round head cropped from the current pose
 * (its ring carries the state) and the latest line in a bubble beside it.
 * Tapping the head goes back to the big fox.
 */
export function FoxStrip({ pose, pill, caption, captionFading, onShowFox }: Caption & { onShowFox: () => void }) {
  const line = captionTail(caption, STRIP_CHARS);
  return (
    <div className={`ot-fox-strip ot-pose-${pose}`} data-phone-view="item">
      <button
        type="button"
        className={`ot-fox-head ot-fox-head-${pill.tone}${pill.animateBars ? ' ot-fox-head-speaking' : ''}`}
        onClick={onShowFox}
        aria-label="Visa Räven"
        title="Visa Räven"
      >
        <PoseImage pose={pose} decorative />
      </button>
      <div className="ot-fox-strip-body">
        {/* The ring shows the state; this keeps it available to screen readers. */}
        <span className="ot-sr-only" role="status" aria-label={pill.label}>
          {pill.label}
        </span>
        <div
          className={`ot-fox-bubble ot-fox-bubble-strip${captionFading ? ' ot-caption-fading' : ''}`}
          aria-live="polite"
        >
          {line || (
            <span className="ot-fox-bubble-state" aria-hidden="true">
              {pill.label}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
