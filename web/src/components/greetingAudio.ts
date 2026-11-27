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

/** The band whose clip is playing right now, or null. */
export function playingGreetingBand(): BandId | null {
  return playing ? elBand : null;
}

/** Hook form of playingGreetingBand(): the chooser marks only that card. */
export function usePlayingGreetingBand(): BandId | null {
  return useSyncExternalStore(subscribeGreeting, playingGreetingBand, playingGreetingBand);
}

function ensure(band: BandId): HTMLAudioElement {
  if (!el || elBand !== band) {
    stopGreeting();
    elBand = band;
    const audio = new Audio(helloAudioUrl(band));
    audio.preload = 'auto';
    el = audio;
    // Only the current clip may change the state: a late error or pause
    // from a clip we already switched away from must not clear the new one.
    const stopIfCurrent = () => {
      if (el === audio) setPlaying(false);
    };
    audio.addEventListener('ended', stopIfCurrent);
    audio.addEventListener('error', stopIfCurrent);
    audio.addEventListener('pause', stopIfCurrent);
  }
  return el;
}

/** Pre-fetch and decode the greeting clip on user intent (hover, pointerdown,
 *  focus) so the first tap plays from a warm buffer without autoplaying or
 *  interrupting a clip that is already playing. */
export function preloadGreeting(band: BandId): void {
  if (playing || (el && !el.paused) || (el && elBand === band)) return;
  const audio = ensure(band);
  try {
    audio.load?.();
  } catch {
    /* jsdom or stubbed Audio without load() */
  }
}

/** Toggle the greeting clip for this band. Safe to call when the file is
 *  missing (404): the error listener just flips back to not playing. */
export function toggleGreeting(band: BandId): void {
  const audio = ensure(band);
  if (!audio.paused) {
    stopGreeting();
    return;
  }
  try {
    const played = audio.play();
    if (played && typeof (played as Promise<void>).catch === 'function') {
      (played as Promise<void>).then(
        () => {
          if (el === audio && !audio.paused) setPlaying(true);
        },
        () => {
          if (el === audio) setPlaying(false);
        },
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
