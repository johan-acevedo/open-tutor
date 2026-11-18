/**
 * open-tutor-llm-bench — temporary global TTFT bake-off worker (delete after 2026-11-16).
 *
 * GET /<BENCH_PATH>/bench/<a|b|c>  (query ?backend= also accepted; else 404)
 *   a = Workers AI binding, @cf/deepseek-ai/deepseek-v4.1-flash-1017, reasoning_effort "none"
 *   b = Command Code Provider API, deepseek/deepseek-v4.1-flash, thinking disabled
 *   c = OpenCode Go, deepseek-v4.1-flash, thinking disabled (+ x-opencode-session)
 *
 * The Worker itself measures TTFT (first non-empty content delta) so the
 * Worker->backend leg is isolated from the probe->Worker leg. Probes read the
 * JSON body (server timings) and Globalping's timings.total (client side).
 *
 * Secrets (never in repo): BENCH_PATH, COMMAND_CODE_API_KEY and OPENCODE_API_KEY
 * are Worker secrets set at deploy time. Hard cap of 900 bench calls, then 429.
 */

const MODEL_A = "@cf/deepseek-ai/deepseek-v4.1-flash-1017";
const CC_URL = "https://api.commandcode.ai/provider/v1/chat/completions";
const MODEL_B = "deepseek/deepseek-v4.1-flash";
const GO_URL = "https://opencode.ai/zen/go/v1/chat/completions";
const MODEL_C = "deepseek-v4.1-flash";
const MAX_TOKENS = 400;
const MAX_REQUESTS = 900;

let count = 0;

// ~300-token tutor-style system prompt: the realistic prefill cost for voice.
const SYSTEM = `You are Roster, a friendly spoken-English tutor for Swedish teenagers aged 13 to 16. The student hears your reply through text-to-speech and answers by voice, so every reply must sound natural when read aloud. Keep replies short: two to four sentences, at most 60 words. Use simple everyday vocabulary at CEFR level A2 to B1 and avoid idioms the student has not learned yet.

Your job in each turn: react warmly to what the student just said, correct at most one mistake by modelling the right form inside your answer instead of lecturing about grammar, and then ask exactly one follow-up question that keeps the conversation going. Never ask two questions in one turn. Never use bullet points, headings, lists, emojis, or stage directions.

Today you are roleplaying ordering coffee in London. You play the barista. The student is the customer. Stay in character the whole time. If the student switches to Swedish, answer in English anyway but weave in a quick translation of their Swedish words so they learn. If the student says something you do not understand, ask them to say it another way instead of guessing. Praise effort concretely before each correction, for example by naming the word they got right.`;

const USER_TURN = `Hi! My name is Elin and I want to practise ordering coffee in London. Can I have a latte, please?`;

async function readSSE(stream, t0) {
  const reader = stream.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let ttftContent = null;
  let ttftReason = null;
  let content = "";
  let reasonChars = 0;
  let chunks = 0;
  let usage = null;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split("\n");
    buf = parts.pop();
    for (const line of parts) {
      const t = line.trim();
      if (!t.startsWith("data:")) continue;
      const payload = t.slice(5).trim();
      if (payload === "[DONE]") continue;
      let ev;
      try {
        ev = JSON.parse(payload);
      } catch {
        continue;
      }
      if (ev.usage) usage = ev.usage;
      const delta = ev.choices && ev.choices[0] && ev.choices[0].delta;
      if (!delta) continue;
      const now = Date.now();
      const c = delta.content;
      if (typeof c === "string" && c.length > 0) {
        if (ttftContent === null) ttftContent = now - t0;
        content += c;
        chunks++;
      }
      for (const k of ["reasoning", "reasoning_content", "thinking"]) {
        const r = delta[k];
        if (typeof r === "string" && r.length > 0) {
          if (ttftReason === null) ttftReason = now - t0;
          reasonChars += r.length;
        }
      }
    }
  }
  return { ttftContent, ttftReason, content, reasonChars, chunks, usage };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const seg = url.pathname.split("/").filter(Boolean);
    if (seg.length < 2 || seg.length > 3 || seg[1] !== "bench" || seg[0] !== env.BENCH_PATH) {
      return new Response("not found", { status: 404 });
    }
    if (request.method !== "GET") {
      return new Response("method not allowed", { status: 405 });
    }
    if (++count > MAX_REQUESTS) {
      return Response.json({ error: "budget exhausted" }, { status: 429 });
    }
    // Path segment wins (some probes percent-encode "?"), query is the fallback.
    const backend = seg[2] || url.searchParams.get("backend");
    if (backend !== "a" && backend !== "b" && backend !== "c") {
      return Response.json({ error: "use /bench/a|b|c" }, { status: 400 });
    }
    const messages = [
      { role: "system", content: SYSTEM },
      { role: "user", content: USER_TURN },
    ];
    const t0 = Date.now();
    let m;
    if (backend === "a") {
      const s = await env.AI.run(MODEL_A, {
        messages,
        max_tokens: MAX_TOKENS,
        stream: true,
        reasoning_effort: "none", // thinking off; "minimal" is an alias
      });
      const body = s instanceof Response ? s.body : s;
      m = await readSSE(body, t0);
    } else if (backend === "b") {
      const r = await fetch(CC_URL, {
        method: "POST",
        headers: {
          Authorization: "Bearer " + env.COMMAND_CODE_API_KEY,
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          "User-Agent": "open-tutor-bench/0.1", // CC returns 403 to default UAs
        },
        body: JSON.stringify({
          model: MODEL_B,
          messages,
          max_tokens: MAX_TOKENS,
          stream: true,
          thinking: { type: "disabled" },
          stream_options: { include_usage: true },
        }),
      });
      if (!r.ok || !r.body) {
        return Response.json({ error: "upstream " + r.status }, { status: 502 });
      }
      m = await readSSE(r.body, t0);
    } else {
      const r = await fetch(GO_URL, {
        method: "POST",
        headers: {
          Authorization: "Bearer " + env.OPENCODE_API_KEY,
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          "User-Agent": "open-tutor-bench/0.1",
          "x-opencode-session": crypto.randomUUID(), // one per conversation
        },
        body: JSON.stringify({
          model: MODEL_C,
          messages,
          max_tokens: MAX_TOKENS,
          stream: true,
          thinking: { type: "disabled" },
          stream_options: { include_usage: true },
        }),
      });
      if (!r.ok || !r.body) {
        return Response.json({ error: "upstream " + r.status }, { status: 502 });
      }
      m = await readSSE(r.body, t0);
    }
    const total = Date.now() - t0;
    return Response.json({
      backend,
      colo: (request.cf && request.cf.colo) || null,
      country: (request.cf && request.cf.country) || null,
      ttft_ms: m.ttftContent,
      ttft_reasoning_ms: m.ttftReason,
      total_ms: total,
      content_chars: m.content.length,
      content_chunks: m.chunks,
      reasoning_chars: m.reasonChars,
      usage: m.usage,
      first60: m.content.slice(0, 60),
      model: backend === "a" ? MODEL_A : backend === "b" ? MODEL_B : MODEL_C,
    });
  },
};
