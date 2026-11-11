import { useEffect, useRef, useState } from 'react';
import type { BoardFocusPayload, BoardItem } from '../protocol';
import BoardCard from './Cards';

type Props = {
  learnerName: string;
  items: BoardItem[];
  focused: BoardFocusPayload | null;
  onItemMounted: (id: string) => void;
  onResourceClosed: (id: string) => void;
  mobile?: boolean;
  activeItemId?: string | null;
  onEnd?: () => void;
};

type View = { kind: 'focus' } | { kind: 'all' } | { kind: 'homework'; id: string };

export default function Board({
  learnerName,
  items,
  focused,
  onItemMounted,
  onResourceClosed,
  mobile = false,
  activeItemId,
  onEnd,
}: Props) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [view, setView] = useState<View>({ kind: 'focus' });
  const [following, setFollowing] = useState(true);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const pausedAt = useRef(0);
  const selected = items.find((item) => item.id === (activeItemId ?? focused?.id)) ?? items.at(-1);
  const homework = items.filter((item) => item.kind === 'homework').at(-1);
  const visibleId = view.kind === 'homework' ? view.id : selected?.id;

  function follow() {
    const scroller = scrollRef.current;
    if (!scroller) return;
    const card = Array.from(scroller.querySelectorAll<HTMLElement>('[data-board-id]')).find(
      (el) => el.dataset.boardId === selected?.id,
    );
    const target = card?.querySelector<HTMLElement>('.ot-step-eq.focused') ?? card;
    if (!target) return;
    // Scroll this surface only; scrollIntoView can move the entire page on iOS.
    const outer = scroller.getBoundingClientRect();
    const inner = target.getBoundingClientRect();
    scroller.scrollTop += inner.height > outer.height ? inner.top - outer.top : inner.bottom - outer.bottom + 8;
  }

  useEffect(() => {
    if (mobile && (view.kind !== 'focus' || Date.now() - pausedAt.current < 6000)) return;
    const frame = requestAnimationFrame(() => {
      follow();
      setFollowing(true);
    });
    return () => cancelAnimationFrame(frame);
  }, [items, focused, activeItemId, mobile, view.kind]);

  const pauseFollow = () => {
    pausedAt.current = Date.now();
    setFollowing(false);
  };

  return (
    <>
      {mobile && (
        <nav className="ot-board-nav" aria-label="Tavlans vyer">
          {homework && (
            <button
              type="button"
              className="ot-homework-chip"
              onClick={() => setView({ kind: 'homework', id: homework.id })}
            >
              {homework.kind === 'homework' && homework.images?.[0] && <img src={homework.images[0]} alt="" />}Din
              uppgift
            </button>
          )}
          {items.length > 0 && (
            <button
              type="button"
              aria-pressed={view.kind === 'all'}
              onClick={() => setView(view.kind === 'all' ? { kind: 'focus' } : { kind: 'all' })}
            >
              Hela tavlan · {items.length}
            </button>
          )}
          {view.kind === 'homework' && (
            <button type="button" onClick={() => setView({ kind: 'focus' })}>
              Tillbaka
            </button>
          )}
        </nav>
      )}
      {mobile && confirmEnd && (
        <div className="ot-end-confirm" role="group" aria-label="Avsluta samtalet?">
          <span>Avsluta samtalet?</span>
          <button type="button" onClick={() => setConfirmEnd(false)}>
            Fortsätt
          </button>
          <button
            type="button"
            className="ot-mobile-end"
            onClick={() => {
              setConfirmEnd(false);
              onEnd?.();
            }}
          >
            Ja, avsluta
          </button>
        </div>
      )}
      <div
        className={`ot-board-scroll${mobile ? ' ot-focus-surface' : ''}`}
        data-view={mobile ? view.kind : 'all'}
        ref={scrollRef}
        onWheel={pauseFollow}
        onTouchMove={pauseFollow}
      >
        {items.length === 0 && (
          <div className="ot-board-empty" role="status" aria-label="Whiteboard">
            <h1 className="ot-board-empty-greeting">Hej {learnerName}!</h1>
            <p>Här hamnar det vi jobbar med.</p>
            <span>Säg hej — tutorn ritar upp här.</span>
          </div>
        )}
        {items.map((item) => (
          <div key={item.id} className="ot-card-slot" hidden={mobile && view.kind !== 'all' && item.id !== visibleId}>
            <BoardCard
              item={item}
              focusedStep={focused?.id === item.id ? focused.step : undefined}
              revealThrough={
                mobile && view.kind === 'focus' && item.kind === 'steps'
                  ? focused?.id === item.id
                    ? (focused.step ?? 0)
                    : 0
                  : undefined
              }
              onMounted={onItemMounted}
              onResourceClosed={onResourceClosed}
            />
          </div>
        ))}
      </div>
      {mobile && items.length > 0 && (!following || view.kind !== 'focus') && (
        <button
          type="button"
          className="ot-follow-btn"
          onClick={() => {
            pausedAt.current = 0;
            setView({ kind: 'focus' });
            setFollowing(true);
            requestAnimationFrame(follow);
          }}
        >
          Tutorn pekar här ↑
        </button>
      )}
    </>
  );
}
