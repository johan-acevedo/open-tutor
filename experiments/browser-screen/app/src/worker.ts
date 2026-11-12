// Screen worker: the browser-owned Pi Durable Harness lives here.
//
// - Opens IndexedDbStorage("open-tutor-proof-v1") via the published
//   @earendil-works/pi-durable 1.5.2 `/storage/indexeddb` adapter.
// - Holds a Web Lock for the database lifetime: one owner tab. A second
//   tab sees the lock as taken and opens read-only.
// - Model access goes through a same-origin OpenAI-compatible proxy
//   (proof-proxy provider); the real provider key never enters the browser.
// - Narrow tools only: prepare_page (model fills it, worker validates and
//   commits the page). No shell, no file access in the browser agent.
// - Fox "commands" arrive as plain UI text and are validated here against
//   the current page id + revision. Stale or duplicate reveals are refused.
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { createModels } from "@earendil-works/pi-ai/models";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";
import { OPENCODE_GO_MODELS } from "@earendil-works/pi-ai/providers/opencode-go.models";
import { createProvider } from "@earendil-works/pi-ai/models";
import {
  createRegistry,
  defineDoc,
  defineExtension,
  defineTool,
  Harness,
  section,
} from "@earendil-works/pi-durable";
import { IndexedDbStorage } from "@earendil-works/pi-durable/storage/indexeddb";
import { obj, str } from "@earendil-works/pi-schema";
import type { MainToWorker, WorkerToMain, DeckPage, DeckSnapshot } from "./protocol.ts";

const DB_NAME = "open-tutor-proof-v1";
const LOCK_NAME = "open-tutor-proof-v1";
const MODEL_ID = "deepseek-v4.1-flash";

type Deck = { pages: DeckPage[]; current: number };

const DeckDoc = defineDoc<Deck>({
  kind: "proof.deck",
  version: 1,
  scope: "conversation",
  history: "latest",
  fork: "initial",
  initial: () => ({ pages: [], current: 0 }),
  checkpointWhen: () => false,
});

const PrepareParams = obj({ topic: str(), question: str(), solution: str() });

const post = (msg: WorkerToMain) => (self as unknown as { postMessage(m: unknown): void }).postMessage(msg);

let harness: Harness | undefined;
let root: { id: string } | undefined;
let rootHandle: any;
let readOnly = false;
let closing = false;
let ctx = BACKGROUND_CONTEXT;

function snapshotOf(deck: Deck, conversationId: string): DeckSnapshot {
  return { conversationId, pages: deck.pages, current: deck.current, readOnly };
}

async function readDeck(): Promise<Deck> {
  const snap = await harness!.snapshot(DeckDoc, root!.id as never, ctx);
  return (snap as unknown as Deck) ?? { pages: [], current: 0 };
}

async function publish() {
  if (!harness || !root) return;
  post({ kind: "deck", snapshot: snapshotOf(await readDeck(), root.id) });
}

function newRevision(): string {
  return `r${Date.now().toString(36)}${Math.floor(Math.random() * 0xffff).toString(36)}`;
}

const preparePageTool = defineTool({
  name: "prepare_page",
  description:
    "Save one primary-school Swedish maths exercise page. Call exactly once per preparation request.",
  parameters: PrepareParams,
  execute: async (args, api, callContext) => {
    const topic = args.topic.trim().slice(0, 80);
    const question = args.question.trim().slice(0, 600);
    const solution = args.solution.trim().slice(0, 600);
    if (!topic || !question || !solution) {
      return { output: [{ type: "text", text: "rejected: topic, question and solution must all be non-empty" }], isError: true };
    }
    const page: DeckPage = {
      id: `p${Date.now().toString(36)}${Math.floor(Math.random() * 0xffff).toString(36)}`,
      revision: newRevision(),
      topic,
      question,
      solution,
      input: "",
      revealed: false,
      createdAt: Date.now(),
    };
    await api.commit(async (tx) => {
      const deck = (await tx.doc(DeckDoc, api.conversationId)) as unknown as Deck;
      deck.pages.push(page);
      deck.current = deck.pages.length - 1;
    }, callContext);
    return { output: [{ type: "text", text: `saved page ${page.id} on "${topic}"` }] };
  },
});

const TutorExtension = defineExtension({
  name: "tutor",
  tools: [preparePageTool],
  sections: [
    section("brief", () => (
      "You are the Screen, an exercise-board agent for Swedish primary-school maths. " +
      "Write short Swedish exercises with a number answer. " +
      "When asked to prepare a page, call prepare_page exactly once with topic, question and solution, " +
      "then reply with one short Swedish sentence confirming the page. Nothing else is available: " +
      "no files, no shell, no other tools."
    ), { tag: false }),
  ],
});

const OBSERVE_PROMPT =
  "Describe exactly what you see in this board photo, in 3-6 short lines: " +
  "the page label (for example Page 1 of 2), the exercise question, what is written in the answer area, " +
  "and whether a solution/facit is currently shown or hidden. Do not solve the exercise. Do not guess.";

function extractText(record: any): string {
  const model = record?.model;
  if (!Array.isArray(model)) return "";
  const out: string[] = [];
  for (const msg of model) {
    const content = msg?.content;
    if (typeof content === "string") out.push(content);
    else if (Array.isArray(content)) {
      for (const part of content) {
        if (part && part.type === "text" && typeof part.text === "string") out.push(part.text);
      }
    }
  }
  return out.join("\n").trim();
}

async function lastAssistantText(): Promise<string> {
  const page = await rootHandle.entries({ order: "descending" }, 25, undefined, ctx);
  for (const entry of page.items as any[]) {
    if (entry?.kind === "pi.assistant") {
      const text = extractText(entry);
      if (text) return text;
    }
  }
  return "";
}

async function lastErrorDetail(): Promise<string> {
  try {
    const page = await rootHandle.entries({ order: "descending" }, 10, undefined, ctx);
    for (const entry of page.items as any[]) {
      const model = (entry as any)?.model;
      if (Array.isArray(model)) {
        for (const msg of model) {
          if (typeof msg?.errorMessage === "string" && msg.errorMessage) {
            return msg.errorMessage.slice(0, 300);
          }
        }
      }
      if (typeof (entry as any)?.errorMessage === "string" && (entry as any).errorMessage) {
        return String((entry as any).errorMessage).slice(0, 300);
      }
    }
  } catch {
    // diagnostics only; ignore
  }
  return "";
}

async function handlePrepare(topic: string, level: string) {
  post({ kind: "status", busy: true, text: `Screen förbereder: ${topic} …` });
  let failed: string | null = null;
  try {
    const submission = await rootHandle.submit(
      {
        type: "input",
        content:
          `Prepare one ${level} Swedish primary-school maths exercise about "${topic}". ` +
          `Call prepare_page with the exercise, then confirm in one short Swedish sentence.`,
      },
      ctx,
    );
    const settled = await submission.wait(ctx);
    if (settled.status !== "done") {
      const detail = await lastErrorDetail();
      failed = `preparation failed: ${settled.reason ?? settled.status}${detail ? ` (${detail})` : ""}`;
    } else {
      await publish();
    }
  } catch (err) {
    failed = `preparation failed: ${err instanceof Error ? err.message : String(err)}`;
    console.error("[proof] prepare:", failed);
  }
  if (failed) {
    post({ kind: "status", busy: false, text: `Fel: ${failed}` });
  } else {
    post({ kind: "status", busy: false, text: "Sidan klar." });
  }
}

async function handleObserve(pngBase64: string) {
  post({ kind: "status", busy: true, text: "Räven tittar på tavlan …" });
  try {
    const submission = await rootHandle.submit(
      {
        type: "input",
        content: [
          { type: "text", text: OBSERVE_PROMPT },
          { type: "image", data: pngBase64, mimeType: "image/png" },
        ],
      },
      ctx,
    );
    const settled = await submission.wait(ctx);
    if (settled.status !== "done") {
      post({ kind: "error", message: `observation failed: ${settled.reason ?? settled.status}` });
      return;
    }
    const text = await lastAssistantText();
    post({ kind: "observed", text: text || "(tomt svar från modellen)" });
    post({ kind: "status", busy: false, text: "" });
  } catch (err) {
    const msg = `observation failed: ${err instanceof Error ? err.message : String(err)}`;
    console.error("[proof] observe:", msg);
    post({ kind: "status", busy: false, text: `Fel: ${msg}` });
  }
}

async function handleFox(command: string, pageId: string, revision: string) {
  const deck = await readDeck();
  const page = deck.pages[deck.current];
  const wantsReveal = /(visa|reveal|show|facit|svaret|answer|solution)/i.test(command);
  if (!wantsReveal) {
    post({ kind: "fox", text: `Räven förstod inte kommandot. Prova "visa svaret". (Simulerad kommandotolk.)` });
    return;
  }
  if (!page) {
    post({ kind: "fox", text: "Det finns ingen sida att visa svaret på ännu." });
    return;
  }
  if (page.id !== pageId || page.revision !== revision) {
    post({
      kind: "fox",
      text: `Avvisat: kommandot gällde en äldre sida (stale reveal). Den synliga sidan är ${page.id} ${page.revision}.`,
    });
    return;
  }
  if (page.revealed) {
    post({ kind: "fox", text: "Svaret visas redan på den här sidan. (Dubblett ignorerad.)" });
    return;
  }
  await rootHandle.commit(async (tx: any) => {
    const current = (await tx.doc(DeckDoc, root!.id)) as unknown as Deck;
    const target = current.pages[current.current];
    if (target && target.id === pageId && target.revision === revision) {
      target.revealed = true;
    }
  }, ctx);
  await publish();
  post({ kind: "fox", text: `Räven visar svaret på ${page.id}. (Simulerat rävkommando, bundet till sida + revision.)` });
}

async function boot(token: string) {
  try {
    // One owner tab per IndexedDB database: hold a Web Lock for the Harness
    // lifetime. Note locks.request() only resolves once the callback
    // finishes, so a held lock would deadlock boot if awaited — start the
    // request and probe the flag instead of awaiting it.
    let owned = false;
    if (typeof (self as any).navigator?.locks?.request === "function") {
      let released = false;
      void (self as any).navigator.locks
        .request(LOCK_NAME, { mode: "exclusive", ifAvailable: true }, async () => {
          owned = true;
          await new Promise<void>((resolve) => {
            (self as any).__releaseProofLock = () => resolve();
          });
        })
        .then(
          () => { released = true; },
          () => { released = true; },
        );
      const start = Date.now();
      while (!owned && !released && Date.now() - start < 2000) {
        await new Promise((r) => setTimeout(r, 50));
      }
    } else {
      owned = true; // No Web Locks (very old browser): single-tab assumption, say so in README.
    }
    readOnly = !owned;

    const base = OPENCODE_GO_MODELS["deepseek-v4.1-flash"];
    if (!base) throw new Error("deepseek-v4.1-flash missing from published opencode-go catalog");
    const proxyModel = { ...base, provider: "proof-proxy", baseUrl: new URL("/api/proxy/openai", (self as any).location.origin).toString().replace(/\/$/, "") };
    const provider = createProvider({
      id: "proof-proxy",
      name: "Proof proxy",
      auth: {
        apiKey: {
          name: "Proof page token",
          resolve: async () => ({ auth: { apiKey: token }, source: "page token" }),
        },
      },
      models: [proxyModel],
      api: { "openai-completions": openAICompletionsApi() },
    } as never);
    const models = createModels();
    models.setProvider(provider as never);

    const storage = await IndexedDbStorage.open(DB_NAME);
    const registry = createRegistry();
    registry.install(TutorExtension);
    harness = await Harness.open(storage, { models: models as never, registry: registry as never, readOnly }, ctx);
    rootHandle = await (harness as any).root(ctx, {
      agent: {
        model: { provider: "proof-proxy", modelId: MODEL_ID },
        thinkingLevel: "low",
        instructions: "Exercise-board Screen. Swedish, short, primary-school maths.",
      },
    });
    root = { id: rootHandle.id as string };

    if (!readOnly) {
      try {
        const watch = await (harness as any).watchDoc(DeckDoc, root.id, ctx);
        if (watch && typeof watch.start === "function") {
          watch.start(async () => {
            if (!closing) await publish();
          });
        }
      } catch {
        // watchDoc shape differs across releases; polling fallback below covers it.
      }
      setInterval(() => {
        if (!closing) publish().catch(() => {});
      }, 1500);
    }

    const deck = await readDeck();
    post({ kind: "ready", snapshot: snapshotOf(deck, root.id) });
    post({
      kind: "status",
      busy: false,
      text: readOnly ? "Skrivskyddad vy: en annan flik äger skärmen." : "",
    });
  } catch (err) {
    post({ kind: "error", message: err instanceof Error ? err.message : String(err) });
  }
}

(self as unknown as { onmessage: ((e: MessageEvent<MainToWorker>) => void) | null }).onmessage = (e) => {
  const msg = e.data;
  void (async () => {
    switch (msg.kind) {
      case "init":
        await boot(msg.token);
        break;
      case "prepare":
        if (readOnly) return post({ kind: "error", message: "read-only: another tab owns the screen" });
        await handlePrepare(msg.topic, msg.level);
        break;
      case "input":
        if (readOnly) return post({ kind: "error", message: "read-only: another tab owns the screen" });
        await rootHandle.commit(async (tx: any) => {
          const deck = (await tx.doc(DeckDoc, root!.id)) as unknown as Deck;
          const page = deck.pages.find((p) => p.id === msg.pageId);
          if (page && page.revision === msg.revision) page.input = msg.text.slice(0, 500);
        }, ctx);
        break;
      case "goto":
        if (readOnly) return;
        await rootHandle.commit(async (tx: any) => {
          const deck = (await tx.doc(DeckDoc, root!.id)) as unknown as Deck;
          if (msg.index >= 0 && msg.index < deck.pages.length) deck.current = msg.index;
        }, ctx);
        await publish();
        break;
      case "fox":
        if (readOnly) return post({ kind: "error", message: "read-only: another tab owns the screen" });
        await handleFox(msg.command, msg.pageId, msg.revision);
        break;
      case "observe":
        if (readOnly) return post({ kind: "error", message: "read-only: another tab owns the screen" });
        await handleObserve(msg.pngBase64);
        break;
      case "close":
        closing = true;
        try {
          await harness?.close(ctx);
        } catch {
          // ignore close errors in proof harness
        }
        (self as any).__releaseProofLock?.();
        break;
    }
  })();
};
