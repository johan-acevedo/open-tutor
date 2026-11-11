// Page thread: owns pixels and inputs. The Durable conversation lives in
// the worker; this side renders the shared canvas board and sends the very
// same pixels back as PNG for the live vision check.
import "./style.css";
import type { DeckSnapshot, MainToWorker, WorkerToMain, DeckPage } from "./protocol.ts";

const BOARD_W = 900;
const BOARD_H = 640;

const els = {
  gate: document.getElementById("gate")!,
  token: document.getElementById("token") as HTMLInputElement,
  open: document.getElementById("open") as HTMLButtonElement,
  gateError: document.getElementById("gate-error")!,
  app: document.getElementById("app")!,
  conv: document.getElementById("conv")!,
  owner: document.getElementById("owner")!,
  status: document.getElementById("status")!,
  canvas: document.getElementById("board") as HTMLCanvasElement,
  prev: document.getElementById("prev") as HTMLButtonElement,
  next: document.getElementById("next") as HTMLButtonElement,
  pageLabel: document.getElementById("page-label")!,
  topic: document.getElementById("topic") as HTMLInputElement,
  level: document.getElementById("level") as HTMLSelectElement,
  prepare: document.getElementById("prepare") as HTMLButtonElement,
  answer: document.getElementById("answer") as HTMLTextAreaElement,
  foxCmd: document.getElementById("fox-cmd") as HTMLInputElement,
  foxGo: document.getElementById("fox-go") as HTMLButtonElement,
  observe: document.getElementById("observe") as HTMLButtonElement,
  foxBubble: document.getElementById("fox-bubble")!,
  observed: document.getElementById("observed")!,
};

let worker: Worker | null = null;
let snapshot: DeckSnapshot | null = null;
let busy = false;
let lastBoxPageId: string | null = null;
let inputTimer: number | undefined;

const canvasCtx = els.canvas.getContext("2d")!;
els.canvas.width = BOARD_W;
els.canvas.height = BOARD_H;

function currentPage(): DeckPage | undefined {
  if (!snapshot || snapshot.pages.length === 0) return undefined;
  return snapshot.pages[snapshot.current];
}

function wrapText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    const probe = line ? `${line} ${word}` : word;
    if (ctx.measureText(probe).width > maxWidth && line) {
      lines.push(line);
      line = word;
    } else {
      line = probe;
    }
  }
  if (line) lines.push(line);
  return lines.slice(0, 12);
}

function drawBoard(page: DeckPage | undefined, total: number, index: number) {
  const ctx = canvasCtx;
  ctx.fillStyle = "#fdfbf4";
  ctx.fillRect(0, 0, BOARD_W, BOARD_H);
  ctx.strokeStyle = "#2b2b2b";
  ctx.lineWidth = 6;
  ctx.strokeRect(8, 8, BOARD_W - 16, BOARD_H - 16);

  ctx.fillStyle = "#1c1c1c";
  ctx.font = "bold 30px system-ui, sans-serif";
  ctx.fillText(`Sida ${total === 0 ? 0 : index + 1} av ${total}`, 40, 62);

  ctx.font = "22px system-ui, sans-serif";
  ctx.fillStyle = "#555";
  ctx.fillText("Open Tutor · webbläsarägd skärm (proof)", 40, 96);

  if (!page) {
    ctx.fillStyle = "#1c1c1c";
    ctx.font = "26px system-ui, sans-serif";
    ctx.fillText("Ingen sida ännu. Förbered en övning nedan.", 40, 180);
    return;
  }

  let y = 150;
  ctx.fillStyle = "#0b5fa5";
  ctx.font = "bold 24px system-ui, sans-serif";
  ctx.fillText(`Ämne: ${page.topic}`, 40, y);
  y += 16;
  ctx.strokeStyle = "#0b5fa5";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(40, y);
  ctx.lineTo(BOARD_W - 40, y);
  ctx.stroke();
  y += 52;

  ctx.fillStyle = "#1c1c1c";
  ctx.font = "30px system-ui, sans-serif";
  for (const line of wrapText(ctx, page.question, BOARD_W - 120)) {
    ctx.fillText(line, 40, y);
    y += 42;
  }
  y += 18;

  ctx.fillStyle = "#333";
  ctx.font = "22px system-ui, sans-serif";
  ctx.fillText("Ditt svar:", 40, y);
  y += 12;
  ctx.strokeStyle = "#888";
  ctx.lineWidth = 2;
  const boxTop = y;
  const boxH = 150;
  ctx.strokeRect(40, boxTop, BOARD_W - 80, boxH);
  ctx.fillStyle = "#1c1c1c";
  ctx.font = "28px system-ui, sans-serif";
  const inputLines = page.input ? wrapText(ctx, page.input, BOARD_W - 140) : ["…"];
  let iy = boxTop + 44;
  ctx.fillStyle = page.input ? "#1c1c1c" : "#aaa";
  for (const line of inputLines.slice(0, 3)) {
    ctx.fillText(line, 60, iy);
    iy += 40;
  }
  y = boxTop + boxH + 46;

  ctx.fillStyle = "#333";
  ctx.font = "22px system-ui, sans-serif";
  ctx.fillText("Facit:", 40, y);
  y += 44;
  if (page.revealed) {
    ctx.fillStyle = "#0a6b2d";
    ctx.font = "bold 30px system-ui, sans-serif";
    for (const line of wrapText(ctx, page.solution, BOARD_W - 120)) {
      ctx.fillText(line, 40, y);
      y += 42;
    }
  } else {
    ctx.fillStyle = "#999";
    ctx.font = "28px system-ui, sans-serif";
    ctx.fillText("··· dolt ···", 40, y);
    y += 42;
  }

  ctx.fillStyle = "#777";
  ctx.font = "18px system-ui, sans-serif";
  ctx.fillText(`${page.id} · ${page.revision}`, 40, BOARD_H - 28);
}

function render() {
  const page = currentPage();
  drawBoard(page, snapshot?.pages.length ?? 0, snapshot?.current ?? 0);
  els.pageLabel.textContent =
    snapshot && snapshot.pages.length > 0
      ? `Sida ${snapshot.current + 1} av ${snapshot.pages.length}`
      : "Ingen sida";
  els.prev.disabled = busy || !snapshot || snapshot.current <= 0;
  els.next.disabled = busy || !snapshot || snapshot.current >= snapshot.pages.length - 1;
  const editable = !!snapshot && !snapshot.readOnly && !busy;
  els.prepare.disabled = !editable;
  els.foxGo.disabled = !editable;
  els.observe.disabled = !editable;
  // When the visible page changes, the box must follow even mid-typing:
  // otherwise it keeps showing the previous page's text while focused.
  if (page?.id !== lastBoxPageId || document.activeElement !== els.answer) {
    els.answer.value = page?.input ?? "";
    lastBoxPageId = page?.id ?? null;
  }
  els.answer.disabled = !snapshot || snapshot.readOnly || busy || !page;
  els.owner.textContent = snapshot?.readOnly ? "skrivskyddad (annan flik äger)" : "ägare: denna flik";
  if (snapshot) {
    els.conv.textContent = `samtal ${snapshot.conversationId}`;
  }
}

function send(msg: MainToWorker) {
  worker?.postMessage(msg);
}

// Test seam for the repeatable Playwright proof run (read-only state,
// plus a raw channel so the script can send e.g. stale fox commands).
(window as unknown as { __proof: unknown }).__proof = {
  get snapshot() {
    return snapshot;
  },
  send(msg: MainToWorker) {
    send(msg);
  },
};

function setStatus(busyState: boolean, text: string) {
  busy = busyState;
  els.status.textContent = text;
  render();
}

function onWorkerMessage(e: MessageEvent<WorkerToMain>) {
  const msg = e.data;
  switch (msg.kind) {
    case "ready":
    case "deck":
      snapshot = msg.snapshot;
      render();
      break;
    case "status":
      setStatus(msg.busy, msg.text);
      break;
    case "fox":
      els.foxBubble.textContent = `🦊 Räven: ${msg.text}`;
      break;
    case "observed":
      els.observed.textContent = `🦊 Räven ser: ${msg.text}`;
      break;
    case "error":
      setStatus(false, `Fel: ${msg.message}`);
      break;
  }
}

function snapshotPng(): Promise<string> {
  return new Promise((resolve, reject) => {
    els.canvas.toBlob((blob) => {
      if (!blob) return reject(new Error("canvas snapshot failed"));
      const reader = new FileReader();
      reader.onload = () => {
        const url = String(reader.result ?? "");
        resolve(url.slice(url.indexOf(",") + 1));
      };
      reader.onerror = () => reject(new Error("png encode failed"));
      reader.readAsDataURL(blob);
    }, "image/png");
  });
}

els.open.addEventListener("click", () => {
  const token = els.token.value.trim();
  if (!token) {
    els.gateError.textContent = "Skriv sidans kod (PROOF_TOKEN).";
    return;
  }
  try {
    sessionStorage.setItem("proof-token", token);
  } catch {
    // sessionStorage unavailable: keep going with the in-memory token
  }
  els.gateError.textContent = "";
  els.gate.hidden = true;
  els.app.hidden = false;
  worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
  worker.onmessage = onWorkerMessage;
  worker.onerror = (e) => setStatus(false, `Fel: ${e.message}`);
  send({ kind: "init", token });
  render();
});

try {
  const saved = sessionStorage.getItem("proof-token");
  if (saved) els.token.value = saved;
} catch {
  // ignore
}

els.prepare.addEventListener("click", () => {
  const topic = els.topic.value.trim() || "bråk";
  send({ kind: "prepare", topic, level: els.level.value });
});

els.answer.addEventListener("input", () => {
  const page = currentPage();
  if (!page || snapshot?.readOnly) return;
  window.clearTimeout(inputTimer);
  const text = els.answer.value;
  inputTimer = window.setTimeout(() => {
    send({ kind: "input", pageId: page.id, revision: page.revision, text });
    page.input = text;
    drawBoard(page, snapshot!.pages.length, snapshot!.current);
  }, 400);
});

els.prev.addEventListener("click", () => {
  if (snapshot && snapshot.current > 0) send({ kind: "goto", index: snapshot.current - 1 });
});
els.next.addEventListener("click", () => {
  if (snapshot && snapshot.current < snapshot.pages.length - 1) {
    send({ kind: "goto", index: snapshot.current + 1 });
  }
});

els.foxGo.addEventListener("click", () => {
  const page = currentPage();
  if (!page) return;
  send({ kind: "fox", command: els.foxCmd.value || "visa svaret", pageId: page.id, revision: page.revision });
});

els.observe.addEventListener("click", async () => {
  try {
    const pngBase64 = await snapshotPng();
    send({ kind: "observe", pngBase64 });
  } catch (err) {
    setStatus(false, `Fel: ${err instanceof Error ? err.message : String(err)}`);
  }
});

window.addEventListener("beforeunload", () => {
  try {
    send({ kind: "close" });
  } catch {
    // ignore
  }
});

render();
