// Voice tutor spike: VAD -> Whistle STT -> Muse Spark LLM -> mesm-tts, all local except the LLM call.
import { createPlayer } from "./vendor/tts/player.mjs";

const $ = (id) => document.getElementById(id);
const API_CHAT = "https://api.commandcode.ai/provider/v1/chat/completions";
const API_RESP = "https://api.commandcode.ai/provider/v1/responses";
const MODELS = {
  spark: { label: "Muse Spark 1.3", api: "responses", model: "meta/muse-spark-1.3-contributor" },
  deepseek: { label: "DeepSeek V4.1 Flash", api: "chat", model: "deepseek/deepseek-v4.1-flash" },
};
const SYSTEM = "You are a friendly English tutor. Keep every reply to 1-3 short sentences. " +
  "Use only common English words. Reply in English.";

const S = {
  vad: null, stt: null, tts: null, player: null, ctx: null, resample: false,
  running: false, state: "idle", turnId: 0, turn: null, pendingAudio: null, llmAbort: null, dl: new Map(),
  history: [], // {role, content}
};
// Test hook: window.__spike = { state, turns: [...] }
window.__spike = { turns: [], audioSamples: 0, get state() { return S.state; } };

function log(who, cls) {
  const d = document.createElement("div");
  d.className = "u " + cls;
  d.innerHTML = `<span class="who">${who}:</span> <span class="txt"></span>`;
  $("transcript").appendChild(d);
  $("transcript").scrollTop = $("transcript").scrollHeight;
  return d.querySelector(".txt");
}
function status(t) { $("status").textContent = t; }
function loadmsg(t) { const el = $("loadbar"); el.hidden = !t; if (t) el.textContent = t; }

// Split streamed LLM text into complete sentences (simple; tutor replies are short).
// Only splits at real boundaries (terminal punctuation + space + capital/digit);
// the unpunctuated tail stays in `rest` until the LLM finishes.
function takeSentences(buf) {
  const out = [];
  const re = /(.+?[.!?…]["”'’)\]]*?)\s+(?=[A-Z"“(\d])/g;
  let m, last = 0;
  while ((m = re.exec(buf))) {
    if (m[1].trim().length < 2) continue;
    out.push(m[1].trim());
    last = m.index + m[0].length;
  }
  return { sentences: out, rest: buf.slice(last) };
}

function addTimingRow(t) {
  const tb = $("timing").querySelector("tbody");
  const tr = document.createElement("tr");
  const ms = (v) => (v == null ? "—" : Math.round(v));
  tr.innerHTML = `<td>${t.id}</td><td>${t.model || "—"}</td><td class="num">${ms(t.sttMs)}</td>` +
    `<td class="num">${ms(t.llmFirstMs)}</td><td class="num">${ms(t.audioFirstMs)}</td>` +
    `<td class="num">${ms(t.totalMs)}</td><td>${t.note || ""}</td>`;
  tb.appendChild(tr);
}

function refreshDownloads() {
  const rows = performance.getEntriesByType("resource")
    .filter((e) => e.name.startsWith(location.origin));
  for (const e of rows) {
    const p = new URL(e.name).pathname;
    const prev = S.dl.get(p) || { wire: 0, full: 0 };
    // transferSize is 0 when served from cache (SW/HTTP) — that IS the wire truth.
    prev.wire = Math.max(prev.wire, e.transferSize || 0);
    prev.full = Math.max(prev.full, e.decodedBodySize || e.encodedBodySize || 0);
    S.dl.set(p, prev);
  }
  const tb = $("downloads").querySelector("tbody");
  tb.innerHTML = "";
  let wire = 0, full = 0;
  for (const [p, b] of [...S.dl.entries()].sort()) {
    wire += b.wire; full += b.full;
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><code>${p}</code></td><td class="num">${(b.wire / 1048576).toFixed(2)} MB</td>`;
    tb.appendChild(tr);
  }
  $("dlsummary").textContent = `On the wire this visit: ${(wire / 1048576).toFixed(1)} MB ` +
    `(${(full / 1048576).toFixed(1)} MB decoded) across ${S.dl.size} same-origin assets. ` +
    `Reload: service worker serves vendor/ from cache (~0 bytes).`;
}

function mergeWorkerBytes(list) {
  for (const [path, n] of list) {
    const prev = S.dl.get(path) || { wire: 0, full: 0 };
    prev.wire = Math.max(prev.wire, n);
    prev.full = Math.max(prev.full, n);
    S.dl.set(path, prev);
  }
}

function resample24kToCtx(x) {
  const to = S.ctx.sampleRate, out = new Float32Array(Math.round(x.length * to / 24000));
  for (let i = 0; i < out.length; i++) {
    const p = i * 24000 / to, i0 = Math.floor(p), f = p - i0;
    out[i] = x[i0] * (1 - f) + (x[Math.min(i0 + 1, x.length - 1)] * f);
  }
  return out;
}

function workerCall(worker, match, post, transfer) {
  return new Promise((resolve, reject) => {
    const h = ({ data: m }) => {
      if (match(m)) { worker.removeEventListener("message", h); resolve(m); }
      else if (m.op === "error" && (m.turnId === undefined || (post.turnId !== undefined && m.turnId === post.turnId))) {
        worker.removeEventListener("message", h); reject(new Error(m.message));
      }
    };
    worker.addEventListener("message", h);
    worker.postMessage(post, transfer || []);
  });
}

async function boot() {
  const key = $("key").value.trim();
  if (!key) { status("Paste your Command Code key first."); return; }
  localStorage.setItem("voice-tutor.key", key);
  $("start").disabled = true;
  try {
    loadmsg("Audio…");
    S.ctx = new AudioContext({ sampleRate: 24000, latencyHint: "interactive" });
    S.resample = S.ctx.sampleRate !== 24000;
    await S.ctx.resume();
    S.player = await createPlayer(S.ctx);
    S.player.onstart = () => {
      const t = S.turn;
      if (t && t.tFirstAudio == null) {
        t.tFirstAudio = performance.now();
        t.audioFirstMs = t.tFirstAudio - t.tFirstToken;
        t.totalMs = t.tFirstAudio - t.tEos;
      }
    };
    S.player.onfinish = (info) => {
      window.__spike.audioSamples += info.played || 0;
      const t = S.turn;
      if (t && !t.done) { t.done = true; finishTurn(t, ""); }
    };

    loadmsg("Speech recognizer (16.9 MB)…");
    S.stt = new Worker("stt-worker.js");
    mergeWorkerBytes((await workerCall(S.stt, (m) => m.op === "loaded", { op: "load" })).bytes || []);
    routeStt();

    loadmsg("Voice (mesm-tts)…");
    S.tts = new Worker("tts-worker.js", { type: "module" });
    mergeWorkerBytes((await workerCall(S.tts, (m) => m.op === "loaded", { op: "load" })).bytes || []);
    routeTts();

    loadmsg("Voice activity detection…");
    S.vad = await vad.MicVAD.new({
      model: "v5",
      baseAssetPath: new URL("vendor/vad/", location.href).href,
      onnxWASMBasePath: new URL("vendor/ort/", location.href).href,
      minSpeechMs: 250,
      onSpeechStart: onSpeechStart,
      onSpeechEnd: onSpeechEnd,
      getStream: () => navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, autoGainControl: true, noiseSuppression: true },
      }),
    });
    S.running = true;
    S.state = "listening";
    $("stop").disabled = false;
    loadmsg(null);
    status("Listening — talk to your tutor.");
    refreshDownloads();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  } catch (e) {
    console.error(e);
    status("Start failed: " + (e?.message || e));
    $("start").disabled = false;
  }
}

function onSpeechStart() {
  if (!S.running) return;
  // Barge-in only while the tutor is audibly speaking; speech that starts while
  // we are still thinking is queued (its onSpeechEnd arrives later).
  if (S.state === "speaking") bargeIn();
  else S.state = "user-speaking";
}

function onSpeechEnd(audio) {
  if (!S.running) return;
  if (audio.length < 0.35 * 16000) return; // too short: noise/misfire
  if (S.turn) { S.pendingAudio = audio; return; } // finish current turn first
  startTurn(audio);
}

function bargeIn() {
  const t = S.turn;
  try { S.llmAbort?.abort(); } catch {}
  if (t) { S.tts?.postMessage({ op: "stop", turnId: t.id }); }
  S.player?.reset();
  if (t && !t.done) {
    t.done = true; t.interrupted = true;
    window.__spike.turns.push({ id: t.id, model: t.model || "—", note: "barged-in, abandoned" });
    addTimingRow({ id: t.id, model: t.model || "—", note: "barged-in, abandoned" });
  }
  S.turn = null;
  S.pendingAudio = null;
  S.state = "listening";
  status("Interrupted — listening.");
}

async function startTurn(audio) {
  if (S.turn) return; // already handling one (barge-in clears it)
  const id = ++S.turnId;
  const t = S.turn = {
    id, tEos: performance.now(), tTranscript: null, tFirstToken: null, tFirstAudio: null,
    sttMs: null, llmFirstMs: null, audioFirstMs: null, totalMs: null,
    pending: 0, llmDone: false, done: false, sentIdx: 0, buf: "", tutorEl: null,
  };
  S.state = "thinking";
  status("Hearing you…");
  t.userEl = log("You", "you");
  t.userEl.textContent = "…";
  try {
    const m = await workerCall(S.stt, (x) => x.op === "transcript" && x.turnId === id,
      { op: "transcribe", turnId: id, audio }, [audio.buffer]);
    if (!S.turn || S.turn.id !== id) return; // barged-in meanwhile
    t.tTranscript = performance.now();
    t.sttMs = m.ms;
    const text = m.text.trim();
    t.userEl.textContent = text || "(nothing heard)";
    if (!text) { t.done = true; S.turn = null; S.state = "listening"; status("Listening."); maybeNext(); return; }
    status("Thinking…");
    await runLlm(t, text);
  } catch (e) {
    console.error(e);
    if (S.turn?.id === id) {
      t.userEl.textContent += ` [STT error: ${e.message}]`;
      t.done = true; S.turn = null; S.state = "listening"; status("Listening."); maybeNext();
    }
  }
}

async function runLlm(t, text) {
  const key = localStorage.getItem("voice-tutor.key");
  const sel = localStorage.getItem("voice-tutor.model") || "spark";
  const M = MODELS[sel] || MODELS.spark;
  t.model = M.label;
  S.history.push({ role: "user", content: text });
  t.tutorEl = log("Tutor", "tutor");
  S.llmAbort = new AbortController();
  let url, body;
  if (M.api === "responses") {
    url = API_RESP;
    body = {
      model: M.model, stream: true, reasoning: { effort: "minimal" }, max_output_tokens: 400,
      instructions: SYSTEM, input: S.history.slice(-6),
    };
  } else {
    url = API_CHAT;
    body = {
      model: M.model, stream: true, thinking: { type: "disabled" }, max_tokens: 400,
      messages: [{ role: "system", content: SYSTEM }, ...S.history.slice(-6)],
    };
  }
  let resp;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": "Bearer " + key },
      body: JSON.stringify(body),
      signal: S.llmAbort.signal,
    });
  } catch (e) {
    if (e.name === "AbortError") return; // barge-in
    throw new Error("LLM request failed: " + e.message);
  }
  if (!resp.ok) throw new Error(`LLM HTTP ${resp.status}: ${(await resp.text()).slice(0, 200)}`);
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let acc = "", reply = "", leftover = "";
  // Parses both SSE shapes: chat completions (bare `data:` chunks + [DONE])
  // and Responses (`event:` + `data:`, text in response.output_text.delta).
  const handleText = (d) => {
    if (t.tFirstToken == null) {
      t.tFirstToken = performance.now();
      t.llmFirstMs = t.tFirstToken - t.tTranscript;
    }
    reply += d; acc += d;
    t.tutorEl.textContent = reply;
    const { sentences, rest } = takeSentences(acc);
    acc = rest;
    for (const snt of sentences) queueSentence(t, snt);
  };
  const pump = async () => {
    const { done, value } = await reader.read();
    if (done) return false;
    leftover += dec.decode(value, { stream: true });
    const blocks = leftover.split("\n\n");
    leftover = blocks.pop();
    for (const b of blocks) {
      let ev = "", data = "";
      for (const line of b.split("\n")) {
        const s = line.trim();
        if (s.startsWith("event:")) ev = s.slice(6).trim();
        else if (s.startsWith("data:")) data += s.slice(5).trim();
      }
      if (!data) continue;
      if (data === "[DONE]" || ev === "response.completed") return false;
      try {
        const j = JSON.parse(data);
        if (j.type === "response.output_text.delta" && j.delta) handleText(j.delta);
        else if (j.choices) {
          const d = j.choices[0]?.delta?.content || "";
          if (d) handleText(d);
        }
      } catch {}
    }
    return true;
  };
  try {
    while (await pump()) { if (S.turn?.id !== t.id) return; } // eslint-disable-line
  } catch (e) {
    if (e.name === "AbortError" || S.llmAbort.signal.aborted) return;
    throw e;
  }
  if (S.turn?.id !== t.id) return; // barged-in
  if (acc.trim()) queueSentence(t, acc.trim());
  t.llmDone = true;
  t.reply = reply;
  S.history.push({ role: "assistant", content: reply });
  status(reply ? "Speaking…" : "Listening.");
  S.state = reply ? "speaking" : "listening";
  if (!reply) { finishTurn(t, "empty reply"); return; }
  checkTurnEnd(t);
}

function maybeNext() {
  const next = S.pendingAudio;
  S.pendingAudio = null;
  if (next && S.running && !S.turn) startTurn(next);
}

function queueSentence(t, text) {
  if (!text || S.turn?.id !== t.id) return;
  t.pending++;
  S.tts.postMessage({ op: "synth", turnId: t.id, i: t.sentIdx++, text });
}

function checkTurnEnd(t) {
  if (t.llmDone && t.pending === 0 && !t.done) {
    if (!t.audioPushed) { t.done = true; finishTurn(t, "no audio"); return; } // worklet never fires onfinish on an empty queue
    S.player.end(); // drain queue, onfinish -> finishTurn
  }
}

function finishTurn(t, note) {
  if (S.turn?.id !== t.id) return;
  S.turn = null;
  S.state = "listening";
  status("Listening — talk to your tutor.");
  const row = {
    id: t.id, model: t.model || "—", sttMs: t.sttMs, llmFirstMs: t.llmFirstMs,
    audioFirstMs: t.audioFirstMs, totalMs: t.totalMs, note: note || (t.reply ? "" : "no audio"),
  };
  window.__spike.turns.push(row);
  addTimingRow(row);
  refreshDownloads();
  const next = S.pendingAudio;
  S.pendingAudio = null;
  if (next && S.running) startTurn(next);
}

function routeStt() {
  // transcripts are matched via workerCall promises; stray errors surface here.
  S.stt.addEventListener("message", ({ data: m }) => {
    if (m.op === "error" && m.turnId === undefined) { status("STT error: " + m.message); }
  });
}

function routeTts() {
  S.tts.addEventListener("message", ({ data: m }) => {
    const t = S.turn;
    if (!t || m.turnId !== t.id) return; // stale turn
    if (m.op === "chunk") {
      let s = m.samples;
      if (S.resample) s = resample24kToCtx(s);
      t.audioPushed = true;
      S.player.push(s);
      $("transcript").scrollTop = $("transcript").scrollHeight;
    } else if (m.op === "sentDone" || m.op === "sentError") {
      if (m.bytes) mergeWorkerBytes(m.bytes);
      if (m.op === "sentError" && t.tutorEl) t.tutorEl.textContent += ` ⚠️(voice skipped a sentence: ${m.message.slice(0, 80)})`;
      t.pending = Math.max(0, t.pending - 1);
      checkTurnEnd(t);
    }
  });
}

const NOTICES = {
  spark: "Conversations are processed by Meta's Muse Spark model, and Meta may use them to train its AI. Don't share personal details.",
  deepseek: "Conversations are processed by DeepSeek's V4.1 Flash model, which may use them to train its AI. Don't share personal details.",
};
function applyModelNotice() {
  const sel = $("model").value;
  $("ainotice").innerHTML = "<strong>Notice:</strong> " + NOTICES[sel];
}
$("model").value = localStorage.getItem("voice-tutor.model") || "spark";
applyModelNotice();
$("model").onchange = () => { localStorage.setItem("voice-tutor.model", $("model").value); applyModelNotice(); };
$("key").value = localStorage.getItem("voice-tutor.key") || "";
$("start").onclick = boot;
$("stop").onclick = async () => {
  S.running = false;
  try { S.llmAbort?.abort(); } catch {}
  try { await S.vad?.pause(); } catch {}
  S.player?.reset();
  S.turn = null; S.state = "idle";
  $("start").disabled = false; $("stop").disabled = true;
  status("Stopped.");
};
