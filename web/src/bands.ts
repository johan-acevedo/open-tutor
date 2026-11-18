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
// Companion art and full themes for bands 2 and 3 are being designed in a
// separate thread (see design/bands/README.md): every band reuses the fox for
// now, with clearly distinct theme tokens so the switch is visible.

export type BandId = 'primary' | 'middle' | 'upper';

export type BandConfig = {
  id: BandId;
  /** Host prefixes that select this band (matched against the request host). */
  hosts: string[];
  /** Companion asset set. Placeholders reuse the fox; the design thread puts
   *  real art under design/bands/<band>/ and wires it here (see
   *  design/bands/README.md). */
  companion: {
    /** Label shown in docs/tests; the art itself is still the fox. */
    asset: 'fox-placeholder' | 'fox';
    greetingImage: string;
  };
  /** Theme tokens for the web app (applied as CSS variables under
   *  [data-band]; see styles.css) and the screen shell (same token names;
   *  see design/bands/README.md). Distinct per band on purpose. */
  theme: {
    accentFrom: string;
    accentTo: string;
    surface: string;
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
    companion: { asset: 'fox', greetingImage: '/character/greeting.webp' },
    theme: { accentFrom: '#22d3ee', accentTo: '#a78bfa', surface: '#121826' },
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
    companion: { asset: 'fox-placeholder', greetingImage: '/character/greeting.webp' },
    theme: { accentFrom: '#34d399', accentTo: '#38bdf8', surface: '#0e1a17' },
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
    companion: { asset: 'fox-placeholder', greetingImage: '/character/greeting.webp' },
    theme: { accentFrom: '#fbbf24', accentTo: '#f472b6', surface: '#1a1410' },
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
