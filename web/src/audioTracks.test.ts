import { describe, expect, it } from 'vitest';
import { audioElementBusy } from './audioTracks';

function element(stream: unknown): HTMLAudioElement {
  return { srcObject: stream } as unknown as HTMLAudioElement;
}

function stream(states: Array<'live' | 'ended'>): MediaStream {
  return {
    getAudioTracks: () => states.map((readyState) => ({ readyState })),
  } as unknown as MediaStream;
}

describe('audioElementBusy', () => {
  it('is free when nothing is attached', () => {
    expect(audioElementBusy(null)).toBe(false);
    expect(audioElementBusy(element(null))).toBe(false);
  });

  it('is busy while another audio track is live', () => {
    expect(audioElementBusy(element(stream(['live'])))).toBe(true);
  });

  it('is free again when the old track has ended (reconnect)', () => {
    expect(audioElementBusy(element(stream(['ended'])))).toBe(false);
  });

  it('tolerates a stream without audio tracks', () => {
    expect(audioElementBusy(element(stream([])))).toBe(false);
    expect(audioElementBusy(element({}))).toBe(false);
  });
});
