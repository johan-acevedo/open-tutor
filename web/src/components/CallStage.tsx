import type { ReactNode } from 'react';
import type { BoardFocusPayload, BoardItem } from '../protocol';
import type { Pill, Pose } from '../avatarState';
import Board from './Board';
import Avatar from './Avatar';
import type { PageAnswer, PageShellMessage } from './PageCard';

type Props = {
  learnerName: string;
  items: BoardItem[];
  focused: BoardFocusPayload | null;
  /** arrival until the first board item, then teaching. */
  mode: 'arrival' | 'teaching';
  pose: Pose;
  pill: Pill | null;
  caption: string;
  captionFading: boolean;
  activeItemId?: string | null;
  onItemMounted: (id: string) => void;
  onResourceClosed: (id: string) => void;
  onItemFailed?: (id: string, message: string) => void;
  registerPageFrame?: (id: string, send: ((msg: PageShellMessage) => void) | null) => void;
  onPageAnswer?: (answer: PageAnswer) => void;
  onCurrentChange?: (id: string) => void;
  /** Call-surface overlays (the homework tray). */
  overlay?: ReactNode;
};

/**
 * The desktop/tablet in-call stage (concept A). Arrival: the companion stands
 * large and centred over the halo, and the board section stays laid out at
 * its teaching geometry but unseen — so the pixel size the server commissions
 * pages for (readBoardSize measures .ot-board-scroll) is already the size the
 * board will have once it slides in. Teaching: the board slides/fades in on
 * the left (~2/3) and the companion keeps the right column (~1/3), staying
 * large enough to show its poses. Phone portrait lives in PhoneStage.
 */
export default function CallStage({
  learnerName,
  items,
  focused,
  mode,
  pose,
  pill,
  caption,
  captionFading,
  activeItemId,
  onItemMounted,
  onResourceClosed,
  onItemFailed,
  registerPageFrame,
  onPageAnswer,
  onCurrentChange,
  overlay,
}: Props) {
  return (
    <main className={`ot-main ot-main-${mode}`}>
      <section className="ot-board" aria-label="Whiteboard">
        <Board
          learnerName={learnerName}
          items={items}
          focused={focused}
          // The desktop stage never shows the empty-board copy: in arrival the
          // companion owns the stage, in teaching there is always an item.
          // The scroll surface still mounts in arrival so its laid-out size is
          // what the server hears (see readBoardSize).
          showEmptyState={false}
          onItemMounted={onItemMounted}
          onResourceClosed={onResourceClosed}
          onItemFailed={onItemFailed}
          activeItemId={activeItemId}
          registerPageFrame={registerPageFrame}
          onPageAnswer={onPageAnswer}
          onCurrentChange={onCurrentChange}
        />
        {overlay}
      </section>
      {/* Arrival hero: halo + centred companion + speech bubble. Stays mounted
          in teaching (unseen) so the switch is a fade, not a remount. */}
      <div className="ot-stage-hero">
        <div className="ot-stage-halo" aria-hidden="true" />
        <div className="ot-stage-hero-inner">
          <Avatar pose={pose} pill={pill} caption={caption} captionFading={captionFading} />
        </div>
      </div>
      <aside className="ot-avatar-col" aria-label="Tutor">
        <div className="ot-companion-halo" aria-hidden="true" />
        <Avatar pose={pose} pill={pill} caption={caption} captionFading={captionFading} />
      </aside>
    </main>
  );
}
