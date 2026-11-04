// Loads the drawing library on first use. Sessions without a diagram never fetch it.

import type { ComponentType } from 'react';
import type { DiagramItem } from './protocol';

export type DiagramCanvasProps = {
  item: DiagramItem;
  /** The scene now shows `rev` (no error) or could not be drawn (error, in Swedish). */
  onRendered: (rev: number, error?: string) => void;
  /** Allow the child to pan and zoom this diagram. Off, the page scrolls through it. */
  interactive: boolean;
};

export type DiagramCanvasModule = { default: ComponentType<DiagramCanvasProps> };

let importer: () => Promise<DiagramCanvasModule> = () => import('./DiagramCanvas');
let cached: Promise<DiagramCanvasModule> | null = null;

/** A failed load is not cached, so "Försök igen" really tries again. */
export function loadDiagramCanvas(): Promise<DiagramCanvasModule> {
  cached ??= importer().catch((error) => {
    cached = null;
    throw error;
  });
  return cached;
}

/** For tests. */
export function setDiagramImporter(fn: (() => Promise<DiagramCanvasModule>) | null): void {
  importer = fn ?? (() => import('./DiagramCanvas'));
  cached = null;
}
