// Age bands: one codebase, the request host picks the band, and the band
// decides the look (companion, theme, copy). The band never switches
// mid-session or on later visits: it is resolved per page load.
//
// Bands (decided 2026-11-18, ranges corrected the same day):
// - primary: tutor.* — years 1-6, today's fox and style.
// - middle:  tutor2.* — years 7-9 (middle school).
// - upper:   tutor3.* — upper secondary and adults. The tutor finds out naturally
//   whether the learner is an upper-secondary student (and which year) or an adult;
//   only adults skip the grade.
//
import type { Pose } from './avatarState';
import { middleTheme, upperTheme } from 'virtual:band-themes';
import { sv } from './locales/sv';

export type BandId = 'primary' | 'middle' | 'upper';

// Bump when the pose files change (scripts/normalize_companion_poses.py):
// public/ files keep their names, and Cloudflare and browsers cache them for
// hours, so without a new URL the old poses linger after a deploy.
export const POSE_VERSION = '20261119';

// Own cache-bust version for the landing images (scripts/export_landing_companions.py).
export const LANDING_IMG_VERSION = '20261125';

// Cache-bust version for the spoken landing greetings
// (web/public/audio/hello-<band>.mp3). Bump when the clips change.
export const HELLO_AUDIO_VERSION = '20261127';

/** Versioned URL of the spoken greeting clip behind the landing speech bubble. */
export function helloAudioUrl(band: BandId): string {
  return `/audio/hello-${band}.mp3?v=${HELLO_AUDIO_VERSION}`;
}

function landingImages(directory: string): { hero: string; face: string } {
  return {
    hero: `${directory}/hero.webp?v=${LANDING_IMG_VERSION}`,
    face: `${directory}/face.webp?v=${LANDING_IMG_VERSION}`,
  };
}

function poseImages(directory: string): Record<Pose, string> {
  const url = (pose: Pose) => `${directory}/${pose}.webp?v=${POSE_VERSION}`;
  return {
    greeting: url('greeting'),
    listening: url('listening'),
    speaking: url('speaking'),
    thinking: url('thinking'),
    working: url('working'),
    waiting: url('waiting'),
    pointing: url('pointing'),
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
    /** Full figure beside the landing headline (scripts/export_landing_companions.py). */
    hero: string;
    /** 96x96 head crop for the round face by band cross-link names. */
    face: string;
  };
  theme: {
    stylesheet: string;
  };
  /** Band copy for the voice-first start page. `{name}` is filled
   *  in with the remembered learner. No name is ever asked in a field: the
   *  tutor learns it by voice after the single start button is pressed. See
   *  web/src/locales/sv.ts (band.* keys) for the Swedish copy. */
  copy: {
    /** Static first-visit bubble beside the companion. */
    welcomeBubble: string;
    /** Returning-visit bubble, with the remembered learner's name. */
    returningBubble: string;
    /** Small link under the start button when the assumed learner is wrong. */
    notYou: string;
    /** The single start action, naming the band companion. */
    startButton: string;
    /** Menu entry that returns to the nameless first-visit page. */
    switchStudent: string;
  };
  /** One-line register hint for the tutor prompt when the grade is unknown. */
  registerHint: string;
};

export const BANDS: Record<BandId, BandConfig> = {
  primary: {
    id: 'primary',
    hosts: ['tutor.'],
    companion: { asset: 'fox', name: sv['band.primary.companionName'], poses: poseImages('/character'), ...landingImages('/character') },
    theme: { stylesheet: '' },
    copy: {
      welcomeBubble: sv['band.primary.welcomeBubble'],
      returningBubble: sv['band.primary.returningBubble'],
      notYou: sv['band.primary.notYou'],
      startButton: sv['band.primary.startButton'],
      switchStudent: sv['band.primary.switchStudent'],
    },
    registerHint: 'years 1–6: friendly, concrete, small steps',
  },
  middle: {
    id: 'middle',
    hosts: ['tutor2.'],
    companion: { asset: 'lynx', name: sv['band.middle.companionName'], poses: poseImages('/character/middle'), ...landingImages('/character/middle') },
    theme: { stylesheet: middleTheme },
    copy: {
      welcomeBubble: sv['band.middle.welcomeBubble'],
      returningBubble: sv['band.middle.returningBubble'],
      notYou: sv['band.middle.notYou'],
      startButton: sv['band.middle.startButton'],
      switchStudent: sv['band.middle.switchStudent'],
    },
    registerHint: 'middle school (years 7–9): speak like a peer, compact explanations',
  },
  upper: {
    id: 'upper',
    hosts: ['tutor3.'],
    companion: { asset: 'bear', name: sv['band.upper.companionName'], poses: poseImages('/character/upper'), ...landingImages('/character/upper') },
    theme: { stylesheet: upperTheme },
    copy: {
      welcomeBubble: sv['band.upper.welcomeBubble'],
      returningBubble: sv['band.upper.returningBubble'],
      notYou: sv['band.upper.notYou'],
      startButton: sv['band.upper.startButton'],
      switchStudent: sv['band.upper.switchStudent'],
    },
    registerHint: 'gymnasiet or adult — find out naturally which; gymnasiet years are 10–12, adults skip the grade',
  },
};

export const BAND_IDS: BandId[] = ['primary', 'middle', 'upper'];

/** Band from a hostname alone. Unknown hosts (localhost, tailnet dev URLs)
 *  default to primary (years 1-6). */
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

/** Path routes for the single-domain flow on talarum.se. Canonical paths
 *  plus aliases (normalized with history.replaceState by the caller). */
export const BAND_PATHS: Record<BandId, string> = {
  primary: '/ak1-6',
  middle: '/hogstadiet',
  upper: '/gymnasiet',
};

const PATH_ALIASES: Record<string, BandId> = {
  '/ak1-6': 'primary',
  '/hogstadiet': 'middle',
  '/hogstadiet/': 'middle',
  '/gymnasiet': 'upper',
  '/gymnasiet/': 'upper',
  '/raven': 'primary',
  '/lodjuret': 'middle',
  '/linnea': 'middle',
  '/bjornen': 'upper',
  '/bj\u00f6rnen': 'upper',
  '/vuxen': 'upper',
  '/studier': 'upper',
};

/** Band from the request path alone. Unknown paths (/, /integritet, …)
 *  name no band. */
export function bandFromPath(pathname: string): BandId | null {
  try {
    const p = (pathname || '/').split('?')[0].split('#')[0].toLowerCase();
    const norm = p.length > 1 && p.endsWith('/') && !PATH_ALIASES[p] ? p.slice(0, -1) : p;
    return PATH_ALIASES[norm] ?? (norm === '/ak1-6/' ? 'primary' : null);
  } catch {
    return null;
  }
}

export function bandPath(band: BandId): string {
  return BAND_PATHS[band];
}

/** Band named explicitly by the request host (tutor./tutor2./tutor3.
 *  prefixes), or null on any other host (talarum.se, localhost, tailnet
 *  dev). A tutor.* host always names its band; anything else leaves the
 *  band to the path, ?band= or server default. */
export function explicitHostBand(hostname: string): BandId | null {
  const host = (hostname || '').toLowerCase();
  if (host.startsWith('tutor2.')) return 'middle';
  if (host.startsWith('tutor3.')) return 'upper';
  if (host.startsWith('tutor.')) return 'primary';
  return null;
}

/** One band per navigation. Precedence: ?band= > path > host prefix >
 *  server-advertised TUTOR_BAND (only when nothing else names a band) >
 *  default. Deliberately not persisted: a testing override must not leak
 *  into later visits. */
export function resolveBand(opts: {
  hostname: string;
  search: string;
  pathname?: string;
  serverBand?: string | null;
}): BandId {
  const named =
    bandFromSearch(opts.search) ??
    (opts.pathname !== undefined ? bandFromPath(opts.pathname) : null) ??
    explicitHostBand(opts.hostname);
  if (named) return named;
  const server = opts.serverBand;
  if (server === 'primary' || server === 'middle' || server === 'upper') return server;
  return 'primary';
}

/** Alias paths (/raven, /lodjuret, /linnea, …) normalize to the canonical band path
 *  while keeping the query string and fragment: a ?band= testing override
 *  or #anchor survives the normalization. Returns the full normalized URL
 *  (path + search + hash), or null when the path is already canonical or
 *  names no band. */
export function normalizeAliasUrl(pathname: string, search: string, hash: string): string | null {
  const band = bandFromPath(pathname);
  if (!band) return null;
  const canon = BAND_PATHS[band];
  try {
    if (pathname.toLowerCase() === canon) return null;
  } catch {
    return null;
  }
  return canon + search + hash;
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
