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
  sanitizePosthogEvent,
  sessionEnded,
  sessionFailed,
  sessionStarted,
  sessionStartRequested,
  stableLearnerId,
  stripKodFromUrl,
  turnSent,
} from './analytics';
import {
  consumeFamilyCodeFromUrl,
  familyCode,
  rememberFamilyCode,
  resetFamilyCodeForTests,
} from './useSession';

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
        capture_pageview: false,
        disable_session_recording: true,
        person_profiles: 'identified_only',
        persistence: 'localStorage',
        before_send: expect.any(Function),
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

  it('strips the kod access code from the URL at startup', () => {
    window.history.replaceState(null, '', '/?kod=SECRET123');
    expect(consumeFamilyCodeFromUrl()).toBe('SECRET123');
    expect(window.location.search).toBe('');
    expect(window.location.href).not.toContain('SECRET123');
    // Remembered for the session request.
    expect(localStorage.getItem('open-tutor-code')).toBe('SECRET123');
    // Second call finds no kod: the code now comes from storage.
    expect(consumeFamilyCodeFromUrl()).toBeNull();
    window.history.replaceState(null, '', '/');
  });

  it('scrubs kod from URL-like properties via the before_send hook', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(configResponse(POSTHOG_KEY)));
    await initAnalytics();
    const beforeSend = posthogMock.init.mock.calls[0][1].before_send as (
      event: Record<string, unknown>,
    ) => Record<string, unknown> | null;
    expect(typeof beforeSend).toBe('function');
    const cleaned = beforeSend({
      event: 'page_opened',
      properties: {
        $current_url: 'https://tutor.example/?kod=SECRET123&foo=1',
        $referrer: 'https://tutor.example/?kod=SECRET123',
        room: 'tutor-x',
      },
    }) as { properties: Record<string, unknown> };
    expect(JSON.stringify(cleaned)).not.toContain('SECRET123');
    expect(JSON.stringify(cleaned)).not.toContain('kod=');
    expect(cleaned.properties['room']).toBe('tutor-x');
    expect(cleaned.properties['$current_url']).toBe('https://tutor.example/?foo=1');
    expect(cleaned.properties['$referrer']).toBe('https://tutor.example/');
    // Events without kod pass through untouched.
    const plain = { event: 'x', properties: { room: 'tutor-x' } };
    expect(sanitizePosthogEvent(plain)).toBe(plain);
  });

  it('stripKodFromUrl keeps the rest of the URL intact', () => {
    expect(stripKodFromUrl('https://tutor.example/?kod=abc&foo=1')).toBe('https://tutor.example/?foo=1');
    expect(stripKodFromUrl('https://tutor.example/?foo=1&kod=abc')).toBe('https://tutor.example/?foo=1');
    expect(stripKodFromUrl('https://tutor.example/?kod=abc')).toBe('https://tutor.example/');
    expect(stripKodFromUrl('https://tutor.example/?foo=1')).toBe('https://tutor.example/?foo=1');
    expect(stripKodFromUrl('/?kod=abc')).toBe('/');
    expect(stripKodFromUrl('/')).toBe('/');
    // Percent-encoded parameter names are the same parameter.
    expect(stripKodFromUrl('https://tutor.example/?%6bod=SECRET&foo=1')).toBe('https://tutor.example/?foo=1');
  });

  it('scrubs a percent-encoded kod from the referrer', () => {
    const cleaned = sanitizePosthogEvent({
      event: 'page_opened',
      properties: { $referrer: 'https://x.example/?%6Bod=SECRET', $session_entry_referrer: 'https://x.example/?%6bod=SECRET' },
    });
    expect(JSON.stringify(cleaned)).not.toContain('SECRET');
  });

  it('returns one stable device id per page load when localStorage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    resetAnalytics();
    const first = getDeviceId();
    const second = getDeviceId();
    expect(first).toBeTruthy();
    expect(second).toBe(first);
    vi.restoreAllMocks();
    resetAnalytics();
  });

  it('queues events and the identify before init completes, firing page_opened once', async () => {
    let resolveConfig!: (value: unknown) => void;
    const gate = new Promise((resolve) => {
      resolveConfig = resolve;
    });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockReturnValue(gate.then(() => configResponse(POSTHOG_KEY))),
    );
    const ready = initAnalytics();
    // Fired while the SDK is still loading (StrictMode would double-fire these).
    pageOpened();
    pageOpened();
    sessionStartRequested();
    identifyLearner('Leo', 8);
    expect(posthogMock.capture).not.toHaveBeenCalled();
    resolveConfig(undefined);
    await ready;
    expect(analyticsEnabled()).toBe(true);
    const events = posthogMock.capture.mock.calls.map(([event]) => event);
    expect(events.filter((e) => e === 'page_opened')).toHaveLength(1);
    expect(events).toContain('session_start_requested');
    expect(posthogMock.identify).toHaveBeenCalledTimes(1);
    const device = getDeviceId();
    expect(posthogMock.identify).toHaveBeenCalledWith(`device:${device}:learner:leo`, {
      learner_name: 'Leo',
      grade: 8,
    });
  });

  it('drops queued events when analytics is off', async () => {
    let resolveConfig!: (value: unknown) => void;
    const gate = new Promise((resolve) => {
      resolveConfig = resolve;
    });
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(gate.then(() => configResponse(null))));
    const ready = initAnalytics();
    pageOpened();
    identifyLearner('Leo', 8);
    resolveConfig(undefined);
    await ready;
    expect(analyticsEnabled()).toBe(false);
    expect(posthogMock.capture).not.toHaveBeenCalled();
    expect(posthogMock.identify).not.toHaveBeenCalled();
  });
});

describe('kod scrubbing against the real posthog-js SDK', () => {
  beforeEach(() => {
    resetAnalytics();
    posthogMock.init.mockClear();
    posthogMock.capture.mockClear();
    posthogMock.identify.mockClear();
    localStorage.clear();
    vi.unstubAllGlobals();
  });
  it('strips kod from $set/$set_once on identify, including a coded referrer', async () => {
    const real = await vi.importActual<typeof import('posthog-js')>('posthog-js');
    const ph = real.default;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const seen: Array<Record<string, any>> = [];
    window.history.replaceState(null, '', '/?kod=SECRET123&foo=1');
    Object.defineProperty(document, 'referrer', {
      value: 'https://skola.se/sida?kod=SECRET123',
      configurable: true,
    });
    try {
      ph.init('phc_scrub_test', {
        api_host: 'https://eu.i.posthog.com',
        autocapture: false,
        capture_pageview: false,
        disable_session_recording: true,
        advanced_disable_decide: true,
        person_profiles: 'identified_only',
        persistence: 'localStorage',
        // Our hook on the real SDK's event shapes; returning null drops the
        // event so the test sends nothing.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        before_send: (event: any) => {
          const cleaned = sanitizePosthogEvent(event);
          if (cleaned) seen.push(JSON.parse(JSON.stringify(cleaned)));
          return null;
        },
      });
      const device = getDeviceId();
      ph.identify(stableLearnerId(device, 'Leo'));
      ph.capture('turn_sent', { modality: 'typed' });

      expect(seen.length).toBeGreaterThan(0);
      const payload = JSON.stringify(seen);
      expect(payload).not.toContain('SECRET123');
      expect(payload).not.toContain('kod=');

      // The regression: $identify keeps the page URL in top-level
      // $set_once.$initial_current_url and a coded referrer in
      // $set_once.$initial_referrer — both must be scrubbed, not dropped.
      const identify = seen.find((e) => e.event === '$identify');
      expect(identify).toBeDefined();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const setOnce = (identify as Record<string, any>)['$set_once'];
      expect(setOnce).toBeDefined();
      expect(setOnce['$initial_current_url']).toBe('http://localhost:3000/?foo=1');
      expect(setOnce['$initial_referrer']).toBe('https://skola.se/sida');
    } finally {
      Object.defineProperty(document, 'referrer', { value: '', configurable: true });
      window.history.replaceState(null, '', '/');
    }
  });
});

describe('pre-init queue ordering', () => {
  beforeEach(() => {
    resetAnalytics();
    posthogMock.init.mockClear();
    posthogMock.capture.mockClear();
    posthogMock.identify.mockClear();
    localStorage.clear();
    vi.unstubAllGlobals();
  });
  it('replays identify transitions in order (A, A-events, B, B-events)', async () => {
    let resolveConfig!: (value: unknown) => void;
    const gate = new Promise((resolve) => {
      resolveConfig = resolve;
    });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockReturnValue(gate.then(() => configResponse(POSTHOG_KEY))),
    );
    const ready = initAnalytics();
    identifyLearner('Anna', 3);
    turnSent();
    identifyLearner('Bella', 4);
    homeworkShared('image');
    resolveConfig(undefined);
    await ready;
    expect(analyticsEnabled()).toBe(true);
    const device = getDeviceId();
    expect(posthogMock.identify).toHaveBeenCalledTimes(2);
    expect(posthogMock.identify).toHaveBeenNthCalledWith(1, `device:${device}:learner:anna`, {
      learner_name: 'Anna',
      grade: 3,
    });
    expect(posthogMock.identify).toHaveBeenNthCalledWith(2, `device:${device}:learner:bella`, {
      learner_name: 'Bella',
      grade: 4,
    });
    expect(posthogMock.capture.mock.calls.map(([event]) => event)).toEqual([
      'turn_sent',
      'homework_shared',
    ]);
  });
});

describe('family code without storage', () => {
  beforeEach(() => {
    resetAnalytics();
    localStorage.clear();
    vi.unstubAllGlobals();
    resetFamilyCodeForTests();
  });
  function blockStorage() {
    const getItem = vi
      .spyOn(Storage.prototype, 'getItem')
      .mockImplementation(() => {
        throw new Error('blocked');
      });
    const setItem = vi
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new Error('blocked');
      });
    return () => {
      getItem.mockRestore();
      setItem.mockRestore();
    };
  }

  it('keeps the URL code in memory when storage throws', () => {
    resetFamilyCodeForTests();
    const unblock = blockStorage();
    try {
      window.history.replaceState(null, '', '/?kod=URLKOD123');
      expect(familyCode()).toBe('URLKOD123'); // consumed from the URL...
      expect(window.location.search).toBe(''); // ...and scrubbed from the URL
      expect(familyCode()).toBe('URLKOD123'); // ...and remembered without storage
    } finally {
      unblock();
      window.history.replaceState(null, '', '/');
      resetFamilyCodeForTests();
    }
  });

  it('keeps a typed prompt code in memory when storage throws', () => {
    resetFamilyCodeForTests();
    const unblock = blockStorage();
    try {
      rememberFamilyCode('PROMPTKOD');
      expect(familyCode()).toBe('PROMPTKOD'); // the retry reuses it
      expect(familyCode()).toBe('PROMPTKOD');
    } finally {
      unblock();
      resetFamilyCodeForTests();
    }
  });
});
