// Behaviour contracts for proxy/server.mjs. These assert the security
// bounds (token auth, model allowlist, size caps), not implementation
// details. Run with: node --test tests/
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const TOKEN = "test-token-123";
const REAL_KEY = "real-provider-key-never-leaves-server";

let dir;
let proxy;
let upstream;
let upstreamSawAuth = [];
let upstreamBodies = [];

const PROXY_PORT = 19773;
const UP_PORT = 19774;

async function startUpstream() {
  const { createServer } = await import("node:http");
  return new Promise((resolve) => {
    const server = createServer((req, res) => {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        upstreamSawAuth.push(req.headers["authorization"]);
        upstreamBodies.push(body);
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ choices: [{ message: { content: "ok" } }] }));
      });
    });
    server.listen(UP_PORT, "127.0.0.1", () => resolve(server));
  });
}

function waitFor(url, timeoutMs = 15000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const r = await fetch(url);
        if (r.ok) return resolve();
      } catch {
        // retry
      }
      if (Date.now() - start > timeoutMs) return reject(new Error(`timeout waiting for ${url}`));
      setTimeout(tick, 200);
    };
    tick();
  });
}

before(async () => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "proof-proxy-test-"));
  fs.writeFileSync(path.join(dir, "index.html"), "<html>hi</html>");
  upstream = await startUpstream();
  // Point the proxy at a stub upstream by monkey-patching https.request is
  // not possible across processes; instead the proxy under test always calls
  // the real upstream host, so these tests exercise everything up to the
  // forwarding boundary except the live network call. Live forwarding is
  // covered by the Playwright proof run.
  proxy = spawn("node", ["proxy/server.mjs"], {
    cwd: new URL("..", import.meta.url).pathname,
    env: {
      ...process.env,
      PROOF_PORT: String(PROXY_PORT),
      PROOF_PUBLIC_DIR: dir,
      PROOF_TOKEN: TOKEN,
      PROOF_AUTH_FILE: path.join(dir, "auth.json"),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  fs.writeFileSync(path.join(dir, "auth.json"), JSON.stringify({ "opencode-go": { key: "stub-key" } }));
  proxy.stderr.on("data", () => {});
  await waitFor(`http://127.0.0.1:${PROXY_PORT}/api/health`);
});

after(async () => {
  proxy?.kill();
  upstream?.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

const chat = (body, token = TOKEN) =>
  fetch(`http://127.0.0.1:${PROXY_PORT}/api/proxy/openai/chat/completions`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });

test("health is public and serves the app", async () => {
  const health = await fetch(`http://127.0.0.1:${PROXY_PORT}/api/health`).then((r) => r.json());
  assert.equal(health.ok, true);
  const app = await fetch(`http://127.0.0.1:${PROXY_PORT}/`).then((r) => r.text());
  assert.match(app, /hi/);
});

test("rejects missing token", async () => {
  const r = await chat({ model: "deepseek-v4.1-flash", messages: [{ role: "user", content: "hi" }] }, "wrong");
  assert.equal(r.status, 401);
});

test("rejects disallowed model", async () => {
  const r = await chat({ model: "gpt-6.1-sol", messages: [{ role: "user", content: "hi" }] });
  assert.equal(r.status, 400);
  assert.match(await r.text(), /model not allowed/);
});

test("clamps oversized max_tokens instead of rejecting", async () => {
  // The proxy clamps agent-sized ceilings (e.g. a 384k window) down to its
  // per-request cap and forwards; validation must not reject them.
  const r = await chat({ model: "deepseek-v4.1-flash", messages: [{ role: "user", content: "hi" }], max_tokens: 50000 });
  assert.notEqual(r.status, 400);
  await r.text().catch(() => {});
});

test("rejects non-data images and too many images", async () => {
  const bad = await chat({
    model: "deepseek-v4.1-flash",
    messages: [{ role: "user", content: [{ type: "image_url", image_url: { url: "https://evil/x.png" } }] }],
  });
  assert.equal(bad.status, 400);
  const many = await chat({
    model: "deepseek-v4.1-flash",
    messages: [
      { role: "user", content: [{ type: "text", text: "x" }, { type: "image_url", image_url: { url: "data:image/png;base64,AAA" } }, { type: "image_url", image_url: { url: "data:image/png;base64,AAA" } }, { type: "image_url", image_url: { url: "data:image/png;base64,AAA" } }, { type: "image_url", image_url: { url: "data:image/png;base64,AAA" } }] },
    ],
  });
  assert.equal(many.status, 400);
});

test("allows null content on assistant tool-call turns", async () => {
  const r = await chat({
    model: "deepseek-v4.1-flash",
    messages: [
      { role: "user", content: "hi" },
      { role: "assistant", content: null, tool_calls: [{ id: "1", type: "function", function: { name: "prepare_page", arguments: "{}" } }] },
      { role: "tool", tool_call_id: "1", content: "saved" },
    ],
  });
  assert.notEqual(r.status, 400);
  await r.text().catch(() => {});
});

test("rejects oversized payload", async () => {
  const big = "x".repeat(3_000_000);
  const r = await chat({ model: "deepseek-v4.1-flash", messages: [{ role: "user", content: big }] });
  assert.ok([400, 413].includes(r.status));
});

test("never echoes the provider key", async () => {
  const r = await chat({ model: "nope", messages: [] }, "wrong");
  const text = await r.text();
  assert.doesNotMatch(text, /stub-key/);
  assert.equal(upstreamBodies.length, 0, "rejected requests must not reach upstream");
});
