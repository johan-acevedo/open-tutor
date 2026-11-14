// PostHog product analytics for the page.
//
// Fully OFF until GET /api/config returns a project key: no SDK is loaded,
// no device id is read and every helper below is a silent no-op. Open-source
// safe, and tests need no network.
//
// Privacy: events carry small fixed scalar properties only (rooms, grades,
// counts, outcomes). Conversation text, typed text, homework content and
// images NEVER reach this module — the helpers take no free-text arguments.

export type HomeworkKind = 'image' | 'pdf' | 'text';

const CONFIG_URL = '/api/config';
const DEVICE_KEY = 'open-tutor-device-id';

/** Random per-browser id. Mirrors nothing server-side; the worker links it. */
export function getDeviceId(): string {
  try {
    const stored = localStorage.getItem(DEVICE_KEY);
    if (stored) return stored;
    const fresh =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `id-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
    try {
      localStorage.setItem(DEVICE_KEY, fresh);
    } catch {
      /* storage blocked: still countable for this page load */
    }
    return fresh;
  } catch {
    return `id-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
  }
}

/** One learner on one device. MUST match analytics.stable_distinct_id (Python):
 *  lowercase, trimmed, single-spaced name. */
export function stableLearnerId(deviceId: string, name: string): string {
  const device = (deviceId || '').trim();
  if (!device) return '';
  const normalized = (name || '').trim().toLowerCase().split(/\s+/).join(' ');
  if (!normalized) return `device:${device}`;
  return `device:${device}:learner:${normalized}`;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type PostHogClient = any;

let client: PostHogClient | null = null;
let initPromise: Promise<void> | null = null;

async function loadClient(): Promise<PostHogClient | null> {
  let config: { posthog: { key: string; host: string } | null };
  try {
    const res = await fetch(CONFIG_URL, { headers: { Accept: 'application/json' } });
    if (!res.ok) return null;
    config = (await res.json()) as typeof config;
  } catch {
    return null;
  }
  if (!config?.posthog?.key) return null;
  try {
    const { default: posthog } = await import('posthog-js');
    posthog.init(config.posthog.key, {
      api_host: config.posthog.host,
      autocapture: false,
      capture_pageview: true,
      disable_session_recording: true,
      person_profiles: 'identified_only',
      persistence: 'localStorage',
    });
    return posthog;
  } catch {
    return null;
  }
}

/** Fetch /api/config and start PostHog only when it names a key. Idempotent. */
export function initAnalytics(): Promise<void> {
  if (client) return Promise.resolve();
  if (!initPromise) {
    initPromise = loadClient().then((loaded) => {
      client = loaded;
    });
  }
  return initPromise;
}

/** For tests: forget the client so initAnalytics() runs again. */
export function resetAnalytics(): void {
  client = null;
  initPromise = null;
}

export function analyticsEnabled(): boolean {
  return client !== null;
}

function track(event: string, properties?: Record<string, string | number | boolean | null>): void {
  if (!client) return;
  try {
    client.capture(event, properties ?? {});
  } catch {
    /* analytics must never break the lesson */
  }
}

export function pageOpened(): void {
  track('page_opened');
}

export function accessCodeResult(ok: boolean): void {
  track('access_code_result', { ok });
}

export function micPermission(granted: boolean): void {
  track('mic_permission', { granted });
}

export function sessionStartRequested(): void {
  track('session_start_requested');
}

export function identifyLearner(name: string, grade: number | null): void {
  if (!client) return;
  try {
    client.identify(stableLearnerId(getDeviceId(), name), {
      learner_name: name,
      grade,
    });
  } catch {
    /* analytics must never break the lesson */
  }
}

export function sessionStarted(room: string): void {
  track('session_started', { room });
}

export function sessionFailed(status: string | number): void {
  track('session_failed', { status });
}

export function sessionEnded(reason: string, durationS: number): void {
  track('session_ended', { reason, duration_s: durationS });
}

export function turnSent(): void {
  // Typed turns only; spoken turns are counted worker-side.
  track('turn_sent', { modality: 'typed' });
}

export function homeworkShared(kind: HomeworkKind): void {
  track('homework_shared', { kind });
}

export function resourceOpened(): void {
  track('resource_opened');
}
