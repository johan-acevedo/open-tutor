import { describe, expect, it } from 'vitest';
import { applyServerBand, bandConfig, bandFromHostname, bandFromSearch, currentBand } from './bands';

describe('bandFromHostname', () => {
  it('picks the band by subdomain prefix', () => {
    expect(bandFromHostname('tutor.example.se')).toBe('primary');
    expect(bandFromHostname('tutor2.example.se')).toBe('middle');
    expect(bandFromHostname('tutor3.example.se')).toBe('upper');
  });
  it('defaults unknown hosts (localhost, tailnet dev) to primary (åk 1–6)', () => {
    expect(bandFromHostname('localhost')).toBe('primary');
    expect(bandFromHostname('127.0.0.1')).toBe('primary');
    expect(bandFromHostname('dell5500.tail2e1c4e.ts.net')).toBe('primary');
  });
  it('is case-insensitive', () => {
    expect(bandFromHostname('Tutor2.Example.Se')).toBe('middle');
  });
});

describe('bandFromSearch', () => {
  it('accepts band names and numbers for testing', () => {
    expect(bandFromSearch('?band=middle')).toBe('middle');
    expect(bandFromSearch('?band=3')).toBe('upper');
    expect(bandFromSearch('?band=1')).toBe('primary');
    expect(bandFromSearch('')).toBeNull();
    expect(bandFromSearch('?band=nope')).toBeNull();
  });
});

describe('currentBand', () => {
  it('lets ?band= win over the host', () => {
    localStorage.clear();
    expect(currentBand('tutor2.example.se', '?band=upper')).toBe('upper');
  });
  it('remembers the override for the next visit', () => {
    localStorage.clear();
    currentBand('tutor.example.se', '?band=middle');
    expect(currentBand('tutor3.example.se', '')).toBe('middle');
  });
  it('falls back to the host with no override', () => {
    localStorage.clear();
    expect(currentBand('tutor3.example.se', '')).toBe('upper');
  });
});

describe('applyServerBand', () => {
  it('honours TUTOR_BAND only when the page names no band', () => {
    localStorage.clear();
    expect(applyServerBand('middle', false)).toBe('middle');
    expect(applyServerBand('middle', true)).toBeNull();
    expect(applyServerBand('nope', false)).toBeNull();
    expect(applyServerBand(null, false)).toBeNull();
  });
});

describe('band configs', () => {
  it('keeps the fox theme and selects the chosen companions for the other bands', () => {
    expect(bandConfig('primary').theme.stylesheet).toBe('');
    expect(bandConfig('primary').companion.asset).toBe('fox');
    expect(bandConfig('middle').companion.asset).toBe('lynx');
    expect(bandConfig('upper').companion.asset).toBe('bear');
  });
  it('gives the tutor a register hint per band', () => {
    expect(bandConfig('primary').registerHint).toContain('1–6');
    expect(bandConfig('middle').registerHint).toContain('7–9');
    expect(bandConfig('upper').registerHint).toMatch(/gymnasiet or adult/i);
  });
});
