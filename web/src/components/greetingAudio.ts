import { useSyncExternalStore } from 'react';
import { helloAudioUrl, type BandId } from '../bands';

// One spoken greeting clip behind the landing speech bubble. A tiny module
// singleton (not component state) so both the bubble and the two start
// buttons stop the same clip: tapping the bubble toggles it, tapping either
// start button stops it before the call begins. The clip is only ever created
// and played inside a tap handler, so it never autoplays.

let el: HTMLAudioElement | null = null;
let elBand: BandId | null = null;
const listeners = new Set<() => void>();
let playing = false;

function emit(): void {
  for (const fn of listeners) fn();
}

function setPlaying(next: boolean): void {
  if (playing !== next) {
    playing = next;
    emit();
  }
}

/** Reset the singleton; tests only (a fresh Audio mock per test file). */
export function resetGreetingForTests(): void {
  el = null;
  elBand = null;
  listeners.clear();
  playing = false;
}

export function isGreetingPlaying(): boolean {
  return playing;
}

export function subscribeGreeting(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

export function useGreetingPlaying(): boolean {
  return useSyncExternalStore(subscribeGreeting, isGreetingPlaying, isGreetingPlaying);
}

function ensure(band: BandId): HTMLAudioElement {
  if (!el || elBand !== band) {
    stopGreeting();
    elBand = band;
    el = new Audio(helloAudioUrl(band));
    el.addEventListener('ended', () => setPlaying(false));
    el.addEventListener('error', () => setPlaying(false));
    el.addEventListener('pause', () => setPlaying(false));
  }
  return el;
}

/** Toggle the greeting clip for this band. Safe to call when the file is
 *  missing (404): the error listener just flips back to not playing. */
export function toggleGreeting(band: BandId): void {
  const audio = ensure(band);
  if (!audio.paused) {
    audio.pause();
    setPlaying(false);
    return;
  }
  try {
    const played = audio.play();
    if (played && typeof (played as Promise<void>).catch === 'function') {
      (played as Promise<void>).then(
        () => setPlaying(true),
        () => setPlaying(false),
      );
    } else {
      setPlaying(true);
    }
  } catch {
    setPlaying(false);
  }
}

/** Stop the greeting clip if it is playing. Called before the start flow. */
export function stopGreeting(): void {
  if (el && !el.paused) {
    try {
      el.pause();
    } catch {
      /* already gone */
    }
  }
  if (el) {
    try {
      el.currentTime = 0;
    } catch {
      /* not seekable yet */
    }
  }
  setPlaying(false);
}
