/** A first name worth storing, learned by voice or typed in the call.

 * The worker checks the same rule before calling `learner.setName` (see
 * `is_valid_learner_name` in `server/open_tutor/agent.py`), and the profile
 * store checks it again before persisting: a misheard fragment, a digit, or
 * markup is never stored. On rejection the tool asks again and nothing is
 * written.
 *
 * Rule: Unicode letters plus space, hyphen and apostrophe; 1-3 words; at
 * most 40 chars; no digits or markup.
 */

// NB: JS \w is ASCII-only even with /u (unlike Python), so Unicode letters
// need \p{L} explicitly; \p{M} covers combining marks. Digits cannot match
// below -- the \d check states that separately, mirroring the worker.
const WORD = /^[\p{L}][\p{L}\p{M}]*(?:['\u2019-][\p{L}\p{M}]+)*$/u;

/** Collapse whitespace the way the worker does (`" ".join(name.split())`). */
export function cleanLearnerName(raw: unknown): string {
  if (typeof raw !== 'string') return '';
  return raw.split(/\s+/).filter(Boolean).join(' ');
}

export function isValidLearnerName(raw: unknown): boolean {
  const clean = cleanLearnerName(raw);
  if (!clean || clean.length > 40) return false;
  if (/\d/.test(clean)) return false;
  const words = clean.split(' ');
  if (words.length > 3) return false;
  return words.every((word) => WORD.test(word));
}
