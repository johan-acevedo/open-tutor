// Age bands: one codebase, the request host picks the band, and the band
// decides the look (companion, theme, copy). The band never switches
// mid-session or on later visits: it is resolved per page load.
//
// Bands (decided 2026-11-18, ranges corrected the same day):
// - primary: tutor.*  — åk 1–6, today's fox and style.
// - middle:  tutor2.* — åk 7–9 (högstadiet).
// - upper:   tutor3.* — gymnasiet and adults. The tutor finds out naturally
//   whether the learner is a gymnasiet student (and which year) or an adult;
//   only adults skip the grade.
//
import type { Pose } from './avatarState';
import { middleTheme, upperTheme } from 'virtual:band-themes';

export type BandId = 'primary' | 'middle' | 'upper';

function poseImages(directory: string): Record<Pose, string> {
  return {
    greeting: `${directory}/greeting.webp`,
    listening: `${directory}/listening.webp`,
    speaking: `${directory}/speaking.webp`,
    thinking: `${directory}/thinking.webp`,
    working: `${directory}/working.webp`,
    waiting: `${directory}/waiting.webp`,
    pointing: `${directory}/pointing.webp`,
  };
}

export type BandConfig = {
  id: BandId;
  /** Host prefixes that select this band (matched against the request host). */
  hosts: string[];
  companion: {
    asset: 'fox' | 'lynx' | 'bear';
    name: string;
    poses: Record<Pose, string>;
  };
  theme: {
    stylesheet: string;
  };
  /** Band copy for the web app (Swedish). */
  copy: {
    landingTitle: string;
    namePrompt: string;
    startButton: string;
    switchStudent: string;
    newStudent: string;
  };
  /** One-line register hint for the tutor prompt when the grade is unknown. */
  registerHint: string;
};

export const BANDS: Record<BandId, BandConfig> = {
  primary: {
    id: 'primary',
    hosts: ['tutor.'],
    companion: { asset: 'fox', name: 'Räven', poses: poseImages('/character') },
    theme: { stylesheet: '' },
    copy: {
      landingTitle: 'Vad heter du?',
      namePrompt: 'Förnamn',
      startButton: 'Starta',
      switchStudent: 'Byt elev',
      newStudent: 'Ny elev',
    },
    registerHint: 'åk 1–6: friendly, concrete, small steps',
  },
  middle: {
    id: 'middle',
    hosts: ['tutor2.'],
    companion: { asset: 'lynx', name: 'Lodjuret', poses: poseImages('/character/middle') },
    theme: { stylesheet: middleTheme },
    copy: {
      landingTitle: 'Vad heter du?',
      namePrompt: 'Förnamn',
      startButton: 'Starta',
      switchStudent: 'Byt elev',
      newStudent: 'Ny elev',
    },
    registerHint: 'högstadiet (åk 7–9): speak like a peer, compact explanations',
  },
  upper: {
    id: 'upper',
    hosts: ['tutor3.'],
    companion: { asset: 'bear', name: 'Björnen', poses: poseImages('/character/upper') },
    theme: { stylesheet: upperTheme },
    copy: {
      landingTitle: 'Vad heter du?',
      namePrompt: 'Förnamn',
      startButton: 'Starta',
      switchStudent: 'Byt person',
      newStudent: 'Ny person',
    },
    registerHint: 'gymnasiet or adult — find out naturally which; gymnasiet years are 10–12, adults skip the grade',
  },
};

export const BAND_IDS: BandId[] = ['primary', 'middle', 'upper'];

/** Band from a hostname alone. Unknown hosts (localhost, tailnet dev URLs)
 *  default to primary (åk 1–6). */
export function bandFromHostname(hostname: string): BandId {
  const host = (hostname || '').toLowerCase();
  for (const id of BAND_IDS) {
    if (id === 'primary') continue;
    if (BANDS[id].hosts.some((prefix) => host.startsWith(prefix))) return id;
  }
  return 'primary';
}

/** ?band= override for testing: primary|middle|upper (or 1|2|3). */
export function bandFromSearch(search: string): BandId | null {
  try {
    const raw = new URLSearchParams(search).get('band');
    if (!raw) return null;
    const v = raw.trim().toLowerCase();
    if (v === 'primary' || v === '1' || v === 'tutor') return 'primary';
    if (v === 'middle' || v === '2' || v === 'tutor2') return 'middle';
    if (v === 'upper' || v === '3' || v === 'tutor3') return 'upper';
    return null;
  } catch {
    return null;
  }
}

/** Band for this page load only: ?band= wins, otherwise the host. Deliberately
 *  not persisted — a testing override must not leak into later visits. */
export function currentBand(hostname: string, search: string): BandId {
  return bandFromSearch(search) ?? bandFromHostname(hostname);
}

/** Server-advertised default band (TUTOR_BAND, via /api/config): only for
 *  testing on hosts whose name picks no band. Applies when the page carries
 *  no ?band=. */
export function applyServerBand(band: string | null | undefined, hasOverride: boolean): BandId | null {
  if (hasOverride) return null;
  if (band === 'primary' || band === 'middle' || band === 'upper') return band;
  return null;
}

export function bandConfig(band: BandId): BandConfig {
  return BANDS[band];
}
