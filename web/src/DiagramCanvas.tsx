// The Excalidraw canvas of a diagram card. Loaded lazily through diagramLoader.ts.
//
// View-only: the tutor draws, the child looks. The scene is rebuilt from the model on every
// revision (diagramModel.ts), applied one revision at a time, and acknowledged only after the
// library has drawn it.

import './excalidrawAssets';
import { useCallback, useEffect, useRef, useState } from 'react';
import { CaptureUpdateAction, Excalidraw, convertToExcalidrawElements } from '@excalidraw/excalidraw';
import '@excalidraw/excalidraw/index.css';
import type { ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types';
import type { DiagramCanvasProps } from './diagramLoader';
import type { DiagramItem } from './protocol';
import { ensureDiagramFonts } from './diagramFonts';
import {
  FONT_STACK,
  PALETTE,
  buildScene,
  linkElementId,
  nodeElementId,
  toSkeletons,
} from './diagramModel';
import type { Measure } from './diagramModel';

const FRAME_WAIT_MS = 1500;

let measureContext: CanvasRenderingContext2D | null = null;
/** Text width in the diagram font. Only called after the font has loaded. */
export const measureText: Measure = (text, px) => {
  measureContext ??= document.createElement('canvas').getContext('2d');
  if (!measureContext) throw new Error('canvas is not available');
  measureContext.font = `${px}px ${FONT_STACK}`;
  return measureContext.measureText(text).width;
};

/** Load the Nunito files this diagram's text needs from our own server; fail visibly if they cannot load. */
export function loadDiagramFonts(item: DiagramItem): Promise<void> {
  return ensureDiagramFonts(item.nodes.map((n) => n.text).concat(item.links.map((l) => l.label ?? '')).join(''));
}

const nextFrames = (n: number) =>
  new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error('Diagrammet ritades inte i tid.')), FRAME_WAIT_MS);
    const step = (left: number) => {
      if (left === 0) {
        window.clearTimeout(timer);
        resolve();
      } else requestAnimationFrame(() => step(left - 1));
    };
    step(n);
  });

const reducedMotion = () =>
  typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Node ids to bring into view for a focus: the highlighted nodes and the nodes next to them, for context. */
export function focusContext(item: DiagramItem): Set<string> {
  const focus = new Set(item.focus);
  const nodes = new Set(item.nodes.filter((n) => focus.has(n.id)).map((n) => n.id));
  for (const l of item.links) {
    if (focus.has(l.id)) {
      nodes.add(l.source);
      nodes.add(l.target);
    }
  }
  const withNeighbours = new Set(nodes);
  for (const l of item.links) {
    if (nodes.has(l.source)) withNeighbours.add(l.target);
    if (nodes.has(l.target)) withNeighbours.add(l.source);
  }
  return withNeighbours;
}

/** Zoom to the highlighted nodes and their neighbours, or to the whole diagram when nothing is highlighted. */
export function fitCamera(api: ExcalidrawImperativeAPI, item: DiagramItem, animate: boolean): void {
  const elements = api.getSceneElements();
  const near = new Set([...focusContext(item)].map(nodeElementId));
  const focused = elements.filter((e) => near.has(e.id));
  const boxes = elements.filter((e) => e.type === 'rectangle');
  const targets = focused.length ? focused : boxes.length ? boxes : elements;
  if (targets.length === 0) return;
  api.scrollToContent(targets, {
    fitToViewport: true,
    viewportZoomFactor: 0.88,
    maxZoom: 1.1,
    animate: animate && !reducedMotion(),
    duration: 320,
  });
}

/** Draw `item` and return only once the library shows exactly that scene. */
export async function applyDiagram(api: ExcalidrawImperativeAPI, item: DiagramItem, animate: boolean): Promise<void> {
  await loadDiagramFonts(item);
  const scene = buildScene(item, measureText);
  const elements = convertToExcalidrawElements(toSkeletons(scene) as never, { regenerateIds: false });
  api.updateScene({
    elements,
    appState: { viewBackgroundColor: PALETTE.canvas },
    captureUpdate: CaptureUpdateAction.NEVER,
  });
  fitCamera(api, item, animate);
  await nextFrames(2);

  // Acknowledge only what is really in the scene: every node and arrow, with its label, and
  // nothing left over from an earlier revision.
  const shown = api.getSceneElements();
  const expected = new Set([...scene.nodes.map((n) => nodeElementId(n.id)), ...scene.arrows.map((a) => linkElementId(a.id))]);
  const present = new Set(shown.filter((e) => e.type !== 'text').map((e) => e.id));
  const labels = shown.filter((e) => e.type === 'text').length;
  const wantLabels = scene.nodes.length + scene.arrows.filter((a) => a.label).length;
  if (present.size !== expected.size || [...expected].some((id) => !present.has(id)) || labels !== wantLabels) {
    throw new Error('Diagrammet visades inte som väntat.');
  }
}

export default function DiagramCanvas({ item, onRendered, interactive }: DiagramCanvasProps) {
  const [api, setApi] = useState<ExcalidrawImperativeAPI | null>(null);
  const box = useRef<HTMLDivElement | null>(null);
  const latest = useRef(item);
  const applied = useRef(0);
  const running = useRef(false);
  const alive = useRef(true);
  const report = useRef(onRendered);
  report.current = onRendered;
  latest.current = item;

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // Apply the newest revision; revisions that arrive meanwhile are folded into the next pass.
  const pump = useCallback(async () => {
    if (running.current || !api) return;
    running.current = true;
    try {
      while (alive.current && applied.current !== latest.current.rev) {
        const target = latest.current;
        try {
          await applyDiagram(api, target, applied.current > 0);
        } catch (error) {
          // Not marked as drawn: the next revision, or a resend of this one, tries again.
          if (alive.current) {
            report.current(target.rev, error instanceof Error ? error.message : 'Diagrammet kunde inte ritas.');
          }
          break;
        }
        applied.current = target.rev;
        if (alive.current) {
          // What the scene shows now; browser tests read it, and so can anyone debugging.
          box.current?.setAttribute('data-scene-rev', String(target.rev));
          report.current(target.rev);
        }
      }
    } finally {
      running.current = false;
    }
  }, [api]);

  useEffect(() => {
    // The same revision again (a resend): it is already drawn, so say so.
    if (!running.current && applied.current === item.rev && applied.current > 0) report.current(item.rev);
    void pump();
  }, [item, pump]);

  useEffect(() => {
    if (box.current && api) (box.current as HTMLDivElement & { excalidrawApi?: unknown }).excalidrawApi = api;
  }, [api]);

  // The board changes width when the first card arrives and when the window changes: refit.
  useEffect(() => {
    const el = box.current;
    if (!api || !el || typeof ResizeObserver === 'undefined') return;
    let timer = 0;
    const observer = new ResizeObserver(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        if (alive.current && applied.current > 0 && !running.current) fitCamera(api, latest.current, false);
      }, 120);
    });
    observer.observe(el);
    return () => {
      observer.disconnect();
      window.clearTimeout(timer);
    };
  }, [api]);

  return (
    <div className="ot-diagram-canvas" ref={box} data-interactive={interactive ? 'true' : 'false'}>
      <Excalidraw
        excalidrawAPI={(a) => setApi(a)}
        viewModeEnabled
        zenModeEnabled
        theme="light"
        aiEnabled={false}
        detectScroll={false}
        handleKeyboardGlobally={false}
        autoFocus={false}
        UIOptions={{ canvasActions: { loadScene: false, export: false, saveAsImage: false, saveToActiveFile: false } }}
        initialData={{ appState: { viewBackgroundColor: PALETTE.canvas } }}
      />
    </div>
  );
}
