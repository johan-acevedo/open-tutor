import type { Pill, Pose } from '../avatarState';
import { captionTail } from '../useSession';
import { PillIcon, PoseImage } from './Avatar';
import { useBand } from '../BandContext';
import { t } from '../locales/sv';

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
 * The big fox on a phone: it fills the screen and what it says sits in a
 * comic bubble by its head (landing language: light paper, dark outline,
 * tail toward the figure). The state lives inside the bubble as a small line
 * on top — no separate floating pill; the "Visa sidan" action below it is a
 * solid button so the two cannot be confused.
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
  // As in Avatar: whitespace-only counts as empty, and the live region
  // collapses with height:0 (never hidden from assistive tech).
  const empty = line.trim() === '';
  return (
    <div className={`ot-fox-hero ot-pose-${pose}`} data-phone-view="fox">
      <div className="ot-fox-hero-head">
        <div className={`ot-fox-bubble ot-fox-bubble-hero${empty ? ' ot-bubble-empty' : ''}`}>
          <div className="ot-fox-state" role="status" aria-label={pill.label}>
            <PillIcon pill={pill} />
            <span>{pill.label}</span>
          </div>
          <div
            className={`ot-fox-text${captionFading ? ' ot-caption-fading' : ''}${empty ? ' ot-text-empty' : ''}`}
            aria-live="polite"
          >
            {line}
          </div>
        </div>
        <div className="ot-fox-hero-controls">
          {onShowPage && (
            <button
              type="button"
              className="ot-show-page"
              onClick={onShowPage}
              title={pageTitle ? t('fox.showPageWithTitle', { title: pageTitle }) : t('fox.showPage')}
            >
              <span aria-hidden="true">▤</span> {t('fox.showPage')}
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
 * The companion under a shown item: a real cut-out of the current pose
 * (head, shoulders and hands, no circle crop), large enough to show body
 * language, stepping slightly in front of the board's bottom edge. The
 * latest line sits in a comic bubble beside it, the state as a small line on
 * top. Tapping the figure goes back to the big fox.
 *
 * The overlap is paint only (the figure overflows its row): the board keeps
 * its grid size, so the size the server hears (readBoardSize) is still the
 * size the page actually gets.
 */
export function FoxStrip({ pose, pill, caption, captionFading, onShowFox }: Caption & { onShowFox: () => void }) {
  const { companion } = useBand();
  const line = captionTail(caption, STRIP_CHARS);
  const empty = line.trim() === '';
  return (
    <div className={`ot-fox-strip ot-pose-${pose}`} data-phone-view="item">
      <button
        type="button"
        className="ot-fox-cutout"
        onClick={onShowFox}
        aria-label={t('fox.showCompanion', { name: companion.name })}
        title={t('fox.showCompanion', { name: companion.name })}
      >
        <PoseImage pose={pose} decorative />
      </button>
      <div className="ot-fox-strip-body">
        <div className={`ot-fox-bubble ot-fox-bubble-strip${empty ? ' ot-bubble-empty' : ''}`}>
          <div className="ot-fox-state" role="status" aria-label={pill.label}>
            <PillIcon pill={pill} />
            <span>{pill.label}</span>
          </div>
          <div
            className={`ot-fox-text${captionFading ? ' ot-caption-fading' : ''}${empty ? ' ot-text-empty' : ''}`}
            aria-live="polite"
          >
            {line}
          </div>
        </div>
      </div>
    </div>
  );
}
