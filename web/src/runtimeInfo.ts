/**
 * Sessionsinfo: worker-supplied runtime metadata plus browser-owned Screen facts.
 *
 * The worker publishes its side as the `tutor.runtime` participant attribute
 * (JSON, see server/open_tutor/runtime_info.py). That payload is `unknown`
 * until `parseRuntimeInfo` validates it here at the boundary — the same
 * manual-guard style as `validate.ts`, no runtime-schema dependency and no
 * `as` casts. The Screen section below is appended by the browser from its
 * own actual configuration. The same-origin proxy forwards this model ID.
 */
import { version as livekitVersion } from 'livekit-client';
import { PI_AI_VERSION } from '@earendil-works/pi-ai/utils/version';
import { SCREEN_MODEL_ID, SCREEN_THINKING_LEVEL } from './screen/screenConfig';

export type RuntimeField = { label: string; value: string };
export type RuntimeSection = { title: string; fields: RuntimeField[] };
export type RuntimeInfo = { version: 1; sections: RuntimeSection[] };

const MAX_SECTIONS = 12;
const MAX_FIELDS = 24;
const MAX_TITLE = 120;
const MAX_VALUE = 500;

function isRecord(raw: unknown): raw is Record<string, unknown> {
  return typeof raw === 'object' && raw !== null && !Array.isArray(raw);
}

function isBoundedString(raw: unknown, max: number, allowEmpty: boolean): raw is string {
  return typeof raw === 'string'
    && raw.length <= max
    && (allowEmpty || raw.length > 0);
}

/** Strictly parse worker runtime metadata. Returns null on any violation. */
export function parseRuntimeInfo(raw: unknown): RuntimeInfo | null {
  if (!isRecord(raw)) return null;
  if (raw.version !== 1) return null;
  if (!Array.isArray(raw.sections) || raw.sections.length === 0 || raw.sections.length > MAX_SECTIONS) {
    return null;
  }
  const sections: RuntimeSection[] = [];
  for (const entry of raw.sections) {
    if (!isRecord(entry)) return null;
    if (!isBoundedString(entry.title, MAX_TITLE, false)) return null;
    if (!Array.isArray(entry.fields) || entry.fields.length === 0 || entry.fields.length > MAX_FIELDS) {
      return null;
    }
    const fields: RuntimeField[] = [];
    for (const item of entry.fields) {
      if (!isRecord(item)) return null;
      if (!isBoundedString(item.label, MAX_TITLE, false)) return null;
      if (!isBoundedString(item.value, MAX_VALUE, true)) return null;
      fields.push({ label: item.label, value: item.value });
    }
    sections.push({ title: entry.title, fields });
  }
  return { version: 1, sections };
}

/** The browser-owned Screen section, built from actual Screen configuration. */
export function buildScreenSection(): RuntimeSection {
  const livekit = typeof livekitVersion === 'string' && livekitVersion ? livekitVersion : 'okänd';
  const piAi = typeof PI_AI_VERSION === 'string' && PI_AI_VERSION ? PI_AI_VERSION : 'okänd';
  return {
    title: 'Skärm (webbläsare)',
    fields: [
      { label: 'Modell', value: SCREEN_MODEL_ID },
      { label: 'Resonemang', value: SCREEN_THINKING_LEVEL },
      { label: 'Körs i', value: 'webbläsaren (Pi Durable-harness i Web Worker)' },
      { label: 'Lagring', value: 'IndexedDB (per profil)' },
      { label: 'Anrop', value: 'Chat Completions via samma ursprung /api/screen/openai' },
      { label: 'SDK', value: `livekit-client ${livekit}, pi-ai ${piAi}` },
      { label: 'Webbapp', value: window.location.origin },
    ],
  };
}
