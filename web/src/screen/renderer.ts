/**
 * Canvas renderer for Screen pages — the first-slice visible board.
 *
 * One page at a time on a responsive canvas with stable chrome. Text,
 * simple equations (as plain text lines), image artifacts and generated
 * SVG assets are composed into the canvas; the designated child answer is
 * drawn from `assets.draftText` so observations include exactly what the
 * learner sees. No arbitrary iframe HTML is ever used.
 *
 * `captureObservation` reads the same canvas this renderer draws into —
 * that is the actual-pixels guarantee.
 */
import type { ScreenBlobStore } from "./assets";
import type { ScreenPage } from "./types";

/** Pre-resolved drawables for one render pass. */
export interface ScreenRenderAssets {
  /** Drawable images keyed by asset id (Image, ImageBitmap, canvas, …). */
  images?: Map<string, CanvasImageSource>;
  /** Rasterised generated-SVG drawable, when the page carries `svgAsset`. */
  svgImage?: CanvasImageSource | null;
  /** Child draft text drawn into the answer area. */
  draftText?: string;
  /** e.g. "Sida 2 av 3". Unknown to the deck core, supplied by the lead. */
  pageLabel?: string;
}

export interface ScreenRenderSize {
  w: number;
  h: number;
}

const BG_TOP = "#0b1220";
const BG_BOTTOM = "#0f1b33";
const CARD = "#16223d";
const CARD_BORDER = "#2b3b5e";
const INK = "#f1f5f9";
const MUTED = "#9fb0cc";
const ACCENT = "#fbbf24";
const ACCENT_INK = "#1a1305";
const ANSWER_BG = "#0d1730";
const SOLUTION_BG = "#12281c";
const SOLUTION_BORDER = "#2f7a4d";
const HIDDEN_BG = "#1c2438";

const FONT = `"Atkinson Hyperlegible", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`;

/**
 * Render a page into a real canvas. Call after `resolveScreenAssets` when
 * the page references blob image assets.
 */
export function renderScreenPage(
  canvas: HTMLCanvasElement,
  page: ScreenPage,
  assets: ScreenRenderAssets = {},
): void {
  const dpr = typeof window !== "undefined" && window.devicePixelRatio ? window.devicePixelRatio : 1;
  const cssW = canvas.clientWidth > 0 ? canvas.clientWidth : canvas.width || 1280;
  const cssH = canvas.clientHeight > 0 ? canvas.clientHeight : canvas.height || 800;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no-2d-context");
  ctx.save();
  ctx.scale(dpr, dpr);
  drawScreenPage(ctx, { w: cssW, h: cssH }, page, assets);
  ctx.restore();
}

/** Testable core: draws into any 2d context at the given CSS size. */
export function drawScreenPage(
  ctx: CanvasRenderingContext2D,
  size: ScreenRenderSize,
  page: ScreenPage,
  assets: ScreenRenderAssets = {},
): void {
  const { w, h } = size;
  // Background.
  const bg = ctx.createLinearGradient(0, 0, 0, h);
  bg.addColorStop(0, BG_TOP);
  bg.addColorStop(1, BG_BOTTOM);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);
  // Top accent bar.
  ctx.fillStyle = ACCENT;
  ctx.fillRect(0, 0, w, 6);

  const margin = Math.max(20, Math.min(56, w * 0.045));
  const cardX = margin;
  const cardY = 26;
  const cardW = w - margin * 2;
  const cardH = h - cardY - 20;
  roundRect(ctx, cardX, cardY, cardW, cardH, 18);
  ctx.fillStyle = CARD;
  ctx.fill();
  ctx.strokeStyle = CARD_BORDER;
  ctx.lineWidth = 1.5;
  ctx.stroke();

  let y = cardY + 30;
  const innerX = cardX + 28;
  const innerW = cardW - 56;

  // Subject chip + page label.
  const chip = page.subject || (page.kind === "geography" ? "Geografi" : "Matte");
  ctx.font = `700 15px ${FONT}`;
  const chipW = ctx.measureText(chip).width + 28;
  roundRect(ctx, innerX, y - 20, chipW, 30, 15);
  ctx.fillStyle = ACCENT;
  ctx.fill();
  ctx.fillStyle = ACCENT_INK;
  ctx.textBaseline = "middle";
  ctx.fillText(chip, innerX + 14, y - 4);
  if (assets.pageLabel) {
    ctx.fillStyle = MUTED;
    ctx.font = `500 15px ${FONT}`;
    ctx.textAlign = "right";
    ctx.fillText(assets.pageLabel, cardX + cardW - 28, y - 4);
    ctx.textAlign = "left";
  }
  y += 22;

  // Title.
  ctx.fillStyle = INK;
  ctx.font = `700 ${clamp(w * 0.032, 24, 40)}px ${FONT}`;
  ctx.textBaseline = "alphabetic";
  for (const line of wrapText(ctx, page.title, innerW)) {
    y += lineHeight(ctx);
    if (y > cardY + cardH - 170) break;
    ctx.fillText(line, innerX, y);
  }
  y += 14;

  // Body / question lines.
  ctx.font = `400 ${clamp(w * 0.02, 17, 24)}px ${FONT}`;
  ctx.fillStyle = "#dce6f7";
  for (const paragraph of page.body.slice(0, 6)) {
    for (const line of wrapText(ctx, paragraph, innerW)) {
      y += lineHeight(ctx) * 0.96;
      if (y > cardY + cardH - 230) break;
      ctx.fillText(line, innerX, y);
    }
    y += 8;
  }

  const boxW = innerW;
  const boxX = innerX;
  const footerH = 44;
  const answerH = 96;
  const solutionH = page.revealed ? 110 : 56;
  const hasVisual = page.asset?.id || page.svgAsset;
  const visualH = hasVisual ? clamp(h * 0.22, 110, 200) : 0;

  // Visual asset box (image or generated-SVG placeholder).
  if (hasVisual) {
    const boxY = cardY + cardH - footerH - answerH - solutionH - visualH - 44;
    if (boxY > y + 6) {
      y = boxY;
      const image = page.asset?.id ? assets.images?.get(page.asset.id) : undefined;
      const svgDrawable = !image && page.svgAsset ? assets.svgImage : undefined;
      roundRect(ctx, boxX, y, boxW, visualH, 12);
      ctx.fillStyle = "#0a1122";
      ctx.fill();
      ctx.strokeStyle = CARD_BORDER;
      ctx.lineWidth = 1;
      ctx.stroke();
      if (image) {
        ctx.save();
        roundRect(ctx, boxX, y, boxW, visualH, 12);
        ctx.clip();
        drawContain(ctx, image, boxX, y, boxW, visualH);
        ctx.restore();
      } else if (svgDrawable) {
        ctx.save();
        roundRect(ctx, boxX, y, boxW, visualH, 12);
        ctx.clip();
        drawContain(ctx, svgDrawable, boxX, y, boxW, visualH);
        ctx.restore();
      } else {
        drawMapPlaceholder(ctx, boxX, y, boxW, visualH, page);
      }
      const attribution = page.asset?.attribution ?? (page.svgAsset ? "Genererad bild" : null);
      if (attribution) {
        ctx.fillStyle = MUTED;
        ctx.font = `400 12px ${FONT}`;
        ctx.fillText(truncate(ctx, `Bild: ${attribution}`, boxW - 16), boxX + 8, y + visualH - 10);
      }
      y += visualH + 14;
    }
  }

  // Answer area (child-owned; drawn so pixels match what the child sees).
  const answerY = cardY + cardH - footerH - answerH - solutionH - 16;
  const answerBoxY = Math.max(y + 6, answerY);
  roundRect(ctx, boxX, answerBoxY, boxW, answerH, 12);
  ctx.fillStyle = ANSWER_BG;
  ctx.fill();
  ctx.strokeStyle = CARD_BORDER;
  ctx.stroke();
  ctx.fillStyle = MUTED;
  ctx.font = `600 14px ${FONT}`;
  ctx.fillText(page.answerLabel || "Ditt svar", boxX + 14, answerBoxY + 22);
  const draft = (assets.draftText ?? "").trim();
  ctx.font = `400 ${clamp(w * 0.019, 16, 22)}px ${FONT}`;
  if (draft) {
    ctx.fillStyle = INK;
    const lines = wrapText(ctx, draft, boxW - 28).slice(0, 2);
    lines.forEach((line, i) => ctx.fillText(line, boxX + 14, answerBoxY + 50 + i * lineHeight(ctx) * 0.95));
  } else {
    ctx.fillStyle = "#5c6c8d";
    ctx.fillText("Skriv ditt svar här …", boxX + 14, answerBoxY + 54);
  }

  // Solution area: hidden until the fox-gated reveal.
  const solutionY = answerBoxY + answerH + 12;
  roundRect(ctx, boxX, solutionY, boxW, solutionH, 12);
  if (page.revealed) {
    ctx.fillStyle = SOLUTION_BG;
    ctx.fill();
    ctx.strokeStyle = SOLUTION_BORDER;
    ctx.stroke();
    ctx.fillStyle = "#7ee2a8";
    ctx.font = `600 14px ${FONT}`;
    ctx.fillText("Facit", boxX + 14, solutionY + 22);
    ctx.fillStyle = "#e8f7ee";
    ctx.font = `400 ${clamp(w * 0.019, 16, 22)}px ${FONT}`;
    const lines = wrapText(ctx, page.solution, boxW - 28).slice(0, 3);
    lines.forEach((line, i) => ctx.fillText(line, boxX + 14, solutionY + 50 + i * lineHeight(ctx) * 0.95));
  } else {
    ctx.fillStyle = HIDDEN_BG;
    ctx.fill();
    ctx.strokeStyle = CARD_BORDER;
    ctx.stroke();
    ctx.fillStyle = MUTED;
    ctx.font = `600 16px ${FONT}`;
    ctx.fillText("🔒 Facit är dolt", boxX + 14, solutionY + solutionH / 2 + 6);
  }

  // Footer: sources + stable page/revision metadata.
  ctx.fillStyle = MUTED;
  ctx.font = `400 12.5px ${FONT}`;
  const sources = page.sources.slice(0, 2).join(" · ");
  if (sources) ctx.fillText(truncate(ctx, `Källor: ${sources}`, boxW * 0.62), boxX, cardY + cardH - 14);
  const meta = `${page.id} ${page.revision}`;
  ctx.textAlign = "right";
  ctx.fillText(meta, boxX + boxW, cardY + cardH - 14);
  ctx.textAlign = "left";
}

function lineHeight(ctx: CanvasRenderingContext2D): number {
  const match = /(\d+(?:\.\d+)?)px/.exec(ctx.font);
  return (match ? Number(match[1]) : 20) * 1.32;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/** Greedy word wrap for canvas fillText. Exported for tests. */
export function wrapText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  if (words.length === 0) return [""];
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    const trial = line ? `${line} ${word}` : word;
    if (ctx.measureText(trial).width <= maxWidth || !line) {
      line = trial;
    } else {
      lines.push(line);
      line = word;
    }
  }
  if (line) lines.push(line);
  return lines;
}

function truncate(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let out = text;
  while (out.length > 4 && ctx.measureText(`${out}…`).width > maxWidth) {
    out = out.slice(0, -1);
  }
  return `${out}…`;
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
): void {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

/**
 * Contain-fit draw: the whole map/image stays visible (letterboxed),
 * never cropped. Map images prefer this over cover-fit.
 */
export function drawContain(
  ctx: CanvasRenderingContext2D,
  image: CanvasImageSource,
  x: number,
  y: number,
  w: number,
  h: number,
): void {
  const iw = (image as { width?: number }).width ?? 0;
  const ih = (image as { height?: number }).height ?? 0;
  // SVG drawables without intrinsic size still paint via drawImage stretch.
  if (!iw || !ih) {
    try {
      ctx.drawImage(image, x, y, w, h);
    } catch {
      // ignore undecodable drawables; placeholder path handles the rest
    }
    return;
  }
  const scale = Math.min(w / iw, h / ih);
  const dw = iw * scale;
  const dh = ih * scale;
  ctx.drawImage(image, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
}

/** Legacy cover-fit kept for callers that explicitly want cropping. */
export function drawCover(
  ctx: CanvasRenderingContext2D,
  image: CanvasImageSource,
  x: number,
  y: number,
  w: number,
  h: number,
): void {
  const iw = (image as { width?: number }).width ?? 0;
  const ih = (image as { height?: number }).height ?? 0;
  if (!iw || !ih) return;
  const scale = Math.max(w / iw, h / ih);
  const dw = iw * scale;
  const dh = ih * scale;
  ctx.drawImage(image, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
}

/** Deterministic placeholder when an SVG asset has no preloaded drawable. */
function drawMapPlaceholder(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  page: ScreenPage,
): void {
  ctx.save();
  roundRect(ctx, x, y, w, h, 12);
  ctx.clip();
  ctx.strokeStyle = "#24344f";
  ctx.lineWidth = 1;
  for (let gx = x; gx < x + w; gx += 28) {
    ctx.beginPath();
    ctx.moveTo(gx, y);
    ctx.lineTo(gx, y + h);
    ctx.stroke();
  }
  for (let gy = y; gy < y + h; gy += 28) {
    ctx.beginPath();
    ctx.moveTo(x, gy);
    ctx.lineTo(x + w, gy);
    ctx.stroke();
  }
  // Stylised coastline.
  ctx.strokeStyle = "#3f6d4e";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(x + w * 0.1, y + h * 0.75);
  ctx.bezierCurveTo(
    x + w * 0.3, y + h * 0.3,
    x + w * 0.55, y + h * 0.6,
    x + w * 0.9, y + h * 0.25,
  );
  ctx.stroke();
  ctx.fillStyle = ACCENT;
  ctx.beginPath();
  ctx.arc(x + w * 0.55, y + h * 0.45, 6, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = MUTED;
  ctx.font = `600 14px ${FONT}`;
  ctx.fillText(page.kind === "geography" ? "Karta laddas …" : "Bild laddas …", x + 14, y + 26);
  ctx.restore();
}

/**
 * Minimal SVG sanitizer for generated map/diagram assets. Generated SVG
 * travels with the page (never an iframe); this strips scripts, event
 * handler attributes, javascript: URLs, iframes and foreignObject so a
 * compromised model string cannot escape the canvas raster path.
 */
export function sanitizeSvg(svg: string): string {
  let out = svg;
  out = out.replace(/<script[\s\S]*?<\/script\s*>/gi, "");
  out = out.replace(/<iframe[\s\S]*?(<\/iframe\s*>|\/>)/gi, "");
  out = out.replace(/<foreignObject[\s\S]*?<\/foreignObject\s*>/gi, "");
  out = out.replace(/\s+on[a-zA-Z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/g, "");
  out = out.replace(/(href|xlink:href)\s*=\s*("|')\s*javascript:[^"']*\2/gi, '$1=$2#$2');
  return out.slice(0, 200_000);
}

/**
 * Resolve blob image assets and generated SVG into drawables. Call before
 * `renderScreenPage`. Researched raster bytes come from the blob store;
 * generated sanitized SVG is rasterised via `createImageBitmap` with an
 * `Image`/object-URL fallback so a real canvas never keeps a permanent
 * "Karta laddas" placeholder when SVG exists.
 */
export async function resolveScreenAssets(
  page: ScreenPage,
  blobStore: ScreenBlobStore,
  draftText = "",
  pageLabel = "",
): Promise<ScreenRenderAssets> {
  const images = new Map<string, CanvasImageSource>();
  const ref = page.asset;
  if (ref?.id && ref.status === "ready" && ref.mimeType !== "image/svg+xml") {
    const record = await blobStore.get(ref.id);
    if (record) {
      const drawable = await decodeDrawable(record.bytes, record.meta.mimeType);
      if (drawable) images.set(ref.id, drawable);
    }
  }
  let svgImage: CanvasImageSource | null = null;
  if (page.svgAsset && page.svgAsset.trim()) {
    svgImage = await decodeSvgDrawable(page.svgAsset);
  }
  return { images, svgImage, draftText, pageLabel };
}

export async function decodeSvgDrawable(svg: string): Promise<CanvasImageSource | null> {
  const text = svg.trim();
  if (!text) return null;
  try {
    if (typeof createImageBitmap !== "undefined") {
      const blob = new Blob([text], { type: "image/svg+xml" });
      const bmp = await createImageBitmap(blob);
      if (bmp) return bmp;
    }
  } catch {
    // fall through to the Image/object-URL path
  }
  try {
    const g = globalThis as unknown as {
      Image?: new () => HTMLImageElement;
      URL?: { createObjectURL(b: Blob): string; revokeObjectURL(u: string): void };
    };
    if (g.Image && g.URL?.createObjectURL) {
      const blob = new Blob([text], { type: "image/svg+xml" });
      const url = g.URL.createObjectURL(blob);
      try {
        return await loadImageElement(url, g.Image);
      } finally {
        try {
          g.URL.revokeObjectURL(url);
        } catch {
          // ignore revocation failures
        }
      }
    }
  } catch {
    return null;
  }
  return null;
}

function loadImageElement(
  url: string,
  ImageCtor: new () => HTMLImageElement,
): Promise<CanvasImageSource> {
  return new Promise((resolve, reject) => {
    const img = new ImageCtor();
    img.onload = () => resolve(img as unknown as CanvasImageSource);
    img.onerror = () => reject(new Error("svg-load-failed"));
    img.src = url;
  });
}

async function decodeDrawable(bytes: Uint8Array, mimeType: string): Promise<CanvasImageSource | null> {
  try {
    if (typeof createImageBitmap !== "undefined") {
      const blob = new Blob([bytes as unknown as BlobPart], { type: mimeType });
      return await createImageBitmap(blob);
    }
  } catch {
    return null;
  }
  return null;
}
