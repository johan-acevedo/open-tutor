import { beforeEach, describe, expect, it, vi } from 'vitest';

const POSTHOG_KEY = 'phc_testkey';

const posthogMock = vi.hoisted(() => ({
  init: vi.fn(),
  capture: vi.fn(),
  identify: vi.fn(),
}));

vi.mock('posthog-js', () => ({ default: posthogMock }));

import {
  accessCodeResult,
  analyticsEnabled,
  getDeviceId,
  homeworkShared,
  identifyLearner,
  initAnalytics,
  micPermission,
  pageOpened,
  resetAnalytics,
  resourceOpened,
  sessionEnded,
  sessionFailed,
  sessionStarted,
  sessionStartRequested,
  stableLearnerId,
  turnSent,
} from './analytics';

function configResponse(key: string | null) {
  return {
    ok: true,
    json: () => Promise.resolve(key ? { posthog: { key, host: 'https://eu.i.posthog.com' } } : { posthog: null }),
  };
}

describe('analytics', () => {
  beforeEach(() => {
    resetAnalytics();
    posthogMock.init.mockClear();
    posthogMock.capture.mockClear();
    posthogMock.identify.mockClear();
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it('is a no-op without a configured key: no SDK init, no events', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(configResponse(null)));
    await initAnalytics();
    expect(analyticsEnabled()).toBe(false);
    expect(posthogMock.init).not.toHaveBeenCalled();
    pageOpened();
    accessCodeResult(true);
    micPermission(true);
    sessionStartRequested();
    identifyLearner('Leo', 8);
    sessionStarted('tutor-x');
    sessionFailed(500);
    sessionEnded('ended_by_child', 60);
    turnSent();
    homeworkShared('image');
    resourceOpened();
    expect(posthogMock.capture).not.toHaveBeenCalled();
    expect(posthogMock.identify).not.toHaveBeenCalled();
  });

  it('stays off when /api/config fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    await initAnalytics();
    expect(analyticsEnabled()).toBe(false);
    pageOpened();
    expect(posthogMock.capture).not.toHaveBeenCalled();
  });

  it('initialises once with the privacy settings when a key is configured', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(configResponse(POSTHOG_KEY)));
    await initAnalytics();
    await initAnalytics();
    expect(analyticsEnabled()).toBe(true);
    expect(posthogMock.init).toHaveBeenCalledTimes(1);
    expect(posthogMock.init).toHaveBeenCalledWith(
      POSTHOG_KEY,
      expect.objectContaining({
        api_host: 'https://eu.i.posthog.com',
        autocapture: false,
        capture_pageview: true,
        disable_session_recording: true,
        person_profiles: 'identified_only',
        persistence: 'localStorage',
      }),
    );
  });

  it('emits the fixed event set with small scalar properties only', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(configResponse(POSTHOG_KEY)));
    await initAnalytics();
    pageOpened();
    accessCodeResult(false);
    micPermission(true);
    sessionStartRequested();
    sessionStarted('tutor-abc');
    sessionFailed(503);
    sessionEnded('ended_by_child', 61.5);
    turnSent();
    homeworkShared('pdf');
    resourceOpened();

    const calls = posthogMock.capture.mock.calls as Array<[string, Record<string, unknown>]>;
    expect(calls.map(([event]) => event)).toEqual([
      'page_opened',
      'access_code_result',
      'mic_permission',
      'session_start_requested',
      'session_started',
      'session_failed',
      'session_ended',
      'turn_sent',
      'homework_shared',
      'resource_opened',
    ]);
    const byEvent = Object.fromEntries(calls);
    expect(byEvent['access_code_result']).toEqual({ ok: false });
    expect(byEvent['mic_permission']).toEqual({ granted: true });
    expect(byEvent['session_started']).toEqual({ room: 'tutor-abc' });
    expect(byEvent['session_failed']).toEqual({ status: 503 });
    expect(byEvent['session_ended']).toEqual({ reason: 'ended_by_child', duration_s: 61.5 });
    expect(byEvent['turn_sent']).toEqual({ modality: 'typed' });
    expect(byEvent['homework_shared']).toEqual({ kind: 'pdf' });

    // Allowlisted property keys per event: nothing else can leave the browser.
    const allowed: Record<string, string[]> = {
      page_opened: [],
      access_code_result: ['ok'],
      mic_permission: ['granted'],
      session_start_requested: [],
      session_started: ['room'],
      session_failed: ['status'],
      session_ended: ['reason', 'duration_s'],
      turn_sent: ['modality'],
      homework_shared: ['kind'],
      resource_opened: [],
    };
    for (const [event, props] of calls) {
      expect(Object.keys(props).sort()).toEqual([...allowed[event]].sort());
    }
    // No conversation text, homework content or images anywhere in the payload.
    const hostile = 'hemlig läxtext som aldrig får lämna webbläsaren 98765';
    expect(JSON.stringify(calls)).not.toContain(hostile);
    expect(JSON.stringify(calls)).not.toContain('data:image');
  });

  it('identifies the learner with the stable device+name id and person properties', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(configResponse(POSTHOG_KEY)));
    await initAnalytics();
    const device = getDeviceId();
    expect(device).toBeTruthy();
    expect(getDeviceId()).toBe(device); // stable in this browser
    identifyLearner('Leo', 8);
    expect(posthogMock.identify).toHaveBeenCalledWith(`device:${device}:learner:leo`, {
      learner_name: 'Leo',
      grade: 8,
    });
  });

  it('derives the same stable id as the worker: case and spacing collapse', () => {
    expect(stableLearnerId('dev-1', 'Leo')).toBe('device:dev-1:learner:leo');
    expect(stableLearnerId('dev-1', '  LEO  ')).toBe('device:dev-1:learner:leo');
    expect(stableLearnerId('dev-1', 'Anna  Maria')).toBe('device:dev-1:learner:anna maria');
  });
});
