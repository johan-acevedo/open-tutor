// PDF homework intake via pdfjs-dist.
// Each page renders to a canvas ~1600px wide, max 10 pages per file.

import * as pdfjsLib from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

let workerConfigured = false;

function ensureWorker(): void {
  if (!workerConfigured) {
    pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;
    workerConfigured = true;
  }
}

export type RenderedPage = {
  dataUrl: string;
  width: number;
  height: number;
};

/** Render up to maxPages pages of a PDF to JPEG data URLs (~targetWidth px wide). */
export async function renderPdfPages(
  file: File | Blob,
  maxPages = 10,
  targetWidth = 1600,
): Promise<RenderedPage[]> {
  ensureWorker();
  const buffer = await file.arrayBuffer();
  const loadingTask = pdfjsLib.getDocument({ data: buffer });
  const doc = await loadingTask.promise;
  const count = Math.min(doc.numPages, maxPages);
  const pages: RenderedPage[] = [];
  for (let n = 1; n <= count; n++) {
    const page = await doc.getPage(n);
    const viewport0 = page.getViewport({ scale: 1 });
    const scale = targetWidth / viewport0.width;
    const viewport = page.getViewport({ scale });
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(viewport.width);
    canvas.height = Math.round(viewport.height);
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('no 2d canvas context');
    await page.render({ canvas, viewport }).promise;
    pages.push({
      dataUrl: canvas.toDataURL('image/jpeg', 0.85),
      width: canvas.width,
      height: canvas.height,
    });
    page.cleanup();
  }
  await loadingTask.destroy();
  return pages;
}
