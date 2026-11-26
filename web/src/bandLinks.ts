import { BAND_PATHS, type BandId } from './bands';

// Host prefixes that select a band (mirrors BANDS in bands.ts).
const PREFIX: Record<BandId, string> = {
  primary: 'tutor.',
  middle: 'tutor2.',
  upper: 'tutor3.',
};

const KNOWN_PREFIXES = [PREFIX.upper, PREFIX.middle, PREFIX.primary];

/** Link from the current page to another band's start page.
 *
 * On a band host (tutor./tutor2./tutor3. prefix) the prefix is swapped and
 * the rest of the URL (protocol, port, other params) is kept; the ?band=
 * testing override is dropped so it cannot pin the old band. On any other
 * host (talarum.se, localhost, tailnet dev) the origin is kept and the
 * single-domain path route (/ak1-6, /hogstadiet, /gymnasiet) is used; the
 * ?band= testing override is dropped there too. Pure: takes and returns strings. */
export function bandUrl(target: BandId, href: string): string {
  const url = new URL(href);
  const host = url.hostname.toLowerCase();
  const matched = KNOWN_PREFIXES.find((prefix) => host.startsWith(prefix));
  if (matched) {
    url.hostname = PREFIX[target] + url.hostname.slice(matched.length);
    url.searchParams.delete('band');
  } else {
    url.pathname = BAND_PATHS[target];
    url.searchParams.delete('band');
  }
  return url.toString();
}
