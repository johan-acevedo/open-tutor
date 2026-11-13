import type { ReactNode } from 'react';
import type { BoardFocusPayload, BoardItem } from '../protocol';
import type { Pill, Pose } from '../avatarState';
import type { PhoneStageState } from '../phoneStage';
import Board from './Board';
import { FoxHero, FoxStrip } from './FoxView';
import type { PageAnswer, PageShellMessage } from './PageCard';

type Props = {
  learnerName: string;
  items: BoardItem[];
  focused: BoardFocusPayload | null;
  mode: 'arrival' | 'teaching';
  stage: PhoneStageState;
  pose: Pose;
  pill: Pill;
  caption: string;
  captionFading: boolean;
  activeItemId?: string | null;
  onItemMounted: (id: string) => void;
  onResourceClosed: (id: string) => void;
  onItemFailed?: (id: string, message: string) => void;
  registerPageFrame?: (id: string, send: ((msg: PageShellMessage) => void) | null) => void;
  onPageAnswer?: (answer: PageAnswer) => void;
  /** Phone-only overlays that live on the board surface (the homework tray). */
  overlay?: ReactNode;
};

/**
 * Phone portrait stage: one thing at a time. The item takes the height between
 * the top bar and the fox strip, or the fox takes the screen and the item is
 * hidden (still mounted, so typed answers and reveals survive).
 *
 * The board keeps its size while the fox is showing, so the pane measured for
 * the server (`.ot-board-scroll`, see readBoardSize) stays the size a page gets.
 */
export default function PhoneStage({
  learnerName,
  items,
  focused,
  mode,
  stage,
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
  overlay,
}: Props) {
  const current = items.at(-1) ?? null;
  return (
    <main
      className={`ot-main ot-main-${mode}${stage.foxView ? ' ot-fox-view' : ''}`}
      data-phone-view={stage.view}
    >
      <section className="ot-board" aria-label="Whiteboard" aria-hidden={stage.foxView || undefined}>
        <Board
          learnerName={learnerName}
          items={items}
          focused={focused}
          mobile
          showEmptyState={false}
          onItemMounted={onItemMounted}
          onResourceClosed={onResourceClosed}
          onItemFailed={onItemFailed}
          activeItemId={activeItemId}
          registerPageFrame={registerPageFrame}
          onPageAnswer={onPageAnswer}
        />
        {overlay}
      </section>
      <aside className="ot-avatar-col" aria-label="Tutor">
        {stage.foxView ? (
          <FoxHero
            pose={pose}
            pill={pill}
            caption={caption}
            captionFading={captionFading}
            pageTitle={current?.title}
            onShowPage={current ? stage.showItem : undefined}
          />
        ) : (
          <FoxStrip
            pose={pose}
            pill={pill}
            caption={caption}
            captionFading={captionFading}
            onShowFox={stage.showFox}
          />
        )}
      </aside>
    </main>
  );
}
