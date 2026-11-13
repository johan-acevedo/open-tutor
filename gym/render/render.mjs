#!/usr/bin/env node
// Headless-Chromium board renderer.
// Usage: node render.mjs --html board.html --png board.png --meta render.json
//   --html  input HTML file
//   --png   output PNG path (exactly 1920x1080)
//   --meta  output JSON path (console errors, scroll state, blocked requests)
// Blocks every network request except https://cdn.jsdelivr.net.
import { chromium } from 'playwright-core';
import { writeFileSync, readFileSync, existsSync } from 'fs';
import { execSync } from 'child_process';
import { homedir } from 'os';
import { dirname, join, resolve } from 'path';
import { fileURLToPath } from 'url';

// Optional local toolkit file served at a fixed jsdelivr-style URL, so boards
// can load it as if from the network (the renderer only allows
// https://cdn.jsdelivr.net). Configured via env: TOOLKIT_URL is the public URL
// the board uses, TOOLKIT_FILE is the local file to serve for it. When unset,
// no special-casing applies and every jsdelivr request passes to the network.
// (Legacy default kept for backwards compat; override with env.)
const BOARDKIT_URL = process.env.TOOLKIT_URL ||
  'https://cdn.jsdelivr.net/gh/johan-acevedo/board-kit@0.1.0/board-kit.js';

function findBoardKit(htmlPathArg) {
  const cands = [];
  if (process.env.TOOLKIT_FILE) cands.push(process.env.TOOLKIT_FILE);
  try { cands.push(join(dirname(resolve(htmlPathArg)), 'board-kit.js')); } catch { /* ignore */ }
  cands.push(resolve('board-kit.js')); // run-dir copy
  try {
    cands.push(join(dirname(fileURLToPath(import.meta.url)),
      '..', '..', 'toolkit', 'board-kit.js')); // central toolkit file
  } catch { /* ignore */ }
  for (const c of cands) {
    try { if (c && existsSync(c)) return c; } catch { /* ignore */ }
  }
  return null;
}

function arg(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : null;
}

const htmlPath = arg('--html');
const pngPath = arg('--png');
const metaPath = arg('--meta');
if (!htmlPath || !pngPath || !metaPath) {
  console.error('usage: render.mjs --html H --png P --meta M');
  process.exit(2);
}

function findChrome() {
  if (process.env.CHROMIUM_PATH && existsSync(process.env.CHROMIUM_PATH))
    return process.env.CHROMIUM_PATH;
  const cands = [
    `${homedir()}/.cache/ms-playwright/chromium-1252/chrome-linux64/chrome`,
    `${homedir()}/.cache/ms-playwright/chromium_headless_shell-1252/chrome-headless-shell-linux64/chrome-headless-shell`,
  ];
  for (const c of cands) if (existsSync(c)) return c;
  try {
    return execSync(
      'ls -d $HOME/.cache/ms-playwright/chromium-*/chrome-linux*/chrome ' +
      '$HOME/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell 2>/dev/null | head -1',
      { encoding: 'utf8' }).trim() || null;
  } catch { return null; }
}

const executablePath = findChrome();
if (!executablePath) {
  console.error('no cached chromium found');
  process.exit(3);
}

const blocked = [];
const consoleErrors = [];
const pageErrors = [];

const browser = await chromium.launch({ executablePath });
const page = await browser.newPage({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
});

await page.route('**/*', (route) => {
  const url = route.request().url();
  if (url === BOARDKIT_URL || url.split('?')[0] === BOARDKIT_URL) {
    const local = findBoardKit(htmlPath);
    if (local) {
      return route.fulfill({
        status: 200,
        contentType: 'application/javascript',
        body: readFileSync(local, 'utf-8'),
      });
    }
    // No local copy: let it pass through (network 404 shows as page error).
    return route.continue();
  }
  if (url.startsWith('file://') || url.startsWith('data:') ||
      url.startsWith('about:') || url.startsWith('blob:') ||
      url.startsWith('https://cdn.jsdelivr.net') ||
      /^https:\/\/(([a-c]\.)?tile\.openstreetmap\.org|([a-d]\.)?basemaps\.cartocdn\.com)/.test(url)) {
    return route.continue();
  }
  blocked.push(url.slice(0, 300));
  return route.abort();
});

page.on('console', (msg) => {
  if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 500));
});
page.on('pageerror', (err) => pageErrors.push(String(err).slice(0, 500)));

const fileUrl = 'file://' + resolve(htmlPath);
await page.goto(fileUrl, { waitUntil: 'load', timeout: 30000 });
await page.waitForTimeout(300);
await page.clock.runFor(1500);
// Early frame: what the child sees ~1.5 s after the board appears.
const earlyPath = pngPath.replace(/\.png$/, '') + '-early.png';
await page.screenshot({ path: earlyPath, clip: { x: 0, y: 0, width: 1920, height: 1080 } });
// Settled frame: run JS timers 15 s ahead and finish every finite CSS/Web animation,
// so staggered reveals are judged in their final state.
await page.clock.runFor(15000);
const anim = await page.evaluate(() => {
  let finished = 0, infinite = 0;
  for (const a of document.getAnimations()) {
    try { a.finish(); finished++; } catch { infinite++; }
  }
  return { finished, infinite };
});
await page.waitForTimeout(300);

const scroll = await page.evaluate(() => ({
  scrollWidth: document.documentElement.scrollWidth,
  scrollHeight: document.documentElement.scrollHeight,
  innerWidth: window.innerWidth,
  innerHeight: window.innerHeight,
}));
scroll.scrolls =
  scroll.scrollWidth > scroll.innerWidth || scroll.scrollHeight > scroll.innerHeight;

await page.screenshot({ path: pngPath, clip: { x: 0, y: 0, width: 1920, height: 1080 } });
await browser.close();

writeFileSync(metaPath, JSON.stringify({
  console_errors: consoleErrors,
  page_errors: pageErrors,
  blocked_requests: blocked,
  scroll,
  animations: anim,
  early_png: earlyPath,
  viewport: { width: 1920, height: 1080 },
}, null, 2) + '\n');
console.log(`rendered ${pngPath}`);
