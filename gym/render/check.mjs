#!/usr/bin/env node
// Board self-check lint.
// Usage: node check.mjs --html board.html
// Renders the board exactly like render.mjs (1920x1080, only
// https://cdn.jsdelivr.net allowed, BoardKit URL served locally), then prints
// a short plain-text report and exits 0 when clean, 1 on any finding.
// Findings: console/page errors, page scroll or overflow beyond 1920x1080,
// elements outside the board or within 24px of an edge, text under 24px,
// overlapping text boxes (HTML + SVG text), blocked network requests.
import { chromium } from 'playwright-core';
import { readFileSync, existsSync, mkdtempSync, rmSync } from 'fs';
import { execSync } from 'child_process';
import { homedir, tmpdir } from 'os';
import { dirname, join, resolve } from 'path';
import { fileURLToPath } from 'url';

function arg(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : null;
}

const htmlPath = arg('--html') || 'board.html';

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

// Same toolkit interception as render.mjs (see notes there): TOOLKIT_URL /
// TOOLKIT_FILE configure the local file served at a jsdelivr-style URL.
const BOARDKIT_URL = process.env.TOOLKIT_URL ||
  'https://cdn.jsdelivr.net/gh/johan-acevedo/board-kit@0.1.0/board-kit.js';

function findBoardKit(htmlPathArg) {
  const cands = [];
  if (process.env.TOOLKIT_FILE) cands.push(process.env.TOOLKIT_FILE);
  try { cands.push(join(dirname(resolve(htmlPathArg)), 'board-kit.js')); } catch { /* ignore */ }
  cands.push(resolve('board-kit.js'));
  try {
    cands.push(join(dirname(fileURLToPath(import.meta.url)),
      '..', '..', 'toolkit', 'board-kit.js'));
  } catch { /* ignore */ }
  for (const c of cands) {
    try { if (c && existsSync(c)) return c; } catch { /* ignore */ }
  }
  return null;
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
    return route.continue();
  }
  if (url.startsWith('file://') || url.startsWith('data:') ||
      url.startsWith('about:') || url.startsWith('blob:') ||
      url.startsWith('https://cdn.jsdelivr.net')) {
    return route.continue();
  }
  blocked.push(url.slice(0, 300));
  return route.abort();
});

page.on('console', (msg) => {
  if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 300));
});
page.on('pageerror', (err) => pageErrors.push(String(err).slice(0, 300)));

const fileUrl = 'file://' + resolve(htmlPath);
await page.clock.install();
await page.goto(fileUrl, { waitUntil: 'load', timeout: 30000 });
await page.waitForTimeout(300);
// Lint the settled board: run timers ahead, finish finite animations (same as render.mjs).
await page.clock.runFor(16500);
await page.evaluate(() => { for (const a of document.getAnimations()) { try { a.finish(); } catch {} } });
await page.waitForTimeout(300);

// Render to a temp PNG (same framing as render.sh) so layout is final.
const workdir = mkdtempSync(join(tmpdir(), 'boardcheck-'));
await page.screenshot({ path: join(workdir, 'check.png') });

const data = await page.evaluate(() => {
  const W = 1920, H = 1080, M = 24;
  const out = {
    scroll: {
      sw: document.documentElement.scrollWidth,
      sh: document.documentElement.scrollHeight,
      iw: window.innerWidth, ih: window.innerHeight,
    },
    outside: [], nearEdge: [], smallText: [], overlaps: [],
  };
  function label(el) {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    else if (el.getAttribute && el.getAttribute('class') && typeof el.getAttribute('class') === 'string')
      s += '.' + el.getAttribute('class').split(/\s+/)[0].slice(0, 24);
    let t = (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 42);
    if (t) s += ' "' + t + '"';
    return s.slice(0, 90);
  }
  function visBox(el) {
    let r;
    try { r = el.getBoundingClientRect(); } catch (e) { return null; }
    if (!r || r.width <= 0 || r.height <= 0) return null;
    try {
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') return null;
      if (parseFloat(cs.opacity) === 0) return null;
    } catch (e) { /* ignore */ }
    return r;
  }
  const els = Array.from(document.querySelectorAll('body *'));
  const boxes = [];
  for (const el of els) {
    const r = visBox(el);
    if (!r) continue;
    boxes.push({ el, r });
    const spansFull = (r.left <= 0 && r.right >= W) || (r.top <= 0 && r.bottom >= H);
    if (r.left < 0 || r.top < 0 || r.right > W || r.bottom > H) {
      out.outside.push(label(el) + ' @[' +
        Math.round(r.left) + ',' + Math.round(r.top) + ' ' +
        Math.round(r.width) + 'x' + Math.round(r.height) + ']');
    } else if (!spansFull &&
        (r.left < M || r.top < M || r.right > W - M || r.bottom > H - M)) {
      out.nearEdge.push(label(el) + ' @[' +
        Math.round(r.left) + ',' + Math.round(r.top) + ' ' +
        Math.round(r.width) + 'x' + Math.round(r.height) + ']');
    }
  }
  // Text under 24px: elements with direct (non-whitespace) text.
  for (const { el, r } of boxes) {
    let direct = '';
    for (const n of el.childNodes) {
      if (n.nodeType === 3) direct += n.nodeValue;
    }
    if (!direct.replace(/\s+/g, '').length) continue;
    let px = 0;
    try { px = parseFloat(getComputedStyle(el).fontSize); } catch (e) { continue; }
    if (px > 0 && px < 24) out.smallText.push(label(el) + ' (' + px.toFixed(1) + 'px)');
  }
  // Overlapping text boxes (HTML text elements + SVG <text>).
  const items = boxes.filter(({ el }) => {
    if (el.tagName && el.tagName.toLowerCase() === 'text') return true;
    for (const n of el.childNodes) {
      if (n.nodeType === 3 && n.nodeValue.replace(/\s+/g, '').length) return true;
    }
    return false;
  });
  function sameEq(a, b) {
    try {
      const ka = a.closest ? a.closest('.katex') : null;
      const kb = b.closest ? b.closest('.katex') : null;
      return !!(ka && kb && ka === kb);
    } catch (e) { return false; }
  }
  for (let i = 0; i < items.length; i++) {
    for (let j = i + 1; j < items.length; j++) {
      const A = items[i], B = items[j];
      if (A.el === B.el || A.el.contains(B.el) || B.el.contains(A.el)) continue;
      if (sameEq(A.el, B.el)) continue;
      const ox = Math.min(A.r.right, B.r.right) - Math.max(A.r.left, B.r.left);
      const oy = Math.min(A.r.bottom, B.r.bottom) - Math.max(A.r.top, B.r.top);
      if (ox > 2 && oy > 2) {
        out.overlaps.push(label(A.el) + '  <>  ' + label(B.el));
        if (out.overlaps.length >= 12) break;
      }
    }
    if (out.overlaps.length >= 12) break;
  }
  return out;
});

await browser.close();
try { rmSync(workdir, { recursive: true, force: true }); } catch { /* ignore */ }

const findings = [];
if (consoleErrors.length) findings.push(['console-errors', consoleErrors]);
if (pageErrors.length) findings.push(['page-errors', pageErrors]);
if (data.scroll.sw > data.scroll.iw || data.scroll.sh > data.scroll.ih)
  findings.push(['scroll', ['page ' + data.scroll.sw + 'x' + data.scroll.sh +
    ' exceeds viewport ' + data.scroll.iw + 'x' + data.scroll.ih]]);
if (data.outside.length) findings.push(['outside-board', data.outside]);
if (data.nearEdge.length) findings.push(['near-edge(<24px)', data.nearEdge]);
if (data.smallText.length) findings.push(['text-under-24px', data.smallText]);
if (data.overlaps.length) findings.push(['overlapping-text', data.overlaps]);
if (blocked.length) findings.push(['blocked-requests', blocked]);

if (process.argv.includes('--json')) {
  // Machine-readable report for the harness (stdout is JSON only).
  const byName = {};
  for (const [name, list] of findings) byName[name] = list;
  console.log(JSON.stringify({
    html: htmlPath,
    clean: findings.length === 0,
    console_errors: byName['console-errors'] || [],
    page_errors: byName['page-errors'] || [],
    scroll: data.scroll,
    scrolls: data.scroll.sw > data.scroll.iw || data.scroll.sh > data.scroll.ih,
    outside: byName['outside-board'] || [],
    near_edge: byName['near-edge(<24px)'] || [],
    small_text: byName['text-under-24px'] || [],
    overlaps: byName['overlapping-text'] || [],
    blocked: byName['blocked-requests'] || [],
  }));
} else {
  console.log('check ' + htmlPath);
  if (!findings.length) {
    console.log('OK: clean (1920x1080, no errors, no overflow, text >= 24px)');
  } else {
    console.log('FAIL: ' + findings.reduce((n, f) => n + f[1].length, 0) +
      ' finding(s) in ' + findings.length + ' categor' +
      (findings.length === 1 ? 'y' : 'ies'));
    for (const [name, list] of findings) {
      console.log('- ' + name + ' (' + list.length + '):');
      for (const item of list.slice(0, 6)) console.log('    ' + item);
      if (list.length > 6) console.log('    ... +' + (list.length - 6) + ' more');
    }
  }
}
process.exit(findings.length ? 1 : 0);
