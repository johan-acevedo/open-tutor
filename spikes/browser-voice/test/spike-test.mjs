// Headless fake-mic check for the voice-tutor spike.
// Asserts: user transcript appears, an LLM reply streams back, TTS audio plays.
// Records the timing panel for 3 turns as JSON (paste into README).
//
// Usage: node test/spike-test.mjs [URL]
//   URL defaults to http://127.0.0.1:8001/
// The Command Code key is NEVER committed: it comes from $VOICE_SPIKE_KEY,
// or (test-time only) ~/.pi/agent/auth.json under the `commandcode` provider.
//
// Needs: npm i puppeteer-core (any recent version; drives system Chrome via CDP).
import { readFileSync, existsSync } from "node:fs";
import { homedir } from "node:os";
import puppeteer from "puppeteer-core";

const PAGE_URL = process.argv[2] || "http://127.0.0.1:8001/";
const WAV = new URL("fixture-turns.wav", import.meta.url).pathname;

function loadKey() {
  if (process.env.VOICE_SPIKE_KEY) return process.env.VOICE_SPIKE_KEY.trim();
  const p = homedir() + "/.pi/agent/auth.json";
  if (existsSync(p)) {
    const j = JSON.parse(readFileSync(p, "utf8"));
    const k = j?.commandcode?.key;
    if (k) return String(k).trim();
  }
  throw new Error("no key: set VOICE_SPIKE_KEY or ~/.pi/agent/auth.json commandcode.key");
}
const KEY = loadKey();

const CHROME = homedir() + "/.cache/ms-playwright/chromium-1254/chrome-linux64/chrome";
const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  protocolTimeout: 600000,
  args: [
    "--use-fake-device-for-media-stream",
    `--use-file-for-fake-audio-capture=${WAV}`,
    "--autoplay-policy=no-user-gesture-required",
    "--no-sandbox",
  ],
});
try {
  const page = await browser.newPage();
  await browser.defaultBrowserContext().overridePermissions(new URL(PAGE_URL).origin, ["microphone"]);
  page.on("console", (m) => { if (m.type() === "error") console.log("[page]", m.text().slice(0, 300)); });
  page.on("pageerror", (e) => console.log("[pageerror]", String(e).slice(0, 300)));
  await page.evaluateOnNewDocument((k) => localStorage.setItem("voice-tutor.key", k), KEY);
  const wantModel = process.env.VOICE_SPIKE_MODEL;
  if (wantModel) await page.evaluateOnNewDocument((m) => localStorage.setItem("voice-tutor.model", m), wantModel);
  await page.goto(PAGE_URL, { waitUntil: "load" });

  console.log("starting…");
  await page.click("#start");
  await page.waitForFunction(
    () => document.getElementById("status").textContent.startsWith("Listening"),
    { timeout: 240000, polling: 1000 });
  console.log("listening. waiting for 3 turns…");
  await page.waitForFunction(() => window.__spike?.turns.length >= 3, { timeout: 420000, polling: 1000 });

  const out = await page.evaluate(() => ({
    turns: window.__spike.turns,
    audioSamples: window.__spike.audioSamples,
    dl: document.getElementById("dlsummary").textContent,
    userTexts: [...document.querySelectorAll("#transcript .you .txt")].map((e) => e.textContent),
    tutorTexts: [...document.querySelectorAll("#transcript .tutor .txt")].map((e) => e.textContent),
  }));
  console.log(JSON.stringify(out, null, 1));

  const assert = (c, msg) => { if (!c) { console.error("FAIL:", msg); process.exitCode = 1; } };
  assert(out.turns.length >= 3, "3 turns recorded");
  for (const [i, t] of out.turns.slice(0, 3).entries()) {
    assert(t.sttMs > 0 && t.llmFirstMs > 0, `turn ${i + 1} has STT + LLM timings`);
    assert(t.totalMs > 0, `turn ${i + 1} has total (first audio played)`);
  }
  assert(out.userTexts.slice(0, 3).every((s) => s && s.length > 10 && !s.startsWith("(")), "user transcripts non-empty");
  assert(out.tutorTexts.slice(0, 3).every((s) => s && s.length > 10), "tutor replies non-empty");
  assert(out.audioSamples > 24000, "TTS audio actually played (>1s @24kHz)");
  console.log(process.exitCode ? "RESULT: FAIL" : "RESULT: PASS");
} finally {
  await browser.close();
}
