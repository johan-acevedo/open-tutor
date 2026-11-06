// Diagram model → scene description and text alternative.
//
// Pure functions, no Excalidraw import: the worker sends node centres, this file sizes the boxes
// from the measured text, cuts every arrow at the box edges and places labels. The whole scene is
// rebuilt from the model on every revision, so a changed label, a removed node or a new link can
// never leave a stale arrow or label behind.

import type { DiagramItem, DiagramRole } from './protocol';

export const FONT_FAMILY_ID = 6; // Excalidraw's Nunito (self-hosted in public/excalidraw/fonts)
export const FONT_STACK = 'Nunito, "Segoe UI Emoji", sans-serif';
export const NODE_FONT_PX = 20;
export const LINK_FONT_PX = 16;
const LINE_HEIGHT = 1.25;
const MAX_TEXT_WIDTH = 210;
const PAD_X = 18;
const PAD_Y = 14;
const ARROW_GAP = 6;

export const PALETTE = {
  canvas: '#181B22',
  nodeFill: '#2A3040',
  focusFill: '#0E3A45',
  text: '#F3F5F8',
  connector: '#A78BFA',
  cyan: '#22D3EE',
} as const;

export const ROLE_STROKE: Record<DiagramRole, string> = {
  center: '#22D3EE',
  idea: '#A78BFA',
  step: '#C4CAD6',
  result: '#34D399',
  note: '#F59E0B',
};

export const ROLE_NAME: Record<DiagramRole, string> = {
  center: 'huvudämne',
  idea: 'idé',
  step: 'steg',
  result: 'resultat',
  note: 'anteckning',
};

export type Measure = (text: string, fontPx: number) => number;
export type FocusState = 'normal' | 'focus' | 'dim';

export type SceneNode = {
  id: string;
  role: DiagramRole;
  /** Top-left corner and size of the box. */
  x: number;
  y: number;
  w: number;
  h: number;
  lines: string[];
  state: FocusState;
};

export type SceneArrow = {
  id: string;
  source: string;
  target: string;
  /** Start point; `points` are relative to it. */
  x: number;
  y: number;
  points: [number, number][];
  label?: string;
  headed: boolean;
  state: FocusState;
};

export type Scene = { nodes: SceneNode[]; arrows: SceneArrow[] };

/** Break a label into lines no wider than maxWidth. A single over-long word is split by characters. */
export function wrapLabel(text: string, maxWidth: number, fontPx: number, measure: Measure): string[] {
  const lines: string[] = [];
  let line = '';
  const push = () => {
    if (line) lines.push(line);
    line = '';
  };
  for (const word of text.trim().split(/\s+/)) {
    let rest = word;
    while (measure(rest, fontPx) > maxWidth && rest.length > 1) {
      push();
      let cut = rest.length - 1;
      while (cut > 1 && measure(rest.slice(0, cut), fontPx) > maxWidth) cut -= 1;
      lines.push(rest.slice(0, cut));
      rest = rest.slice(cut);
    }
    const candidate = line ? `${line} ${rest}` : rest;
    if (line && measure(candidate, fontPx) > maxWidth) {
      push();
      line = rest;
    } else {
      line = candidate;
    }
  }
  push();
  return lines.length ? lines : [''];
}

/** Where the line from `from` to `to` (box centres) leaves the box around `from`. */
function edgePoint(c: { x: number; y: number; hw: number; hh: number }, dx: number, dy: number): [number, number] {
  const tx = dx === 0 ? Infinity : (c.hw + ARROW_GAP) / Math.abs(dx);
  const ty = dy === 0 ? Infinity : (c.hh + ARROW_GAP) / Math.abs(dy);
  const t = Math.min(tx, ty);
  return [c.x + dx * t, c.y + dy * t];
}

export function buildScene(item: DiagramItem, measure: Measure): Scene {
  const focus = new Set(item.focus);
  const anyFocus = focus.size > 0;
  const nodes: SceneNode[] = item.nodes.map((n) => {
    const lines = wrapLabel(n.text, MAX_TEXT_WIDTH, NODE_FONT_PX, measure);
    const textWidth = Math.max(...lines.map((l) => measure(l, NODE_FONT_PX)));
    const w = Math.max(120, Math.ceil(textWidth) + PAD_X * 2);
    const h = Math.max(56, Math.ceil(lines.length * NODE_FONT_PX * LINE_HEIGHT) + PAD_Y * 2);
    const state: FocusState = !anyFocus ? 'normal' : focus.has(n.id) ? 'focus' : 'dim';
    return { id: n.id, role: n.role, x: Math.round(n.x - w / 2), y: Math.round(n.y - h / 2), w, h, lines, state };
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const arrows: SceneArrow[] = [];
  for (const l of item.links) {
    const a = byId.get(l.source);
    const b = byId.get(l.target);
    if (!a || !b) continue;
    const ca = { x: a.x + a.w / 2, y: a.y + a.h / 2, hw: a.w / 2, hh: a.h / 2 };
    const cb = { x: b.x + b.w / 2, y: b.y + b.h / 2, hw: b.w / 2, hh: b.h / 2 };
    const dx = cb.x - ca.x;
    const dy = cb.y - ca.y;
    if (dx === 0 && dy === 0) continue;
    const [sx, sy] = edgePoint(ca, dx, dy);
    const [ex, ey] = edgePoint(cb, -dx, -dy);
    if ((ex - sx) * dx + (ey - sy) * dy <= 0) continue; // boxes touch or overlap: no room for an arrow
    const state: FocusState = !anyFocus
      ? 'normal'
      : focus.has(l.id) || (focus.has(l.source) && focus.has(l.target))
        ? 'focus'
        : 'dim';
    arrows.push({
      id: l.id,
      source: l.source,
      target: l.target,
      x: Math.round(sx),
      y: Math.round(sy),
      points: [
        [0, 0],
        [Math.round(ex - sx), Math.round(ey - sy)],
      ],
      ...(l.label ? { label: l.label } : {}),
      headed: item.layout === 'flow',
      state,
    });
  }
  return { nodes, arrows };
}

export function sceneBounds(scene: Scene): { x: number; y: number; w: number; h: number } {
  const xs = scene.nodes.flatMap((n) => [n.x, n.x + n.w]);
  const ys = scene.nodes.flatMap((n) => [n.y, n.y + n.h]);
  const x = Math.min(...xs);
  const y = Math.min(...ys);
  return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
}

// ---- Excalidraw skeletons -----------------------------------------------------------------------

export const nodeElementId = (id: string) => `n-${id}`;
export const linkElementId = (id: string) => `l-${id}`;

type Skeleton = Record<string, unknown>;

/** Excalidraw "element skeletons" with explicit geometry (the library does not lay anything out). */
export function toSkeletons(scene: Scene): Skeleton[] {
  const out: Skeleton[] = [];
  for (const n of scene.nodes) {
    const focused = n.state === 'focus';
    out.push({
      type: 'rectangle',
      id: nodeElementId(n.id),
      x: n.x,
      y: n.y,
      width: n.w,
      height: n.h,
      strokeColor: focused ? PALETTE.cyan : ROLE_STROKE[n.role],
      backgroundColor: focused ? PALETTE.focusFill : PALETTE.nodeFill,
      fillStyle: 'solid',
      strokeWidth: focused ? 4 : 2,
      roughness: 0,
      roundness: { type: 3 },
      opacity: n.state === 'dim' ? 45 : 100,
      label: {
        text: n.lines.join('\n'),
        fontSize: NODE_FONT_PX,
        fontFamily: FONT_FAMILY_ID,
        strokeColor: PALETTE.text,
        textAlign: 'center',
        verticalAlign: 'middle',
      },
    });
  }
  for (const a of scene.arrows) {
    const focused = a.state === 'focus';
    out.push({
      type: 'arrow',
      id: linkElementId(a.id),
      x: a.x,
      y: a.y,
      width: Math.abs(a.points[1][0]),
      height: Math.abs(a.points[1][1]),
      points: a.points,
      strokeColor: focused ? PALETTE.cyan : PALETTE.connector,
      strokeWidth: focused ? 4 : 2,
      roughness: 0,
      roundness: null,
      opacity: a.state === 'dim' ? 45 : 100,
      startArrowhead: null,
      endArrowhead: a.headed ? 'arrow' : null,
      ...(a.label
        ? {
            label: {
              text: a.label,
              fontSize: LINK_FONT_PX,
              fontFamily: FONT_FAMILY_ID,
              strokeColor: PALETTE.text,
            },
          }
        : {}),
    });
  }
  return out;
}

// ---- Text alternative ---------------------------------------------------------------------------

export type DiagramText = { summary: string; lines: string[] };

/** A readable version of the diagram for people who cannot use the canvas, in Swedish. */
export function diagramText(item: DiagramItem): DiagramText {
  const name = new Map(item.nodes.map((n) => [n.id, n.text]));
  const noun = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  const summary =
    `${item.layout === 'flow' ? 'Flödesschema' : 'Tankekarta'}${item.title ? ` om ${item.title}` : ''}: ` +
    `${noun(item.nodes.length, 'ruta', 'rutor')} och ${noun(item.links.length, 'pil', 'pilar')}.`;
  const lines: string[] = [];
  const linked = new Set<string>();
  for (const l of item.links) {
    linked.add(l.source);
    linked.add(l.target);
    const via = l.label ? ` (${l.label})` : '';
    lines.push(`${name.get(l.source)} → ${name.get(l.target)}${via}`);
  }
  for (const n of item.nodes) {
    if (!linked.has(n.id)) lines.push(`${n.text} (inte kopplad)`);
  }
  if (item.focus.length > 0) {
    const labels = item.focus.map((f) => name.get(f) ?? item.links.find((l) => l.id === f)?.label ?? f);
    lines.push(`Markerat just nu: ${labels.join(', ')}`);
  }
  return { summary, lines };
}
