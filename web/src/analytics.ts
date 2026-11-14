// PostHog product analytics for the page.
//
// Fully OFF until GET /api/config returns a project key: no SDK is loaded,
// no device id is read and every helper below is a silent no-op. Open-source
// safe, and tests need no network.
//
// Privacy: events carry small fixed scalar properties only (rooms, grades,
// counts, outcomes). Conversation text, typed text, homework content and
// images NEVER reach this module — the helpers take no free-text arguments.
// The family access code NEVER reaches PostHog either: the ?kod= parameter is
// stripped from the URL at startup (see consumeFamilyCodeFromUrl, called from
// main.tsx before init) and the before_send hook below scrubs it from every
// URL-like property as a second layer.

export type HomeworkKind = 'image' | 'pdf' | 'text';

const CONFIG_URL = '/api/config';
const DEVICE_KEY = 'open-tutor-device-id';

/** One id per page load: getDeviceId() never mints a second one, even when
 *  localStorage throws (private mode, blocked storage). Cached in the module
 *  so the id sent in /api/session always matches the one used in identify. */
let cachedDeviceId: string | null = null;

function mintDeviceId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `id-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
}

/** Random per-browser id. Mirrors nothing server-side; the worker links it. */
export function getDeviceId(): string {
  if (cachedDeviceId) return cachedDeviceId;
  try {
    const stored = localStorage.getItem(DEVICE_KEY);
    if (stored) {
      cachedDeviceId = stored;
      return stored;
    }
    const fresh = mintDeviceId();
    try {
      localStorage.setItem(DEVICE_KEY, fresh);
    } catch {
      /* storage blocked: still countable for this page load */
    }
    cachedDeviceId = fresh;
    return fresh;
  } catch {
    // localStorage itself throws: fall back to the page-load id, not a fresh
    // random one per call (the caller sends one id in /api/session and
    // another in identify otherwise).
    if (!cachedDeviceId) cachedDeviceId = mintDeviceId();
    return cachedDeviceId;
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

/** Drop the ?kod= access-code parameter from a URL string, keeping the rest
 *  (other params, hash, relative-vs-absolute shape) intact. */
export function stripKodFromUrl(raw: string): string {
  try {
    const absolute = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(raw);
    const parsed = new URL(raw, 'http://localhost');
    if (!parsed.searchParams.has('kod')) return raw;
    parsed.searchParams.delete('kod');
    if (absolute) return parsed.toString();
    const rest = `${parsed.pathname}${parsed.search}${parsed.hash}`;
    return raw.startsWith('/') ? rest : rest.replace(/^\//, '');
  } catch {
    // Unparseable input: regex fallback, then tidy stray separators.
    return raw
      .replace(/([?&])kod=[^&#]*/g, '$1')
      .replace(/[?&]($|#)/g, '$1')
      .replace(/\?&/, '?')
      .replace(/[?&]$/, '');
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type PostHogEvent = { properties?: Record<string, any> } & Record<string, any>;

/** PostHog before_send hook: scrub ?kod= from every URL-like property
 *  ($current_url, $referrer, $initial_* and any other string carrying it).
 *  Second layer behind the startup strip; never drops the event. */
export function sanitizePosthogEvent<T extends PostHogEvent>(event: T | null): T | null {
  if (!event) return event;
  const props = event.properties;
  if (props && typeof props === 'object') {
    for (const key of Object.keys(props)) {
      const value: unknown = props[key];
      if (typeof value === 'string' && value.includes('kod=')) {
        props[key] = stripKodFromUrl(value);
      }
    }
  }
  return event;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type PostHogClient = any;

let client: PostHogClient | null = null;
let initPromise: Promise<void> | null = null;
let initSettled = false;
/** page_opened fires exactly once per page load, even under StrictMode. */
let pageOpenedSent = false;
/** Identify requested before the SDK finished loading: applied after init. */
let pendingIdentify: { name: string; grade: number | null } | null = null;
/** Events fired before init completed: flushed after init, dropped when off. */
let pendingEvents: Array<{ event: string; properties?: Record<string, string | number | boolean | null> }> = [];
const MAX_PENDING = 32;

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
      // We emit page_opened ourselves (exactly once); the SDK must not add
      // its own pageview with the pre-scrub URL.
      capture_pageview: false,
      disable_session_recording: true,
      person_profiles: 'identified_only',
      persistence: 'localStorage',
      before_send: sanitizePosthogEvent,
    });
    return posthog;
  } catch {
    return null;
  }
}

/** Fetch /api/config and start PostHog only when it names a key. Idempotent.
 *  Anything tracked before init completes is queued and flushed once the
 *  client exists; when analytics is off the queue is dropped, never sent. */
export function initAnalytics(): Promise<void> {
  if (client) return Promise.resolve();
  if (!initPromise) {
    initPromise = loadClient().then((loaded) => {
      client = loaded;
      initSettled = true;
      if (client) {
        if (pendingIdentify) {
          const { name, grade } = pendingIdentify;
          pendingIdentify = null;
          doIdentify(name, grade);
        }
        const queued = pendingEvents;
        pendingEvents = [];
        for (const { event, properties } of queued) track(event, properties);
      } else {
        pendingIdentify = null;
        pendingEvents = [];
      }
    });
  }
  return initPromise;
}

/** For tests: forget the client so initAnalytics() runs again. */
export function resetAnalytics(): void {
  client = null;
  initPromise = null;
  initSettled = false;
  pageOpenedSent = false;
  pendingIdentify = null;
  pendingEvents = [];
  cachedDeviceId = null;
}

export function analyticsEnabled(): boolean {
  return client !== null;
}

function track(event: string, properties?: Record<string, string | number | boolean | null>): void {
  if (client) {
    try {
      client.capture(event, properties ?? {});
    } catch {
      /* analytics must never break the lesson */
    }
    return;
  }
  // Init not finished: queue for the flush in initAnalytics. Init finished
  // without a client means analytics is off: drop, never send later.
  if (!initSettled && pendingEvents.length < MAX_PENDING) {
    pendingEvents.push({ event, properties });
  }
}

export function pageOpened(): void {
  if (pageOpenedSent) return;
  pageOpenedSent = true;
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

function doIdentify(name: string, grade: number | null): void {
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

export function identifyLearner(name: string, grade: number | null): void {
  if (client) {
    doIdentify(name, grade);
    return;
  }
  // The SDK may still be loading while the session starts: remember the
  // identify and apply it after init. When analytics is off it is dropped.
  if (!initSettled) pendingIdentify = { name, grade };
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
