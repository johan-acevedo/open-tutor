import { describe, expect, it } from 'vitest';
import { applyServerBand, bandConfig, bandFromHostname, bandFromSearch, explicitHostBand, normalizeAliasUrl, resolveBand } from './bands';

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

describe('explicitHostBand', () => {
  it('names the band only on tutor.* hosts', () => {
    expect(explicitHostBand('tutor.example.se')).toBe('primary');
    expect(explicitHostBand('tutor2.example.se')).toBe('middle');
    expect(explicitHostBand('tutor3.example.se')).toBe('upper');
    expect(explicitHostBand('talarum.se')).toBeNull();
    expect(explicitHostBand('localhost')).toBeNull();
    expect(explicitHostBand('dell5500.tail2e1c4e.ts.net')).toBeNull();
  });
});

describe('resolveBand', () => {
  it('lets ?band= win over the path and the host', () => {
    expect(resolveBand({ hostname: 'tutor2.example.se', search: '?band=upper', pathname: '/hogstadiet' })).toBe('upper');
  });
  it('lets the path win over the host', () => {
    expect(resolveBand({ hostname: 'tutor.example.se', search: '', pathname: '/hogstadiet' })).toBe('middle');
    expect(resolveBand({ hostname: 'tutor2.example.se', search: '', pathname: '/gymnasiet' })).toBe('upper');
  });
  it('falls back to the host with no override', () => {
    expect(resolveBand({ hostname: 'tutor3.example.se', search: '' })).toBe('upper');
    expect(resolveBand({ hostname: 'talarum.se', search: '', pathname: '/' })).toBe('primary');
  });
  it('never persists ?band=: the next load without it falls back to the host', () => {
    localStorage.clear();
    expect(resolveBand({ hostname: 'tutor.example.se', search: '?band=middle' })).toBe('middle');
    expect(localStorage.getItem('open-tutor-band')).toBeNull();
    expect(resolveBand({ hostname: 'tutor3.example.se', search: '' })).toBe('upper');
  });
  it('uses the server band only when nothing else names a band', () => {
    expect(resolveBand({ hostname: 'talarum.se', search: '', pathname: '/', serverBand: 'middle' })).toBe('middle');
    expect(resolveBand({ hostname: 'talarum.se', search: '', pathname: '/', serverBand: 'nope' })).toBe('primary');
    expect(resolveBand({ hostname: 'talarum.se', search: '', pathname: '/', serverBand: null })).toBe('primary');
    // The path and ?band= both beat the server default.
    expect(resolveBand({ hostname: 'talarum.se', search: '', pathname: '/hogstadiet', serverBand: 'upper' })).toBe('middle');
    expect(resolveBand({ hostname: 'talarum.se', search: '?band=upper', pathname: '/', serverBand: 'middle' })).toBe('upper');
    // The host prefix beats the server default too.
    expect(resolveBand({ hostname: 'tutor2.example.se', search: '', pathname: '/', serverBand: 'upper' })).toBe('middle');
  });
});

describe('normalizeAliasUrl', () => {
  it('keeps the query string and fragment on alias normalization', () => {
    expect(normalizeAliasUrl('/lodjuret', '?band=upper', '#x')).toBe('/hogstadiet?band=upper#x');
    expect(normalizeAliasUrl('/raven', '', '')).toBe('/ak1-6');
    expect(normalizeAliasUrl('/vuxen', '?a=b', '')).toBe('/gymnasiet?a=b');
    expect(normalizeAliasUrl('/studier', '?a=b', '#x')).toBe('/gymnasiet?a=b#x');
  });
  it('leaves canonical paths and band-less paths alone', () => {
    expect(normalizeAliasUrl('/hogstadiet', '?band=upper', '#x')).toBeNull();
    expect(normalizeAliasUrl('/ak1-6', '', '')).toBeNull();
    expect(normalizeAliasUrl('/', '', '')).toBeNull();
    expect(normalizeAliasUrl('/integritet', '', '')).toBeNull();
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

describe('bandFromPath', () => {
  it('reads the single-domain path routes', async () => {
    const { bandFromPath, bandPath } = await import('./bands');
    expect(bandFromPath('/ak1-6')).toBe('primary');
    expect(bandFromPath('/hogstadiet')).toBe('middle');
    expect(bandFromPath('/gymnasiet')).toBe('upper');
    expect(bandFromPath('/')).toBeNull();
    expect(bandFromPath('/integritet')).toBeNull();
    expect(bandFromPath('/unknown')).toBeNull();
    expect(bandPath('primary')).toBe('/ak1-6');
    expect(bandPath('middle')).toBe('/hogstadiet');
    expect(bandPath('upper')).toBe('/gymnasiet');
  });

  it('normalizes companion aliases to the same band', async () => {
    const { bandFromPath } = await import('./bands');
    expect(bandFromPath('/raven')).toBe('primary');
    expect(bandFromPath('/lodjuret')).toBe('middle');
    expect(bandFromPath('/bjornen')).toBe('upper');
    expect(bandFromPath('/vuxen')).toBe('upper');
    expect(bandFromPath('/studier')).toBe('upper');
    expect(bandFromPath('/hogstadiet/')).toBe('middle');
  });

  it('gives the path precedence over the host, and ?band= over the path', async () => {
    const { resolveBand } = await import('./bands');
    expect(resolveBand({ hostname: 'tutor.example.se', search: '', pathname: '/hogstadiet' })).toBe('middle');
    expect(resolveBand({ hostname: 'tutor2.example.se', search: '', pathname: '/gymnasiet' })).toBe('upper');
    expect(resolveBand({ hostname: 'tutor.example.se', search: '?band=upper', pathname: '/hogstadiet' })).toBe('upper');
    expect(resolveBand({ hostname: 'localhost', search: '', pathname: '/' })).toBe('primary');
    expect(resolveBand({ hostname: 'talarum.se', search: '', pathname: '/studier' })).toBe('upper');
  });
});
