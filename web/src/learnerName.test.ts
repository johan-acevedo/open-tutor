import { describe, expect, it } from 'vitest';
import { cleanLearnerName, isValidLearnerName } from './learnerName';

// Finding 6: the browser enforces the same first-name rule the worker checks
// before calling learner.setName — Unicode letters plus space, hyphen and
// apostrophe; 1-3 words; at most 40 chars; no digits or markup.
describe('isValidLearnerName', () => {
  it('accepts ordinary first names', () => {
    for (const good of ['Noa', 'Moa', 'Åsa', 'Linnéa', 'Anna-Lisa', 'Mary Jane', 'Bo Erik Lund', 'O’Neil']) {
      expect(isValidLearnerName(good)).toBe(true);
    }
  });
  it('rejects digits, markup and too many words', () => {
    for (const bad of [
      '',
      '   ',
      'Moa2',
      '2Moa',
      '<b>Moa</b>',
      'Hej!',
      'Moa?',
      'a b c d',
      'x'.repeat(41),
      'Moa-',
      '-Moa',
      'Moa_',
      42 as unknown as string,
    ]) {
      expect(isValidLearnerName(bad)).toBe(false);
    }
  });
  it('allows a 40-char name but not 41', () => {
    expect(isValidLearnerName('x'.repeat(40))).toBe(true);
    expect(isValidLearnerName('x'.repeat(41))).toBe(false);
  });
});

describe('cleanLearnerName', () => {
  it('collapses whitespace like the worker', () => {
    expect(cleanLearnerName('  Mary   Jane  ')).toBe('Mary Jane');
    expect(cleanLearnerName(42)).toBe('');
  });
});
