// Validation for incoming board RPC payloads (docs/protocol.md).
// Unknown kinds are rejected so the RPC handler can answer with an error.

import type { BoardFocusPayload, BoardItem, DiagramItem } from './protocol';
import {
  DIAGRAM_COORD_LIMIT,
  DIAGRAM_ID,
  DIAGRAM_MAX_LINKS,
  DIAGRAM_MAX_NODES,
  DIAGRAM_ROLES,
} from './diagramLimits';

export type ValidateOk = { ok: true; item: BoardItem };
export type ValidateErr = { ok: false; error: string };
export type ValidateResult = ValidateOk | ValidateErr;

const KNOWN_KINDS = new Set([
  'text',
  'steps',
  'mindmap',
  'svg',
  'html',
  'image',
  'pending',
  'resource',
  'homework',
  'diagram',
]);

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function isNonEmptyString(v: unknown): v is string {
  return typeof v === 'string' && v.length > 0;
}

function optString(v: unknown): v is string | undefined {
  return v === undefined || typeof v === 'string';
}

function validateDiagram(raw: Record<string, unknown>, id: string, title: string | undefined): ValidateResult {
  const bad = (error: string): ValidateErr => ({ ok: false, error: `diagram: ${error}` });
  if (typeof raw.rev !== 'number' || !Number.isInteger(raw.rev) || raw.rev < 1) return bad('rev must be a positive integer');
  if (raw.layout !== 'radial' && raw.layout !== 'flow') return bad('layout must be radial or flow');
  if (!Array.isArray(raw.nodes) || raw.nodes.length === 0 || raw.nodes.length > DIAGRAM_MAX_NODES) {
    return bad(`nodes must hold 1 to ${DIAGRAM_MAX_NODES} items`);
  }
  const links = raw.links ?? [];
  if (!Array.isArray(links) || links.length > DIAGRAM_MAX_LINKS) return bad(`links must hold at most ${DIAGRAM_MAX_LINKS} items`);
  const focus = raw.focus ?? [];
  if (!Array.isArray(focus) || !focus.every((f) => typeof f === 'string')) return bad('focus must be a string array');

  const seen = new Set<string>();
  const nodes: DiagramItem['nodes'] = [];
  for (const n of raw.nodes) {
    if (!isRecord(n) || typeof n.id !== 'string' || !DIAGRAM_ID.test(n.id)) return bad('node id is missing or malformed');
    if (typeof n.text !== 'string' || n.text.length === 0 || n.text.length > 60) return bad(`node ${n.id} needs text of 1 to 60 characters`);
    const role = n.role === undefined ? 'idea' : n.role;
    if (typeof role !== 'string' || !(DIAGRAM_ROLES as readonly string[]).includes(role)) return bad(`node ${n.id} has an unknown role`);
    const { x, y } = n;
    if (typeof x !== 'number' || typeof y !== 'number' || !Number.isFinite(x) || !Number.isFinite(y)) return bad(`node ${n.id} needs numeric x and y`);
    if (Math.abs(x) > DIAGRAM_COORD_LIMIT || Math.abs(y) > DIAGRAM_COORD_LIMIT) return bad(`node ${n.id} is outside the scene bounds`);
    if (seen.has(n.id)) return bad(`id ${n.id} is used twice`);
    seen.add(n.id);
    nodes.push({ id: n.id, text: n.text, role: role as DiagramItem['nodes'][number]['role'], x, y });
  }
  const outLinks: DiagramItem['links'] = [];
  for (const l of links) {
    if (!isRecord(l) || typeof l.id !== 'string' || !DIAGRAM_ID.test(l.id)) return bad('link id is missing or malformed');
    if (typeof l.source !== 'string' || typeof l.target !== 'string' || !seen.has(l.source) || !seen.has(l.target)) {
      return bad(`link ${l.id} points at a node that does not exist`);
    }
    if (l.label !== undefined && (typeof l.label !== 'string' || l.label.length > 30)) return bad(`link ${l.id} label is invalid`);
    if (seen.has(l.id)) return bad(`id ${l.id} is used twice`);
    seen.add(l.id);
    outLinks.push({ id: l.id, source: l.source, target: l.target, ...(typeof l.label === 'string' && l.label ? { label: l.label } : {}) });
  }
  if (!focus.every((f) => seen.has(f as string))) return bad('focus names an id that does not exist');
  return {
    ok: true,
    item: { id, kind: 'diagram', title, rev: raw.rev, layout: raw.layout, nodes, links: outLinks, focus: focus as string[] },
  };
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
    case 'text': {
      if (typeof raw.markdown !== 'string') return { ok: false, error: 'text item needs markdown string' };
      return { ok: true, item: { id, kind: 'text', title, markdown: raw.markdown } };
    }
    case 'steps': {
      if (!Array.isArray(raw.steps) || raw.steps.length === 0) {
        return { ok: false, error: 'steps item needs a non-empty steps array' };
      }
      for (const s of raw.steps) {
        if (!isRecord(s) || typeof s.tex !== 'string') {
          return { ok: false, error: 'each step needs a tex string' };
        }
        if (s.note !== undefined && typeof s.note !== 'string') {
          return { ok: false, error: 'step note must be a string' };
        }
        if (s.op !== undefined && typeof s.op !== 'string') {
          return { ok: false, error: 'step op must be a string' };
        }
      }
      return {
        ok: true,
        item: {
          id,
          kind: 'steps',
          title,
          steps: raw.steps.map((s) => {
            const r = s as Record<string, unknown>;
            const step: { tex: string; note?: string; op?: string } = { tex: r.tex as string };
            if (typeof r.note === 'string') step.note = r.note;
            if (typeof r.op === 'string') step.op = r.op;
            return step;
          }),
        },
      };
    }
    case 'mindmap': {
      if (typeof raw.center !== 'string') return { ok: false, error: 'mindmap item needs center string' };
      if (!Array.isArray(raw.ideas) || !raw.ideas.every((i) => typeof i === 'string')) {
        return { ok: false, error: 'mindmap item needs ideas string array' };
      }
      return { ok: true, item: { id, kind: 'mindmap', title, center: raw.center, ideas: raw.ideas } };
    }
    case 'svg': {
      if (typeof raw.svg !== 'string') return { ok: false, error: 'svg item needs svg string' };
      return { ok: true, item: { id, kind: 'svg', title, svg: raw.svg } };
    }
    case 'html': {
      if (typeof raw.html !== 'string') return { ok: false, error: 'html item needs html string' };
      if (raw.height !== undefined && typeof raw.height !== 'number') {
        return { ok: false, error: 'html height must be a number' };
      }
      return {
        ok: true,
        item: {
          id,
          kind: 'html',
          title,
          html: raw.html,
          ...(typeof raw.height === 'number' ? { height: raw.height } : {}),
        },
      };
    }
    case 'image': {
      if (typeof raw.url !== 'string' || typeof raw.alt !== 'string') {
        return { ok: false, error: 'image item needs url and alt strings' };
      }
      return { ok: true, item: { id, kind: 'image', title, url: raw.url, alt: raw.alt } };
    }
    case 'pending': {
      if (typeof raw.title !== 'string') return { ok: false, error: 'pending item needs title string' };
      return { ok: true, item: { id, kind: 'pending', title: raw.title } };
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
    case 'diagram':
      return validateDiagram(raw, id, title);
    default:
      return { ok: false, error: `Unknown board kind: ${String(raw.kind)}` };
  }
}

export type FocusOk = { ok: true; focus: BoardFocusPayload };
export type FocusErr = { ok: false; error: string };

/** Parse + validate a board.focus payload: { id, step? }. */
export function validateBoardFocus(raw: unknown): FocusOk | FocusErr {
  if (!isRecord(raw)) return { ok: false, error: 'focus payload must be an object' };
  if (!isNonEmptyString(raw.id)) return { ok: false, error: 'focus payload needs id string' };
  if (raw.step !== undefined && (typeof raw.step !== 'number' || !Number.isInteger(raw.step) || raw.step < 0)) {
    return { ok: false, error: 'focus step must be a non-negative integer' };
  }
  return {
    ok: true,
    focus: { id: raw.id, ...(typeof raw.step === 'number' ? { step: raw.step } : {}) },
  };
}

/** Loose check for incoming note payloads (topic 'note'). */
export function isNoteLike(raw: unknown): raw is { topic: string } & Record<string, unknown> {
  return isRecord(raw) && typeof raw.topic === 'string';
}
