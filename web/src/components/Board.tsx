import { useEffect, useRef } from 'react';
import type { BoardFocusPayload, BoardItem } from '../protocol';
import BoardCard from './Cards';

type Props = {
  learnerName: string;
  lastTopic: string | null;
  items: BoardItem[];
  focused: BoardFocusPayload | null;
  onItemMounted: (id: string) => void;
  onResourceClosed: (id: string) => void;
  dragOver: boolean;
};

export default function Board({
  learnerName,
  lastTopic,
  items,
  focused,
  onItemMounted,
  onResourceClosed,
  dragOver,
}: Props) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = endRef.current;
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'end', behavior: 'smooth' });
    }
  }, [items.length]);

  if (items.length === 0) {
    return (
      <div className="ot-board-scroll" ref={scrollRef}>
        <div className="ot-greeting">
          <h1>Hej {learnerName}!</h1>
          <p className="ot-greeting-sub">Vad har du med dig idag?</p>
          {lastTopic && <span className="ot-last-chip">Förra gången: {lastTopic}</span>}
          <div className={`ot-dropzone${dragOver ? ' dragover' : ''}`} aria-hidden="true">
            <div>📄</div>
            <div>Släpp en fil eller klistra in</div>
            <span className="ot-key-hint">Ctrl + V</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="ot-board-scroll" ref={scrollRef}>
      {items.map((item) => (
        <BoardCard
          key={item.id}
          item={item}
          focusedStep={focused?.id === item.id ? focused.step : undefined}
          onMounted={onItemMounted}
          onResourceClosed={onResourceClosed}
        />
      ))}
      <div ref={endRef} />
    </div>
  );
}
