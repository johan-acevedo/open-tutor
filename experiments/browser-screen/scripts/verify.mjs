// Repeatable technical proof for the browser-owned Pi Durable screen.
//
// Usage: node scripts/verify.mjs
// Env: PROOF_URL (default https://dell5500.tail2e1c4e.ts.net:9443/),
//   token read from ~/.config/open-tutor-proof/env (PROOF_TOKEN).
//
// Asserts, against the REAL served app with LIVE models:
//  1. worker boots a browser-owned Pi Durable session (IndexedDB)
//  2. fox-command-gated reveal (bound to page id + revision)
//  3. stale reveal rejected, duplicate reveal ignored
//  4. child input preserved across page switches
//  5. everything restored after full close + reopen (same conversation)
//  6. live vision describes the ACTUAL visible pixels (revealed vs hidden)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright-core";

const URL = process.env.PROOF_URL ?? "https://dell5500.tail2e1c4e.ts.net:9443/";
const EXE = "/home/johan/.cache/ms-playwright/chromium-1254/chrome-linux64/chrome";
const token = fs
  .readFileSync(path.join(process.env.HOME ?? "", ".config/open-tutor-proof/env"), "utf8")
  .match(/PROOF_TOKEN=(.*)/)?.[1]
  ?.trim();
if (!token) throw new Error("PROOF_TOKEN missing in ~/.config/open-tutor-proof/env");

const DIR = fs.mkdtempSync(path.join(os.tmpdir(), "proof-verify-"));
let failures = 0;
const check = (name, cond, extra = "") => {
  console.log(`${cond ? "PASS" : "FAIL"} ${name}${extra ? ` — ${extra}` : ""}`);
  if (!cond) failures += 1;
};

async function openProfile() {
  const browser = await chromium.launchPersistentContext(DIR, {
    executablePath: EXE,
    args: ["--no-sandbox"],
    ignoreHTTPSErrors: true,
  });
  const page = browser.pages()[0] ?? (await browser.newPage());
  await page.goto(URL, { waitUntil: "networkidle", timeout: 30000 });
  if (!(await page.inputValue("#token").catch(() => ""))) {
    await page.fill("#token", token);
  }
  await page.click("#open");
  await page.waitForFunction(
    () => document.getElementById("conv")?.textContent?.includes("samtal ") &&
      !document.getElementById("conv")?.textContent?.includes("…"),
    null,
    { timeout: 60000 },
  );
  return { browser, page };
}

const snap = (page) => page.evaluate(() => window.__proof.snapshot);

// ---- session 1: build the deck ----
let { browser, page } = await openProfile();
const conv1 = await page.textContent("#conv");
check("worker boots browser-owned session", conv1.includes("samtal"));

await page.evaluate(() => window.__proof.send({ kind: "prepare", topic: "bråk", level: "åk 4–6" }));
await page.waitForFunction(
  () => (document.getElementById("page-label")?.textContent || "").includes("Sida 1 av"),
  null,
  { timeout: 180000 },
);
let s = await snap(page);
const p1 = { id: s.pages[0].id, rev: s.pages[0].revision };
check("page 1 prepared by live model", s.pages.length === 1 && s.pages[0].question.length > 10, s.pages[0]?.question?.slice(0, 60));

await page.fill("#answer", "5/8");
await page.waitForTimeout(2000);
check("child input saved to workspace", (await snap(page)).pages[0].input === "5/8");

await page.evaluate(() => window.__proof.send({ kind: "prepare", topic: "multiplikation", level: "åk 4–6" }));
await page.waitForFunction(
  () => (document.getElementById("page-label")?.textContent || "").includes("Sida 2 av"),
  null,
  { timeout: 180000 },
);
check("second page prepared (page deck, not chat log)", (await snap(page)).pages.length === 2);

await page.evaluate(() => window.__proof.send({ kind: "goto", index: 0 }));
await page.waitForTimeout(2500);
s = await snap(page);
check("input preserved across page switch", s.pages[0].input === "5/8", JSON.stringify(s.pages[0].input));
check("answer box follows visible page", (await page.inputValue("#answer")) === "5/8", await page.inputValue("#answer"));

// fox reveal, stale, duplicate
const cur1 = await page.evaluate(() => { const d = window.__proof.snapshot; const p = d.pages[d.current]; return { id: p.id, rev: p.revision }; });
await page.evaluate((c) => window.__proof.send({ kind: "fox", command: "visa svaret", pageId: c.id, revision: c.rev }), cur1);
await page.waitForTimeout(3000);
check(
  "fox reveal shows answer on current page",
  (await snap(page)).pages[0].revealed === true && (await page.textContent("#fox-bubble")).includes("visar svaret"),
);

await page.evaluate(() => window.__proof.send({ kind: "goto", index: 1 }));
await page.waitForTimeout(2500);
await page.evaluate((stale) => window.__proof.send({ kind: "fox", command: "visa svaret", pageId: stale.id, revision: stale.rev }), p1);
await page.waitForTimeout(2500);
s = await snap(page);
check(
  "stale reveal rejected (other page untouched)",
  s.pages[s.current].revealed === false && (await page.textContent("#fox-bubble")).includes("Avvisat"),
  await page.textContent("#fox-bubble"),
);

await page.evaluate(() => window.__proof.send({ kind: "goto", index: 0 }));
await page.waitForTimeout(2500);
await page.evaluate((c) => window.__proof.send({ kind: "fox", command: "visa svaret", pageId: c.id, revision: c.rev }), cur1);
await page.waitForTimeout(2500);
check("duplicate reveal ignored", (await page.textContent("#fox-bubble")).includes("Redan") || (await page.textContent("#fox-bubble")).includes("Dubblett"));

// live vision on the REVEALED page: fox must see question + input + visible answer
await page.click("#observe");
await page.waitForFunction(
  () => (document.getElementById("observed")?.textContent || "").includes("Räven ser:"),
  null,
  { timeout: 180000 },
);
const seenRevealed = await page.textContent("#observed");
const sol1 = (await snap(page)).pages[0].solution;
check("live vision sees revealed answer on visible page", seenRevealed.includes(sol1.slice(0, 20)), seenRevealed.slice(0, 200));

await browser.close();

// ---- session 2: full close + reopen, same profile ----
({ browser, page } = await openProfile());
const conv2 = await page.textContent("#conv");
check("same durable conversation after reopen", conv2 === conv1, `${conv1} vs ${conv2}`);
s = await snap(page);
check("pages restored after reopen", s.pages.length === 2, `pages=${s.pages.length}`);
check("input restored after reopen", s.pages[0].input === "5/8", JSON.stringify(s.pages[0]?.input));
check("reveal state restored after reopen", s.pages[0].revealed === true);

// live vision on the HIDDEN page: answer must stay hidden from the fox
await page.evaluate(() => window.__proof.send({ kind: "goto", index: 1 }));
await page.waitForTimeout(2500);
await page.click("#observe");
await page.waitForFunction(
  () => {
    const t = document.getElementById("observed")?.textContent || "";
    return t.includes("Räven ser:") && !t.includes("Modellens synbeskrivning");
  },
  null,
  { timeout: 180000 },
);
const seenHidden = await page.textContent("#observed");
const sol2 = (await snap(page)).pages[1].solution;
check(
  "live vision distinguishes hidden answer",
  /dolt|hidden|···/.test(seenHidden) && !seenHidden.includes(sol2.slice(0, 20)),
  seenHidden.slice(0, 250),
);

await browser.close();
fs.rmSync(DIR, { recursive: true, force: true });

console.log(failures === 0 ? "VERIFY OK" : `VERIFY FAILED (${failures})`);
process.exit(failures === 0 ? 0 : 1);
