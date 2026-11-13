import { useEffect, useState } from 'react';
import type { BoardFocusPayload, BoardItem } from '../protocol';
import BoardCard from './Cards';
import PageCard, { type PageAnswer, type PageShellMessage } from './PageCard';

type Props = {
  learnerName: string;
  items: BoardItem[];
  focused: BoardFocusPayload | null;
  onItemMounted: (id: string) => void;
  onResourceClosed: (id: string) => void;
  mobile?: boolean;
  /** The phone shows the fox instead of the empty-board placeholder card. */
  showEmptyState?: boolean;
  activeItemId?: string | null;
  registerPageFrame?: (id: string, send: ((msg: PageShellMessage) => void) | null) => void;
  onPageAnswer?: (answer: PageAnswer) => void;
  onCurrentChange?: (id: string) => void;
};

const noopSend = () => {};
const noopAnswer = () => {};

function registerNoop(_id: string, _send: ((msg: PageShellMessage) => void) | null): void {
  noopSend();
}

export default function Board({
  learnerName,
  items,
  focused,
  onItemMounted,
  onResourceClosed,
  mobile = false,
  showEmptyState = true,
  activeItemId,
  registerPageFrame = registerNoop,
  onPageAnswer = noopAnswer,
  onCurrentChange,
}: Props) {
  // One leaf at a time, like a book. The tutor turns the page by showing or
  // focusing an item; the child turns it with back/forward. Earlier page
  // frames stay mounted (hidden) so typed answers and reveals survive.
  const [currentId, setCurrentId] = useState<string | null>(null);
  const wanted = activeItemId ?? focused?.id ?? null;
  useEffect(() => {
    if (wanted && items.some((item) => item.id === wanted)) setCurrentId(wanted);
  }, [wanted, items]);
  const current = items.find((item) => item.id === currentId) ?? items.at(-1) ?? null;
  const index = current ? items.indexOf(current) : -1;
  // The parent is told from the button handlers below, never from an
  // effect, so turning the page cannot feed back into a render loop.
  const turn = (id: string) => {
    setCurrentId(id);
    onCurrentChange?.(id);
  };


  return (
    <>
      {items.length > 1 && (
        <nav className="ot-book-nav" aria-label="Bläddra i tavlan">
          <button
            type="button"
            disabled={index <= 0}
            onClick={() => {
              const prev = items[index - 1];
              if (prev) turn(prev.id);
            }}
          >
            ← Tillbaka
          </button>
          <span className="ot-book-pos" aria-live="polite">
            {index + 1} / {items.length}
          </span>
          <button
            type="button"
            disabled={index < 0 || index >= items.length - 1}
            onClick={() => {
              const next = items[index + 1];
              if (next) turn(next.id);
            }}
          >
            Framåt →
          </button>
        </nav>
      )}
      <div className="ot-board-scroll" data-book={items.length}>
        {items.length === 0 && showEmptyState && (
          <div className="ot-board-empty" role="status" aria-label="Whiteboard">
            <h1 className="ot-board-empty-greeting">Hej {learnerName}!</h1>
            <p>Här hamnar det vi jobbar med.</p>
            <span>Säg hej — tutorn ritar upp här.</span>
          </div>
        )}
        {items.map((item) => (
          <div
            key={item.id}
            className={`ot-card-slot${item.kind === 'page' ? ' ot-card-slot-page' : ''}`}
            hidden={current ? item.id !== current.id : false}
          >
            {item.kind === 'page' ? (
              <PageCard
                item={item}
                onMounted={onItemMounted}
                registerSend={registerPageFrame}
                onAnswer={onPageAnswer}
              />
            ) : (
              <BoardCard
                item={item}
                focusedStep={focused?.id === item.id ? focused.step : undefined}
                revealThrough={
                  mobile && item.kind === 'steps' && focused?.id === item.id
                    ? (focused.step ?? 0)
                    : undefined
                }
                onMounted={onItemMounted}
                onResourceClosed={onResourceClosed}
              />
            )}
          </div>
        ))}
      </div>
    </>
  );
}
