import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { helloAudioUrl, type BandId } from '../bands';
import {
  isGreetingPlaying,
  resetGreetingForTests,
  stopGreeting,
  toggleGreeting,
} from './greetingAudio';
import { MockAudio } from './mockAudio';

beforeEach(() => {
  resetGreetingForTests();
  MockAudio.instances = [];
  vi.stubGlobal('Audio', MockAudio as unknown as typeof Audio);
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetGreetingForTests();
});

function tick(): Promise<void> {
  return Promise.resolve();
}

it('builds a versioned clip URL per band', () => {
  for (const band of ['primary', 'middle', 'upper'] as BandId[]) {
    const url = helloAudioUrl(band);
    expect(url.startsWith(`/audio/hello-${band}.mp3?v=`)).toBe(true);
    expect(url.length).toBeGreaterThan(`/audio/hello-${band}.mp3?v=`.length);
  }
});

it('creates no Audio until the first tap', () => {
  expect(MockAudio.instances).toHaveLength(0);
});

it('toggles play and stop on the same instance', async () => {
  toggleGreeting('primary');
  expect(MockAudio.instances).toHaveLength(1);
  const audio = MockAudio.instances[0];
  expect(audio.paused).toBe(false);
  await tick();
  expect(isGreetingPlaying()).toBe(true);
  toggleGreeting('primary');
  expect(MockAudio.instances).toHaveLength(1);
  expect(audio.paused).toBe(true);
  expect(isGreetingPlaying()).toBe(false);
});

it('switching bands swaps the clip', async () => {
  toggleGreeting('primary');
  await tick();
  expect(isGreetingPlaying()).toBe(true);
  toggleGreeting('middle');
  expect(MockAudio.instances).toHaveLength(2);
  expect(MockAudio.instances[0].paused).toBe(true);
  expect(MockAudio.instances[1].src).toContain('hello-middle');
  await tick();
  expect(isGreetingPlaying()).toBe(true);
});

it('stop quiets the clip and is a no-op when idle', () => {
  stopGreeting();
  expect(isGreetingPlaying()).toBe(false);
  toggleGreeting('upper');
  const audio = MockAudio.instances[0];
  expect(audio.paused).toBe(false);
  stopGreeting();
  expect(audio.paused).toBe(true);
  expect(audio.currentTime).toBe(0);
  expect(isGreetingPlaying()).toBe(false);
});

it('a missing file flips back to not playing', async () => {
  toggleGreeting('primary');
  await tick();
  expect(isGreetingPlaying()).toBe(true);
  MockAudio.instances[0].emit('error');
  expect(isGreetingPlaying()).toBe(false);
});

it('the clip ending flips back to not playing', async () => {
  toggleGreeting('primary');
  await tick();
  expect(isGreetingPlaying()).toBe(true);
  MockAudio.instances[0].emit('ended');
  expect(isGreetingPlaying()).toBe(false);
});
