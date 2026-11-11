// Open Tutor browser-screen proof: tiny local server.
//
// Serves the built proof app (same origin) and forwards a tightly-bounded
// subset of OpenAI-compatible chat requests to the real inference endpoint.
// It NEVER persists transcripts, exercises, images, or uploads: request
// bodies are streamed to the upstream and never stored.
//
// Secrets: the real provider key is read server-side from the existing Pi
// auth file (~/.pi/agent/auth.json, opencode-go key). The page credential
// (PROOF_TOKEN) is operator-chosen and lives outside the repo
// (~/.config/open-tutor-proof/env). Neither is logged or committed.
import http from "node:http";
import https from "node:https";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const ROOT = process.env.PROOF_PUBLIC_DIR ?? path.resolve(here, "..", "public");
const PORT = Number(process.env.PROOF_PORT ?? "9773");
const PROOF_TOKEN = process.env.PROOF_TOKEN ?? "";
const UPSTREAM_HOST = "opencode.ai";
const UPSTREAM_PATH = "/inference/go/openai/v1/chat/completions";
// Upstream requires per-conversation routing via x-opencode-session (see
// https://opencode.ai/v2/docs/console/go). One stable id per proxy process
// is enough for this single-device proof; the browser never sees it.
const UPSTREAM_SESSION = crypto.randomUUID();

const ALLOWED_MODELS = new Set(["deepseek-v4.1-flash"]);
const MAX_BODY_BYTES = 2_500_000;
// Output cap per proxied request. Pi agents send the model's whole window
// (e.g. 384k) as max_tokens by default; the proxy clamps that down instead
// of rejecting, so the proof keeps working while one request stays cheap.
const MAX_TOKENS = 8192;
const MAX_MESSAGES = 40;
const MAX_TEXT_CHARS = 120_000;
const MAX_IMAGES = 3;
const MAX_IMAGE_BYTES = 1_200_000;
const RATE_LIMIT = 30; // requests per minute per IP
const UPSTREAM_TIMEOUT_MS = 120_000;

function fail(message) {
  console.error(`[proof-proxy] FATAL: ${message}`);
  process.exit(1);
}

function readProviderKey() {
  const authPath =
    process.env.PROOF_AUTH_FILE ?? path.join(process.env.HOME ?? "", ".pi", "agent", "auth.json");
  let raw;
  try {
    raw = fs.readFileSync(authPath, "utf8");
  } catch {
    fail(`cannot read Pi auth file at ${authPath}; refusing to start without provider credentials`);
  }
  try {
    const parsed = JSON.parse(raw);
    const key = parsed?.["opencode-go"]?.key;
    if (typeof key !== "string" || key.length < 8) fail("opencode-go key missing in Pi auth file");
    return key;
  } catch (err) {
    fail(`cannot parse Pi auth file: ${String(err)}`);
  }
}

if (!PROOF_TOKEN) fail("PROOF_TOKEN is not set; refusing to start without a page credential");

const PROVIDER_KEY = readProviderKey();

const SELF_ORIGINS = new Set(
  (process.env.PROOF_SELF_ORIGINS ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),
);

const hits = new Map(); // ip -> number[]
function rateLimited(ip) {
  const now = Date.now();
  const window = (hits.get(ip) ?? []).filter((t) => now - t < 60_000);
  if (window.length >= RATE_LIMIT) return true;
  window.push(now);
  hits.set(ip, window);
  return false;
}

function bearerOk(req, url) {
  const header = req.headers["authorization"] ?? req.headers["x-proof-token"];
  const presented = Array.isArray(header) ? header[0] : header;
  const token = typeof presented === "string" && presented.startsWith("Bearer ")
    ? presented.slice(7)
    : presented;
  if (typeof token !== "string" || token !== PROOF_TOKEN) return false;
  if (url.pathname.startsWith("/api/")) {
    const origin = req.headers["origin"];
    const referer = req.headers["referer"];
    const host = req.headers["host"];
    const candidates = [origin, referer].filter(Boolean);
    if (candidates.length === 0) return true; // same-origin fetch without Origin (e.g. worker)
    const sameHost = candidates.some((c) => {
      try {
        return new URL(c).host === host;
      } catch {
        return false;
      }
    });
    if (sameHost) return true;
    if (SELF_ORIGINS.size > 0 && candidates.some((c) => SELF_ORIGINS.has(originOf(c)))) return true;
    return false;
  }
  return true;
}

function originOf(value) {
  try {
    const u = new URL(value);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "";
  }
}

function approxImageBytes(dataUrl) {
  const comma = dataUrl.indexOf(",");
  const b64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
  return Math.floor(b64.length * 0.75);
}

function validateChatBody(body) {
  if (typeof body !== "object" || body === null) return "body must be a JSON object";
  if (!ALLOWED_MODELS.has(body.model)) return `model not allowed: ${String(body.model)}`;
  const cap = body.max_tokens ?? body.max_completion_tokens;
  if (cap !== undefined && !(Number.isInteger(cap) && cap > 0 && cap <= MAX_TOKENS)) {
    return `max_tokens out of bounds (1..${MAX_TOKENS})`;
  }
  const messages = body.messages;
  if (!Array.isArray(messages) || messages.length === 0 || messages.length > MAX_MESSAGES) {
    return `messages must be a non-empty array of at most ${MAX_MESSAGES}`;
  }
  let textChars = 0;
  let images = 0;
  for (const m of messages) {
    if (typeof m !== "object" || m === null) return "message must be an object";
    const content = m.content;
    if (typeof content === "string") {
      textChars += content.length;
    } else if (Array.isArray(content)) {
      for (const part of content) {
        if (typeof part !== "object" || part === null) return "content part must be an object";
        if (part.type === "text") textChars += String(part.text ?? "").length;
        else if (part.type === "image_url") {
          images += 1;
          const url = part.image_url?.url ?? "";
          if (typeof url !== "string" || !url.startsWith("data:image/")) {
            return "only inline data: images are allowed";
          }
          if (approxImageBytes(url) > MAX_IMAGE_BYTES) return "image too large";
        } else {
          return `content part type not allowed: ${String(part.type)}`;
        }
      }
    } else if (content === null || content === undefined) {
      // Assistant tool-call turns use content:null alongside tool_calls;
      // tool results carry tool_call_id. Neither carries countable text.
      if (!m.tool_calls && !m.tool_call_id) return "message content must be a string or array";
    } else {
      return "message content must be a string or array";
    }
    if (textChars > MAX_TEXT_CHARS) return "text payload too large";
    if (images > MAX_IMAGES) return "too many images";
  }
  const tools = body.tools;
  if (tools !== undefined && (!Array.isArray(tools) || tools.length > 8)) {
    return "at most 8 tools per request";
  }
  return null;
}

function readJsonBody(req, res, limit) {
  return new Promise((resolve) => {
    let size = 0;
    const chunks = [];
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > limit) {
        res.writeHead(413, { "content-type": "application/json" });
        res.end(JSON.stringify({ error: "payload too large" }));
        req.destroy();
        resolve(null);
      } else {
        chunks.push(chunk);
      }
    });
    req.on("end", () => {
      if (res.writableEnded) return resolve(null);
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        res.writeHead(400, { "content-type": "application/json" });
        res.end(JSON.stringify({ error: "invalid JSON" }));
        resolve(null);
      }
    });
    req.on("error", () => resolve(null));
  });
}

function forwardChat(body, res) {
  const payload = JSON.stringify(body);
  const upstream = https.request(
    {
      host: UPSTREAM_HOST,
      path: UPSTREAM_PATH,
      method: "POST",
      headers: {
        authorization: `Bearer ${PROVIDER_KEY}`,
        "content-type": "application/json",
        "content-length": Buffer.byteLength(payload),
        accept: "application/json, text/event-stream",
        "x-opencode-session": UPSTREAM_SESSION,
        "User-Agent": "open-tutor-proof/0.1.0 (pi-durable browser proof)",
      },
      timeout: UPSTREAM_TIMEOUT_MS,
    },
    (up) => {
      const status = up.statusCode ?? 502;
      if (status < 200 || status >= 300) {
        let tail = "";
        up.on("data", (c) => {
          if (tail.length < 2000) tail += c.toString("utf8");
        });
        up.on("end", () => {
          console.error(`[proof-proxy] upstream HTTP ${status}: ${tail.slice(0, 500)}`);
          res.writeHead(502, { "content-type": "application/json" });
          res.end(JSON.stringify({ error: `upstream error ${status}` }));
        });
        return;
      }
      res.writeHead(status, {
        "content-type": up.headers["content-type"] ?? "application/json",
        "cache-control": "no-store",
      });
      up.pipe(res);
    },
  );
  upstream.on("timeout", () => {
    upstream.destroy(new Error("upstream timeout"));
  });
  upstream.on("error", (err) => {
    console.error(`[proof-proxy] upstream failed: ${err.message}`);
    if (!res.writableEnded) {
      res.writeHead(502, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "upstream unavailable" }));
    }
  });
  upstream.end(payload);
}

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".map": "application/json; charset=utf-8",
};

function serveStatic(req, res, url) {
  let rel = decodeURIComponent(url.pathname);
  if (rel === "/") rel = "/index.html";
  const file = path.normalize(path.join(ROOT, rel));
  if (!file.startsWith(ROOT) || path.basename(file).startsWith(".")) {
    res.writeHead(403, { "content-type": "text/plain" });
    res.end("forbidden");
    return;
  }
  fs.readFile(file, (err, data) => {
    if (err) {
      fs.readFile(path.join(ROOT, "index.html"), (err2, fallback) => {
        if (err2 || !["/", "/index.html"].includes(url.pathname) && !url.pathname.startsWith("/assets/")) {
          res.writeHead(404, { "content-type": "text/plain" });
          res.end("not found");
          return;
        }
        if (err2) {
          res.writeHead(404, { "content-type": "text/plain" });
          res.end("not found");
          return;
        }
        res.writeHead(200, { "content-type": MIME[".html"], "cache-control": "no-store" });
        res.end(fallback);
      });
      return;
    }
    res.writeHead(200, {
      "content-type": MIME[path.extname(file)] ?? "application/octet-stream",
      "cache-control": "no-store",
    });
    res.end(data);
  });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://localhost");
  const ip = req.socket.remoteAddress ?? "unknown";
  if (url.pathname === "/api/health") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ok: true, service: "open-tutor-proof", time: Date.now() }));
    return;
  }
  if (url.pathname === "/api/proxy/openai/chat/completions") {
    if (req.method !== "POST") {
      res.writeHead(405, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "method not allowed" }));
      return;
    }
    if (rateLimited(ip)) {
      res.writeHead(429, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "rate limited, try again shortly" }));
      return;
    }
    if (!bearerOk(req, url)) {
      res.writeHead(401, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "unauthorized" }));
      return;
    }
    const body = await readJsonBody(req, res, MAX_BODY_BYTES);
    if (body === null) return;
    for (const field of ["max_tokens", "max_completion_tokens"]) {
      if (typeof body[field] === "number" && body[field] > MAX_TOKENS) {
        console.error(`[proof-proxy] clamped ${field} ${body[field]} to ${MAX_TOKENS}`);
        body[field] = MAX_TOKENS;
      }
    }
    const problem = validateChatBody(body);
    if (problem) {
      const shape = (() => {
        try {
          return `model=${body?.model} messages=${body?.messages?.length} tools=${body?.tools?.length ?? 0} stream=${body?.stream} max_tokens=${body?.max_tokens ?? body?.max_completion_tokens}`;
        } catch { return "unshaped"; }
      })();
      console.error(`[proof-proxy] rejected: ${problem} (${shape})`);
      res.writeHead(400, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: problem }));
      return;
    }
    forwardChat(body, res);
    return;
  }
  if (req.method === "GET" || req.method === "HEAD") {
    serveStatic(req, res, url);
    return;
  }
  res.writeHead(404, { "content-type": "text/plain" });
  res.end("not found");
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`[proof-proxy] serving ${ROOT} + proxy on 127.0.0.1:${PORT}`);
});
