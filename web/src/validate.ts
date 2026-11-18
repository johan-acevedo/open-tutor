// Validation for incoming board RPC payloads (docs/protocol.md).
// Unknown kinds are rejected so the RPC handler can answer with an error.

import type { BoardFocusPayload, BoardItem } from './protocol';

export type ValidateOk = { ok: true; item: BoardItem };
export type ValidateErr = { ok: false; error: string };
export type ValidateResult = ValidateOk | ValidateErr;

// 2026-11-18: text, steps, mindmap, svg, html and material are gone; nothing produces them.
const KNOWN_KINDS = new Set(['image', 'pending', 'resource', 'homework', 'page']);

// LiveKit RPC payloads stay small; only the body travels, the web app holds the shell.
const PAGE_BODY_MAX = 20000;

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function isNonEmptyString(v: unknown): v is string {
  return typeof v === 'string' && v.length > 0;
}

function optString(v: unknown): v is string | undefined {
  return v === undefined || typeof v === 'string';
}

/** Parse + validate a board.show / board.update payload. */
export function validateBoardItem(raw: unknown): ValidateResult {
  if (!isRecord(raw)) return { ok: false, error: 'BoardItem must be an object' };
  if (!isNonEmptyString(raw.id)) return { ok: false, error: 'BoardItem.id must be a non-empty string' };
  if (typeof raw.kind !== 'string' || !KNOWN_KINDS.has(raw.kind)) {
    return { ok: false, error: `Unknown board kind: ${String(raw.kind)}` };
  }
  const id = raw.id as string;
  if (!optString(raw.title)) return { ok: false, error: 'BoardItem.title must be a string' };
  const title = raw.title as string | undefined;

  switch (raw.kind) {
    case 'image': {
      if (typeof raw.url !== 'string' || typeof raw.alt !== 'string') {
        return { ok: false, error: 'image item needs url and alt strings' };
      }
      return { ok: true, item: { id, kind: 'image', title, url: raw.url, alt: raw.alt } };
    }
    case 'pending': {
      if (typeof raw.title !== 'string') return { ok: false, error: 'pending item needs title string' };
      if (raw.height !== undefined && typeof raw.height !== 'number') {
        return { ok: false, error: 'pending height must be a number' };
      }
      return {
        ok: true,
        item: {
          id,
          kind: 'pending',
          title: raw.title,
          ...(typeof raw.height === 'number' ? { height: raw.height } : {}),
        },
      };
    }
    case 'resource': {
      if (typeof raw.title !== 'string' || typeof raw.url !== 'string') {
        return { ok: false, error: 'resource item needs title and url strings' };
      }
      if (raw.embedUrl !== undefined && typeof raw.embedUrl !== 'string') {
        return { ok: false, error: 'resource embedUrl must be a string' };
      }
      if (raw.source !== undefined && typeof raw.source !== 'string') {
        return { ok: false, error: 'resource source must be a string' };
      }
      if (raw.prompt !== undefined && typeof raw.prompt !== 'string') {
        return { ok: false, error: 'resource prompt must be a string' };
      }
      return {
        ok: true,
        item: {
          id,
          kind: 'resource',
          title: raw.title,
          url: raw.url,
          ...(typeof raw.embedUrl === 'string' ? { embedUrl: raw.embedUrl } : {}),
          ...(typeof raw.source === 'string' ? { source: raw.source } : {}),
          ...(typeof raw.prompt === 'string' ? { prompt: raw.prompt } : {}),
        },
      };
    }
    case 'page': {
      if (typeof raw.title !== 'string') return { ok: false, error: 'page item needs title string' };
      if (typeof raw.body !== 'string') return { ok: false, error: 'page item needs body string' };
      if (raw.body.length > PAGE_BODY_MAX) {
        return { ok: false, error: `page body must be at most ${PAGE_BODY_MAX} characters` };
      }
      return { ok: true, item: { id, kind: 'page', title: raw.title, body: raw.body } };
    }
    case 'homework': {
      if (typeof raw.title !== 'string') return { ok: false, error: 'homework item needs title string' };
      if (raw.images !== undefined && (!Array.isArray(raw.images) || !raw.images.every((i) => typeof i === 'string'))) {
        return { ok: false, error: 'homework images must be a string array' };
      }
      if (raw.text !== undefined && typeof raw.text !== 'string') {
        return { ok: false, error: 'homework text must be a string' };
      }
      return {
        ok: true,
        item: {
          id,
          kind: 'homework',
          title: raw.title,
          ...(Array.isArray(raw.images) ? { images: raw.images as string[] } : {}),
          ...(typeof raw.text === 'string' ? { text: raw.text } : {}),
        },
      };
    }
    default:
      return { ok: false, error: `Unknown board kind: ${String(raw.kind)}` };
  }
}

export type FocusOk = { ok: true; focus: BoardFocusPayload };
export type FocusErr = { ok: false; error: string };

/** Parse + validate a board.focus payload: { id }. */
export function validateBoardFocus(raw: unknown): FocusOk | FocusErr {
  if (!isRecord(raw)) return { ok: false, error: 'focus payload must be an object' };
  if (!isNonEmptyString(raw.id)) return { ok: false, error: 'focus payload needs id string' };
  return { ok: true, focus: { id: raw.id } };
}

export type PageOpOk = { ok: true; id: string; arg: string };
export type PageOpErr = { ok: false; error: string };

export type LoadingOk = { ok: true; id: string; topic: string };
export type LoadingErr = { ok: false; error: string };

/** Parse + validate a board.patch / board.reveal / board.point payload: { id, patch|part }. */
export function validateBoardPageOp(raw: unknown, field: 'patch' | 'part'): PageOpOk | PageOpErr {
  if (!isRecord(raw)) return { ok: false, error: 'page op payload must be an object' };
  if (!isNonEmptyString(raw.id)) return { ok: false, error: 'page op payload needs id string' };
  const arg = raw[field];
  if (!isNonEmptyString(arg)) return { ok: false, error: `page op payload needs ${field} string` };
  return { ok: true, id: raw.id, arg };
}

/** Parse + validate a board.loading payload: { id, topic }. An empty topic clears. */
export function validateBoardLoading(raw: unknown): LoadingOk | LoadingErr {
  if (!isRecord(raw)) return { ok: false, error: 'loading payload must be an object' };
  if (!isNonEmptyString(raw.id)) return { ok: false, error: 'loading payload needs id string' };
  if (typeof raw.topic !== 'string') return { ok: false, error: 'loading payload needs topic string' };
  if (raw.topic.length > 120) return { ok: false, error: 'loading topic must be at most 120 characters' };
  return { ok: true, id: raw.id, topic: raw.topic };
}

/** Loose check for incoming note payloads (topic 'note'). */
export function isNoteLike(raw: unknown): raw is { topic: string } & Record<string, unknown> {
  return isRecord(raw) && typeof raw.topic === 'string';
}
