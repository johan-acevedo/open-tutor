import { describe, expect, it } from 'vitest';
import { bandUrl } from './bandLinks';
import { bandLinkHref } from './components/Paper';

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

  it('uses the single-domain path routes on talarum.se and other hosts', () => {
    expect(bandUrl('middle', 'https://talarum.se/')).toBe('https://talarum.se/hogstadiet');
    expect(bandUrl('upper', 'https://talarum.se/ak1-6')).toBe('https://talarum.se/gymnasiet');
    expect(bandUrl('primary', 'https://talarum.se/hogstadiet')).toBe('https://talarum.se/ak1-6');
  });

  it('uses the path routes on dev hosts and drops ?band=', () => {
    expect(bandUrl('middle', 'http://localhost:5173/')).toBe('http://localhost:5173/hogstadiet');
    expect(bandUrl('upper', 'http://dell5500.tail2e1c4e.ts.net:5173/stig?a=b#del')).toBe(
      'http://dell5500.tail2e1c4e.ts.net:5173/gymnasiet?a=b#del',
    );
    expect(bandUrl('primary', 'http://localhost:5173/?band=middle')).toBe(
      'http://localhost:5173/ak1-6',
    );
  });
});

describe('bandLinkHref (masthead band nav)', () => {
  it('on a tutor.* host swaps the prefix and resets the path, so the new host picks the band', () => {
    expect(bandLinkHref('upper', 'https://tutor.example.test/ak1-6')).toBe('https://tutor3.example.test/');
    expect(bandLinkHref('middle', 'https://tutor3.example.test/integritet?band=upper')).toBe('https://tutor2.example.test/');
    expect(bandLinkHref('primary', 'https://tutor2.example.test/hogstadiet#x')).toBe('https://tutor.example.test/');
  });

  it('on a single-domain host points Åk 1–6 at / and keeps other query parameters', () => {
    expect(bandLinkHref('primary', 'https://talarum.example/hogstadiet?kampanj=x&band=middle')).toBe('/?kampanj=x');
    expect(bandLinkHref('middle', 'https://talarum.example/integritet')).toBe('/hogstadiet');
    expect(bandLinkHref('upper', 'http://localhost:5173/?band=primary#top')).toBe('/gymnasiet');
  });
});
