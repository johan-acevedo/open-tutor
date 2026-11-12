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

/**
 * Result of one render pass. `visibleText` contains ONLY text actually
 * passed to canvas drawing (fillText) — hidden solutions, clipped
 * paragraphs and undrawn candidate text are never included. Embedded map
 * image text stays pixels-only and is never transcribed here.
 */
export interface ScreenRenderResult {
  visibleText: string;
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
): ScreenRenderResult {
  const dpr = typeof window !== "undefined" && window.devicePixelRatio ? window.devicePixelRatio : 1;
  const cssW = canvas.clientWidth > 0 ? canvas.clientWidth : canvas.width || 1280;
  const cssH = canvas.clientHeight > 0 ? canvas.clientHeight : canvas.height || 800;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("no-2d-context");
  ctx.save();
  ctx.scale(dpr, dpr);
  const result = drawScreenPage(ctx, { w: cssW, h: cssH }, page, assets);
  ctx.restore();
  return result;
}

/** Testable core: draws into any 2d context at the given CSS size. */
export function drawScreenPage(
  ctx: CanvasRenderingContext2D,
  size: ScreenRenderSize,
  page: ScreenPage,
  assets: ScreenRenderAssets = {},
): ScreenRenderResult {
  const { w, h } = size;
  const compact = w < 600 || h < 480;
  // Every string actually passed to canvas drawing. The returned
  // visibleText is built ONLY from this list: hidden solutions, clipped
  // paragraphs and undrawn candidate text never enter it.
  const drawn: string[] = [];
  const put = (text: string, x: number, yPos: number): void => {
    drawn.push(text);
    ctx.fillText(text, x, yPos);
  };
  const finish = (): ScreenRenderResult => ({ visibleText: drawn.join("\n").slice(0, 4000) });
  // Background.
  const bg = ctx.createLinearGradient(0, 0, 0, h);
  bg.addColorStop(0, BG_TOP);
  bg.addColorStop(1, BG_BOTTOM);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);
  // Top accent bar.
  ctx.fillStyle = ACCENT;
  ctx.fillRect(0, 0, w, 6);

  const margin = compact ? 12 : Math.max(20, Math.min(56, w * 0.045));
  const cardX = margin;
  const cardY = compact ? 12 : 26;
  const cardW = w - margin * 2;
  const cardH = h - cardY - (compact ? 12 : 20);
  roundRect(ctx, cardX, cardY, cardW, cardH, 18);
  ctx.fillStyle = CARD;
  ctx.fill();
  ctx.strokeStyle = CARD_BORDER;
  ctx.lineWidth = 1.5;
  ctx.stroke();

  let y = cardY + (compact ? 20 : 30);
  const padding = compact ? 16 : 28;
  const innerX = cardX + padding;
  const innerW = cardW - padding * 2;
  const footerH = compact ? 20 : 44;
  const answerH = compact ? 44 : 96;
  ctx.font = `400 ${clamp(w * 0.019, 16, 22)}px ${FONT}`;
  const solutionLines = wrapText(ctx, page.solution, innerW - 28).slice(0, compact && h < 320 ? 1 : 3);
  const compactSolutionH = 44 + Math.max(0, solutionLines.length - 1) * lineHeight(ctx) * 0.95;
  const solutionH = compact ? (page.revealed ? compactSolutionH : 32) : (page.revealed ? 110 : 56);
  const gap = compact ? 6 : 12;
  const hasVisual = page.asset?.id || page.svgAsset;
  const visualH = hasVisual ? (compact ? Math.min(110, h * 0.2) : clamp(h * 0.22, 110, 200)) : 0;
  const answerY = cardY + cardH - footerH - answerH - solutionH - gap;
  const visualY = answerY - gap - visualH;
  const bodyBottom = (hasVisual ? visualY : answerY) - gap;
  // Geography uses a compact one-page workspace so the researched map stays
  // prominent: two columns on desktop, stacked with a large map on phones,
  // and slim answer/solution strips instead of the exercise-sized boxes.
  const geoTwoCol = page.kind === "geography" && !compact && w >= 700;
  const geoAnswerH = compact ? 44 : 72;
  ctx.font = `400 ${clamp(w * 0.019, 16, 22)}px ${FONT}`;
  const geoSolFull = wrapText(ctx, page.solution, innerW - 28);
  const geoSolMax = compact ? (h < 320 ? 1 : 3) : 2;
  const geoSolLines = geoSolFull.slice(0, geoSolMax);
  if (geoSolFull.length > geoSolMax && geoSolLines.length > 0) {
    geoSolLines[geoSolLines.length - 1] = truncate(ctx, `${geoSolLines[geoSolLines.length - 1]} \u2026`, innerW - 28);
  }
  const geoCompactSolH = 44 + Math.max(0, geoSolLines.length - 1) * lineHeight(ctx) * 0.95;
  const geoSolutionH = compact ? (page.revealed ? geoCompactSolH : 32) : page.revealed ? 78 : 34;
  const geoAnswerY = cardY + cardH - footerH - geoAnswerH - geoSolutionH - gap;

  // Subject chip + page label.
  const chip = page.subject || (page.kind === "geography" ? "Geografi" : page.kind === "homework" ? "Läxa" : "Matte");
  ctx.font = `700 15px ${FONT}`;
  const chipW = ctx.measureText(chip).width + 28;
  roundRect(ctx, innerX, y - (compact ? 14 : 20), chipW, compact ? 24 : 30, 15);
  ctx.fillStyle = ACCENT;
  ctx.fill();
  ctx.fillStyle = ACCENT_INK;
  ctx.textBaseline = "middle";
  put(chip, innerX + 14, y - 4);
  if (assets.pageLabel) {
    ctx.fillStyle = MUTED;
    ctx.font = `500 15px ${FONT}`;
    ctx.textAlign = "right";
    put(assets.pageLabel, cardX + cardW - padding, y - 4);
    ctx.textAlign = "left";
  }
  y += compact ? 14 : 22;

  // Title. Geography caps the heading so the map keeps its share of the
  // one-page workspace; overflow is honest (ellipsis), never clipped.
  ctx.fillStyle = INK;
  ctx.font = `700 ${compact ? 18 : clamp(w * 0.032, 24, 40)}px ${FONT}`;
  ctx.textBaseline = "alphabetic";
  {
    const fullTitle = wrapText(ctx, page.title, innerW);
    const maxTitle = page.kind === "geography" ? (h < 320 ? 1 : 2) : fullTitle.length;
    let titleLines = fullTitle.slice(0, maxTitle);
    if (fullTitle.length > maxTitle && titleLines.length > 0) {
      titleLines[titleLines.length - 1] = truncate(ctx, `${titleLines[titleLines.length - 1]} \u2026`, innerW);
    }
    const titleBottom =
      page.kind === "homework" ? cardY + cardH - 60 : page.kind === "geography" ? geoAnswerY - gap : bodyBottom;
    for (const line of titleLines) {
      const nextY = y + lineHeight(ctx);
      if (nextY > titleBottom) {
        // No room even for an honest heading line: stop instead of
        // clipping text outside the card.
        break;
      }
      y = nextY;
      put(line, innerX, y);
    }
  }
  y += compact ? 6 : 14;

  // Homework pages: child-uploaded content. Image contain-fit with
  // attribution (never a permanent loading placeholder), expanded body text,
  // and no exercise answer box or hidden facit — the freed space is content.
  if (page.kind === "homework") {
    const hwBoxW = innerW;
    const hwBoxX = innerX;
    const hwFooterH = 44;
    ctx.font = `400 ${clamp(w * 0.02, 17, 24)}px ${FONT}`;
    ctx.fillStyle = "#dce6f7";
    const hwImage = page.asset?.id ? assets.images?.get(page.asset.id) : undefined;
    const hwSvg = !hwImage && page.svgAsset ? assets.svgImage : undefined;
    const hwHasDrawable = Boolean(hwImage || hwSvg);
    const hwHasVisual = Boolean(page.asset?.id || page.svgAsset);
    const hwVisualH = hwHasDrawable ? clamp(h * 0.38, 160, 360) : 0;
    const hwBodyLimit = cardY + cardH - hwFooterH - (hwHasDrawable ? hwVisualH + 52 : 30);
    for (const paragraph of page.body.slice(0, 15)) {
      for (const line of wrapText(ctx, paragraph, innerW)) {
        y += lineHeight(ctx) * 0.96;
        if (y > hwBodyLimit) break;
        put(line, innerX, y);
      }
      y += 8;
      if (y > hwBodyLimit) break;
    }
    if (hwHasDrawable) {
      const hwBoxY = Math.max(y + 6, cardY + cardH - hwFooterH - hwVisualH - 16);
      roundRect(ctx, hwBoxX, hwBoxY, hwBoxW, hwVisualH, 12);
      ctx.fillStyle = "#0a1122";
      ctx.fill();
      ctx.strokeStyle = CARD_BORDER;
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.save();
      roundRect(ctx, hwBoxX, hwBoxY, hwBoxW, hwVisualH, 12);
      ctx.clip();
      drawContain(ctx, (hwImage ?? hwSvg) as CanvasImageSource, hwBoxX, hwBoxY, hwBoxW, hwVisualH);
      ctx.restore();
      const hwAttribution = page.asset?.attribution ?? page.asset?.provenance ?? (page.svgAsset ? "Genererad bild" : null);
      if (hwAttribution) {
        ctx.fillStyle = MUTED;
        ctx.font = `400 12px ${FONT}`;
        put(truncate(ctx, `Bild: ${hwAttribution}`, hwBoxW - 16), hwBoxX + 8, hwBoxY + hwVisualH - 10);
      }
      y = hwBoxY + hwVisualH + 14;
    } else if (hwHasVisual) {
      const hwAttribution = page.asset?.attribution ?? page.asset?.provenance ?? null;
      if (hwAttribution) {
        ctx.fillStyle = MUTED;
        ctx.font = `400 12px ${FONT}`;
        if (y + 20 <= cardY + cardH - hwFooterH - 8) {
          put(truncate(ctx, `Bild: ${hwAttribution}`, hwBoxW - 16), hwBoxX + 8, y + 18);
          y += 24;
        }
      }
    }
    ctx.fillStyle = MUTED;
    ctx.font = `400 12.5px ${FONT}`;
    const hwSources = page.sources.slice(0, 2).join(" · ");
    if (hwSources) put(truncate(ctx, `Källor: ${hwSources}`, hwBoxW * 0.62), hwBoxX, cardY + cardH - 14);
    return finish();
  }

  // Geography pages: the researched/generated map is the hero. Desktop
  // uses two columns (short text left, large map right); phones stack a
  // compact body over a large map. Slim answer/solution strips keep the
  // one-page workspace with no scrolling. Truncation is honest (ellipsis),
  // never clipped outside the canvas.
  if (page.kind === "geography") {
    const geoBoxW = innerW;
    const geoBoxX = innerX;
    const geoSolutionY = geoAnswerY + geoAnswerH + gap;
    ctx.font = `400 ${compact ? 15 : clamp(w * 0.02, 17, 24)}px ${FONT}`;
    ctx.fillStyle = "#dce6f7";
    const geoLineH = lineHeight(ctx) * 0.96;
    const geoContentTop = y;
    const geoContentBottom = geoAnswerY - gap;
    const geoContentH = geoContentBottom - geoContentTop;
    const geoImage = page.asset?.id ? assets.images?.get(page.asset.id) : undefined;
    const geoSvg = !geoImage && page.svgAsset ? assets.svgImage : undefined;
    const geoHasDrawable = Boolean(geoImage || geoSvg);
    const geoAttribution = page.asset?.attribution ?? (page.svgAsset ? "Genererad bild" : null);
    const drawGeoMapBox = (bx: number, by: number, bw: number, bh: number): void => {
      if (bw < 32 || bh < 32 || by + bh > cardY + cardH) return;
      roundRect(ctx, bx, by, bw, bh, 12);
      ctx.fillStyle = "#0a1122";
      ctx.fill();
      ctx.strokeStyle = CARD_BORDER;
      ctx.lineWidth = 1;
      ctx.stroke();
      if (geoHasDrawable) {
        ctx.save();
        roundRect(ctx, bx, by, bw, bh, 12);
        ctx.clip();
        drawContain(ctx, (geoImage ?? geoSvg) as CanvasImageSource, bx, by, bw, bh);
        ctx.restore();
      } else {
        drawMapPlaceholder(ctx, bx, by, bw, bh, page);
        drawn.push("Karta laddas \u2026");
      }
      if (geoAttribution && bh >= 56) {
        ctx.fillStyle = MUTED;
        ctx.font = `400 12px ${FONT}`;
        put(truncate(ctx, `Bild: ${geoAttribution}`, bw - 16), bx + 8, by + bh - 10);
        ctx.font = `400 ${compact ? 15 : clamp(w * 0.02, 17, 24)}px ${FONT}`;
        ctx.fillStyle = "#dce6f7";
      }
    };
    // Draws wrapped body paragraphs within [top, bottom] with paragraph
    // gaps. Returns the y after the last drawn line. Overflow is honest:
    // the last visible line gains an ellipsis; nothing is drawn past bottom.
    const drawGeoParagraphs = (maxWidth: number, x: number, top: number, bottom: number): number => {
      const paras = page.body.slice(0, 6).map((p) => wrapText(ctx, p, maxWidth));
      const total = paras.reduce((n, ls) => n + ls.length, 0);
      let yy = top;
      let fit = 0;
      let stop = false;
      for (const ls of paras) {
        for (let i = 0; i < ls.length; i++) {
          if (yy + geoLineH > bottom) {
            stop = true;
            break;
          }
          yy += geoLineH;
          fit++;
        }
        if (stop) break;
        yy += 8;
      }
      const truncated = fit < total;
      yy = top;
      let doneCount = 0;
      for (const ls of paras) {
        for (let i = 0; i < ls.length; i++) {
          if (doneCount >= fit) break;
          let text = ls[i] ?? "";
          if (truncated && doneCount === fit - 1) {
            text = truncate(ctx, `${text} \u2026`, maxWidth);
          }
          yy += geoLineH;
          put(text, x, yy);
          doneCount++;
        }
        if (doneCount >= fit) break;
        yy += 8;
      }
      return yy;
    };
    if (geoTwoCol) {
      const colGap = 16;
      const leftW = Math.round(innerW * 0.44);
      const rightW = innerW - leftW - colGap;
      drawGeoParagraphs(leftW, innerX, geoContentTop, geoContentBottom);
      if (hasVisual && geoContentH >= 48 && rightW >= 64) {
        drawGeoMapBox(innerX + leftW + colGap, geoContentTop, rightW, geoContentH);
      }
    } else {
      let mapH = 0;
      if (hasVisual && geoContentH > 0) {
        if (geoContentH < 120) {
          mapH = Math.max(0, Math.floor((geoContentH - gap) / 2));
        } else {
          mapH = clamp(Math.round(geoContentH * 0.55), 120, 320);
        }
        mapH = Math.min(mapH, geoContentH);
      }
      const bodyH = geoContentH - mapH - (mapH > 0 ? gap : 0);
      drawGeoParagraphs(innerW, innerX, geoContentTop, geoContentTop + bodyH);
      if (mapH >= 48) {
        drawGeoMapBox(innerX, geoContentTop + bodyH + gap, innerW, mapH);
      }
    }
    // Designated child draft (slim) + fox-gated reveal stay coherent.
    roundRect(ctx, geoBoxX, geoAnswerY, geoBoxW, geoAnswerH, 12);
    ctx.fillStyle = ANSWER_BG;
    ctx.fill();
    ctx.strokeStyle = CARD_BORDER;
    ctx.stroke();
    ctx.fillStyle = MUTED;
    ctx.font = `600 14px ${FONT}`;
    put(page.answerLabel || "Ditt svar", geoBoxX + 14, geoAnswerY + (compact ? 16 : 22));
    const geoDraft = (assets.draftText ?? "").trim();
    ctx.font = `400 ${clamp(w * 0.019, 16, 22)}px ${FONT}`;
    if (geoDraft) {
      ctx.fillStyle = INK;
      const geoDraftLines = wrapText(ctx, geoDraft, geoBoxW - 28).slice(0, compact ? 1 : 2);
      geoDraftLines.forEach((line, i) => put(line, geoBoxX + 14, geoAnswerY + (compact ? 36 : 50) + i * lineHeight(ctx) * 0.95));
    } else {
      ctx.fillStyle = "#5c6c8d";
      put("Skriv ditt svar h\u00e4r \u2026", geoBoxX + 14, geoAnswerY + (compact ? 36 : 54));
    }
    roundRect(ctx, geoBoxX, geoSolutionY, geoBoxW, geoSolutionH, 12);
    if (page.revealed) {
      ctx.fillStyle = SOLUTION_BG;
      ctx.fill();
      ctx.strokeStyle = SOLUTION_BORDER;
      ctx.stroke();
      ctx.fillStyle = "#7ee2a8";
      ctx.font = `600 14px ${FONT}`;
      put("Facit", geoBoxX + 14, geoSolutionY + (compact ? 16 : 22));
      ctx.fillStyle = "#e8f7ee";
      ctx.font = `400 ${clamp(w * 0.019, 16, 22)}px ${FONT}`;
      geoSolLines.forEach((line, i) => put(line, geoBoxX + 14, geoSolutionY + (compact ? 36 : 50) + i * lineHeight(ctx) * 0.95));
    } else {
      ctx.fillStyle = HIDDEN_BG;
      ctx.fill();
      ctx.strokeStyle = CARD_BORDER;
      ctx.stroke();
      ctx.fillStyle = MUTED;
      ctx.font = `600 16px ${FONT}`;
      put("\uD83D\uDD12 Facit \u00e4r dolt", geoBoxX + 14, geoSolutionY + geoSolutionH / 2 + 6);
    }
    ctx.fillStyle = MUTED;
    ctx.font = `400 12.5px ${FONT}`;
    const geoSources = page.sources.slice(0, 2).join(" \u00b7 ");
    if (geoSources) put(truncate(ctx, `K\u00e4llor: ${geoSources}`, geoBoxW * 0.62), geoBoxX, cardY + cardH - 14);
    return finish();
  }

  // Body / question lines.
  ctx.font = `400 ${compact ? 15 : clamp(w * 0.02, 17, 24)}px ${FONT}`;
  ctx.fillStyle = "#dce6f7";
  for (const paragraph of page.body.slice(0, 6)) {
    for (const line of wrapText(ctx, paragraph, innerW)) {
      const nextY = y + lineHeight(ctx) * 0.96;
      if (nextY > bodyBottom) break;
      y = nextY;
      put(line, innerX, y);
    }
    y += 8;
  }

  const boxW = innerW;
  const boxX = innerX;

  // Visual asset box (image or generated-SVG placeholder).
  if (hasVisual) {
    const boxY = visualY;
    if (boxY > cardY + 30) {
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
        drawn.push("Bild laddas \u2026");
      }
      const attribution = page.asset?.attribution ?? (page.svgAsset ? "Genererad bild" : null);
      if (attribution) {
        ctx.fillStyle = MUTED;
        ctx.font = `400 12px ${FONT}`;
        put(truncate(ctx, `Bild: ${attribution}`, boxW - 16), boxX + 8, y + visualH - 10);
      }
      y += visualH + 14;
    }
  }

  // Answer area (child-owned; drawn so pixels match what the child sees).
  const answerBoxY = answerY;
  roundRect(ctx, boxX, answerBoxY, boxW, answerH, 12);
  ctx.fillStyle = ANSWER_BG;
  ctx.fill();
  ctx.strokeStyle = CARD_BORDER;
  ctx.stroke();
  ctx.fillStyle = MUTED;
  ctx.font = `600 14px ${FONT}`;
  put(page.answerLabel || "Ditt svar", boxX + 14, answerBoxY + (compact ? 16 : 22));
  const draft = (assets.draftText ?? "").trim();
  ctx.font = `400 ${clamp(w * 0.019, 16, 22)}px ${FONT}`;
  if (draft) {
    ctx.fillStyle = INK;
    const lines = wrapText(ctx, draft, boxW - 28).slice(0, compact ? 1 : 2);
    lines.forEach((line, i) => put(line, boxX + 14, answerBoxY + (compact ? 36 : 50) + i * lineHeight(ctx) * 0.95));
  } else {
    ctx.fillStyle = "#5c6c8d";
    put("Skriv ditt svar här …", boxX + 14, answerBoxY + (compact ? 36 : 54));
  }

  // Solution area: hidden until the fox-gated reveal.
  const solutionY = answerBoxY + answerH + gap;
  roundRect(ctx, boxX, solutionY, boxW, solutionH, 12);
  if (page.revealed) {
    ctx.fillStyle = SOLUTION_BG;
    ctx.fill();
    ctx.strokeStyle = SOLUTION_BORDER;
    ctx.stroke();
    ctx.fillStyle = "#7ee2a8";
    ctx.font = `600 14px ${FONT}`;
    put("Facit", boxX + 14, solutionY + (compact ? 16 : 22));
    ctx.fillStyle = "#e8f7ee";
    ctx.font = `400 ${clamp(w * 0.019, 16, 22)}px ${FONT}`;
    solutionLines.forEach((line, i) => put(line, boxX + 14, solutionY + (compact ? 36 : 50) + i * lineHeight(ctx) * 0.95));
  } else {
    ctx.fillStyle = HIDDEN_BG;
    ctx.fill();
    ctx.strokeStyle = CARD_BORDER;
    ctx.stroke();
    ctx.fillStyle = MUTED;
    ctx.font = `600 16px ${FONT}`;
    put("🔒 Facit är dolt", boxX + 14, solutionY + solutionH / 2 + 6);
  }

  // Source attribution stays on the teaching surface.
  ctx.fillStyle = MUTED;
  ctx.font = `400 12.5px ${FONT}`;
  const sources = page.sources.slice(0, 2).join(" · ");
  if (sources) put(truncate(ctx, `Källor: ${sources}`, boxW * 0.62), boxX, cardY + cardH - 14);
  return finish();
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
