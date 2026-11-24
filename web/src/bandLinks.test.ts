import { describe, expect, it } from 'vitest';
import { bandUrl } from './bandLinks';

describe('bandUrl', () => {
  it('swaps the host prefix on band hosts and keeps the rest', () => {
    expect(bandUrl('middle', 'https://tutor.example.se/')).toBe('https://tutor2.example.se/');
    expect(bandUrl('upper', 'https://tutor2.example.se/sida?x=1#del')).toBe(
      'https://tutor3.example.se/sida?x=1#del',
    );
    expect(bandUrl('primary', 'https://tutor3.example.se:8443/stig')).toBe(
      'https://tutor.example.se:8443/stig',
    );
  });

  it('drops the ?band= testing override when moving between band hosts', () => {
    expect(bandUrl('upper', 'https://tutor.example.se/?band=middle')).toBe(
      'https://tutor3.example.se/',
    );
  });

  it('keeps the origin and sets ?band= on other hosts', () => {
    expect(bandUrl('middle', 'http://localhost:5173/')).toBe('http://localhost:5173/?band=middle');
    expect(bandUrl('upper', 'http://dell5500.tail2e1c4e.ts.net:5173/stig?a=b#del')).toBe(
      'http://dell5500.tail2e1c4e.ts.net:5173/stig?a=b&band=upper#del',
    );
  });

  it('replaces an existing ?band= instead of doubling it', () => {
    expect(bandUrl('primary', 'http://localhost:5173/?band=middle')).toBe(
      'http://localhost:5173/?band=primary',
    );
  });
});
