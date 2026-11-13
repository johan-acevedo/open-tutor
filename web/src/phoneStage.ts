import { useCallback, useEffect, useState } from 'react';

/** Which of the phone's two views is showing. */
export type PhoneView = 'fox' | 'item';

type Args = {
  /** Whether the book has an item that could be shown at all. */
  hasItem: boolean;
  /** Bumped whenever the tutor puts something new in front of the child. */
  itemSignal: number;
  /** View to start in. The demo starts on the fox, like the start of a call. */
  initial?: PhoneView;
};

export type PhoneStageState = {
  view: PhoneView;
  foxView: boolean;
  /** The child taps the fox head: the item is hidden, not removed. */
  showFox: () => void;
  /** The child taps "Visa sidan", or the tutor shows/patches an item. */
  showItem: () => void;
};

/**
 * The phone in portrait shows one thing at a time: the big fox, or the item
 * with the fox as a strip under it. The tutor turns to the item whenever it
 * shows or patches one; tapping the fox head turns back to the fox.
 */
export function usePhoneStage({ hasItem, itemSignal, initial = 'item' }: Args): PhoneStageState {
  const [picked, setPicked] = useState<PhoneView>(initial);
  useEffect(() => {
    // A new or patched item always wins over the child's last choice.
    if (itemSignal > 0) setPicked('item');
  }, [itemSignal]);
  const view: PhoneView = hasItem ? picked : 'fox';
  const showFox = useCallback(() => setPicked('fox'), []);
  const showItem = useCallback(() => setPicked('item'), []);
  return { view, foxView: view === 'fox', showFox, showItem };
}
