/**
 * Screen worker: the browser-owned Pi Durable Harness host.
 *
 * Runs in a module Web Worker. Owns one Durable session per learner profile
 * (`IndexedDbStorage("open-tutor-screen-{profileId}")`), the ongoing root
 * conversation, JSON docs for artifacts/candidates/control state, and narrow
 * tools. Model access goes through the same-origin OpenAI-compatible Screen
 * gateway (`/api/screen/openai/{room}` + `/chat/completions` appended by the
 * pi-ai provider); the family code lives only in worker memory, never in
 * storage.
 *
 * Authority rule: the worker PROPOSES invisible candidates. Promotion into
 * the visible deck happens only in the main-thread controller (pure deck
 * functions). Reveal is deterministic main-thread logic, not a model turn,
 * so the worker exposes no reveal path at all.
 */
import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";
import { createModels, createProvider } from "@earendil-works/pi-ai/models";
import { OPENCODE_GO_MODELS } from "@earendil-works/pi-ai/providers/opencode-go.models";
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
import { sanitizeSvg } from "./renderer";
import type {
  CandidatePage,
  ScreenArtifact,
  ScreenIntent,
  ScreenPageKind,
} from "./types";
import type { MainToScreenWorker, ScreenWorkerToMain } from "./worker-protocol";

const MODEL_ID = "deepseek-v4.1-flash";

type CandidatesDoc = { json: string };
type ArtifactsDoc = { json: string };
type ControlDoc = { json: string };

interface ControlState {
  latestByNeed: Record<string, number>;
  needByIntent: Record<string, string>;
}

const ScreenCandidatesDoc = defineDoc<CandidatesDoc>({
  kind: "screen.candidates",
  version: 1,
  scope: "session",
  initial: () => ({ json: "[]" }),
  checkpointWhen: () => false,
});

const ScreenArtifactsDoc = defineDoc<ArtifactsDoc>({
  kind: "screen.artifacts",
  version: 1,
  scope: "session",
  initial: () => ({ json: "[]" }),
  checkpointWhen: () => false,
});

const ScreenControlDoc = defineDoc<ControlDoc>({
  kind: "screen.control",
  version: 1,
  scope: "session",
  initial: () => ({ json: JSON.stringify({ latestByNeed: {}, needByIntent: {} }) }),
  checkpointWhen: () => false,
});

const PrepareExerciseParams = obj({
  intentId: str(),
  seq: str(),
  needKey: str(),
  topic: str(),
  question: str(),
  solution: str(),
});

const ProposeGeographyParams = obj({
  intentId: str(),
  seq: str(),
  needKey: str(),
  title: str(),
  body: str(),
  solution: str(),
  svg: str(),
  attribution: str(),
  sources: str(),
  imageUrl: str(),
});

const RecordArtifactParams = obj({
  intentId: str(),
  kind: str(),
  payloadJson: str(),
  provenance: str(),
  blobIdsCsv: str(),
});

const FetchGeographyParams = obj({
  query: str(),
  requestId: str(),
  lessonId: str(),
});

const RequestResearchParams = obj({
  intentId: str(),
  seq: str(),
  needKey: str(),
  query: str(),
  requestId: str(),
  lessonId: str(),
});

const post = (msg: ScreenWorkerToMain) =>
  (self as unknown as { postMessage(m: unknown): void }).postMessage(msg);

const ctx = BACKGROUND_CONTEXT;

let harness: any = null;
let rootHandle: any = null;
let accessCode = "";
let room = "";
let lessonId = "";
let learnerName = "";
let closing = false;
const sentCandidateIds = new Set<string>();

function readJsonArray<T>(json: string): T[] {
  try {
    const parsed: unknown = JSON.parse(json);
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}

function readControl(value: string): ControlState {
  try {
    const parsed = JSON.parse(value) as Partial<ControlState>;
    return {
      latestByNeed: parsed.latestByNeed ?? {},
      needByIntent: parsed.needByIntent ?? {},
    };
  } catch {
    return { latestByNeed: {}, needByIntent: {} };
  }
}

function newPageId(prefix: string): string {
  return `${prefix}${Date.now().toString(36)}${Math.floor(Math.random() * 0xffff).toString(36)}`;
}

function candidateKey(c: { intentId: string; id: string }): string {
  return `${c.intentId}:${c.id}`;
}

async function readDocJson(token: never): Promise<string> {
  const snap = await harness.snapshot(token, undefined, ctx);
  const value = (snap as { json?: string } | null) ?? null;
  return value?.json ?? "[]";
}

async function publishUnsentCandidates(): Promise<void> {
  if (!harness || closing) return;
  try {
    const raw = await readDocJson(ScreenCandidatesDoc as never);
    const candidates = readJsonArray<CandidatePage>(raw);
    for (const c of candidates) {
      if (c.status !== "ready") continue;
      const key = candidateKey(c);
      if (sentCandidateIds.has(key)) continue;
      sentCandidateIds.add(key);
      post({ kind: "candidate", candidate: c, artifacts: [] });
    }
  } catch (err) {
    console.warn("[screen-worker] candidate publish failed:", err);
  }
}

async function noteLatestNeed(needKeyValue: string, seq: number, intentId: string): Promise<void> {
  await rootHandle.commit(async (tx: any) => {
    const doc = (await tx.doc(ScreenControlDoc)) as ControlDoc;
    const control = readControl(doc.json);
    if ((control.latestByNeed[needKeyValue] ?? 0) < seq) {
      control.latestByNeed[needKeyValue] = seq;
    }
    control.needByIntent[intentId] = needKeyValue;
    doc.json = JSON.stringify(control);
  }, ctx);
}

async function isSuperseded(needKeyValue: string, seq: number): Promise<boolean> {
  const raw = await readDocJson(ScreenControlDoc as never);
  const control = readControl(raw);
  return (control.latestByNeed[needKeyValue] ?? 0) > seq;
}

async function storeCandidate(page: Omit<CandidatePage, "status" | "receivedAt">): Promise<void> {
  await rootHandle.commit(async (tx: any) => {
    const doc = (await tx.doc(ScreenCandidatesDoc)) as CandidatesDoc;
    const list = readJsonArray<CandidatePage>(doc.json);
    list.push({ ...page, status: "ready", receivedAt: Date.now() });
    doc.json = JSON.stringify(list.slice(-40));
  }, ctx);
}

function baseCandidate(
  args: { intentId: string; seq: string; needKey: string },
  kind: ScreenPageKind,
  subject: string,
  title: string,
  body: string[],
  solution: string,
  extra: Partial<CandidatePage>,
): Omit<CandidatePage, "status" | "receivedAt"> {
  return {
    id: newPageId("p"),
    revision: `r${Date.now().toString(36)}`,
    lessonId,
    kind,
    subject,
    title: title.slice(0, 140),
    body: body.map((line) => line.slice(0, 600)).slice(0, 8),
    asset: null,
    svgAsset: null,
    answerLabel: "Ditt svar",
    solution: solution.slice(0, 600),
    sources: [],
    revealed: false,
    createdAt: Date.now(),
    intentId: args.intentId,
    requestSeq: Number(args.seq) || 0,
    ...extra,
  };
}

const prepareExerciseTool = defineTool({
  name: "prepare_exercise",
  description:
    "Save one Swedish primary-school maths exercise as an invisible candidate. Call exactly once per preparation.",
  parameters: PrepareExerciseParams,
  execute: async (args: any, _api: any, callContext: any) => {
    void callContext;
    const topic = String(args.topic ?? "").trim().slice(0, 80);
    const question = String(args.question ?? "").trim().slice(0, 600);
    const solution = String(args.solution ?? "").trim().slice(0, 600);
    if (!topic || !question || !solution) {
      return {
        output: [{ type: "text", text: "rejected: topic, question and solution must all be non-empty" }],
        isError: true,
      };
    }
    if (await isSuperseded(String(args.needKey), Number(args.seq) || 0)) {
      return {
        output: [{ type: "text", text: "superseded by a newer request; do not retry." }],
      };
    }
    const page = baseCandidate(args, "exercise", "Matte", `${topic}: ${question}`.slice(0, 140), [question], solution, {});
    await storeCandidate(page);
    await publishUnsentCandidates();
    return { output: [{ type: "text", text: `saved exercise candidate ${page.id}` }] };
  },
});

const proposeGeographyTool = defineTool({
  name: "propose_geography",
  description:
    "Save one Swedish geography page as an invisible candidate, with a generated SVG map or a researched image URL for the main thread to download. Call exactly once per research task.",
  parameters: ProposeGeographyParams,
  execute: async (args: any, _api: any, callContext: any) => {
    void callContext;
    const title = String(args.title ?? "").trim().slice(0, 140);
    const body = String(args.body ?? "").trim().slice(0, 1200);
    const solution = String(args.solution ?? "").trim().slice(0, 600);
    const attribution = String(args.attribution ?? "").trim().slice(0, 300);
    if (!title || !body || !solution) {
      return {
        output: [{ type: "text", text: "rejected: title, body and solution must all be non-empty" }],
        isError: true,
      };
    }
    if (await isSuperseded(String(args.needKey), Number(args.seq) || 0)) {
      return {
        output: [{ type: "text", text: "superseded by a newer request; do not retry." }],
      };
    }
    const rawSvg = String(args.svg ?? "");
    const svg = rawSvg.trim() ? sanitizeSvg(rawSvg) : null;
    const imageUrl = String(args.imageUrl ?? "").trim();
    const httpsImage = imageUrl.startsWith("https://") ? imageUrl.slice(0, 500) : null;
    const sources = String(args.sources ?? "")
      .split("\n")
      .map((s: string) => s.trim().slice(0, 300))
      .filter(Boolean)
      .slice(0, 4);
    if (attribution) sources.unshift(attribution);
    const page = baseCandidate(args, "geography", "Geografi", title, body.split("\n").map((s: string) => s.trim()).filter(Boolean), solution, {
      svgAsset: httpsImage ? null : svg,
      sources: [...new Set(sources)].slice(0, 4),
    });
    await storeCandidate(page);
    if (httpsImage) {
      const key = candidateKey(page);
      sentCandidateIds.add(key);
      post({
        kind: "candidate",
        candidate: { ...page, status: "ready", receivedAt: Date.now() },
        artifacts: [],
        researchImage: { url: httpsImage, attribution: attribution || "Okänd källa" },
      });
    } else {
      await publishUnsentCandidates();
    }
    return { output: [{ type: "text", text: `saved geography candidate ${page.id}` }] };
  },
});

const recordArtifactTool = defineTool({
  name: "record_artifact",
  description: "Store a small JSON artifact (search result, source text, caption) for candidate preparation.",
  parameters: RecordArtifactParams,
  execute: async (args: any, api: any, callContext: any) => {
    void callContext;
    let payload: Record<string, string> = {};
    try {
      const parsed: unknown = JSON.parse(String(args.payloadJson ?? "{}"));
      if (parsed && typeof parsed === "object") {
        payload = Object.fromEntries(
          Object.entries(parsed as Record<string, unknown>)
            .filter(([, v]) => typeof v === "string")
            .map(([k, v]) => [k.slice(0, 80), String(v).slice(0, 2000)]),
        );
      }
    } catch {
      return { output: [{ type: "text", text: "rejected: payloadJson is not JSON" }], isError: true };
    }
    const artifact: ScreenArtifact = {
      id: newPageId("a"),
      lessonId,
      intentId: String(args.intentId ?? ""),
      kind: "source-text",
      payload,
      blobIds: String(args.blobIdsCsv ?? "")
        .split(",")
        .map((s: string) => s.trim())
        .filter(Boolean)
        .slice(0, 8),
      provenance: String(args.provenance ?? "").slice(0, 300),
      createdAt: Date.now(),
    };
    await api.commit(async (tx: any) => {
      const sessionDoc = (await tx.doc(ScreenArtifactsDoc)) as ArtifactsDoc;
      const list = readJsonArray<ScreenArtifact>(sessionDoc.json);
      list.push(artifact);
      sessionDoc.json = JSON.stringify(list.slice(-100));
    }, callContext);
    return { output: [{ type: "text", text: `recorded artifact ${artifact.id}` }] };
  },
});

const fetchGeographyTool = defineTool({
  name: "fetch_geography",
  description: "Query the bounded same-origin geography gateway. Returns small sourced features with provenance.",
  parameters: FetchGeographyParams,
  execute: async (args: any, _api: any, callContext: any) => {
    void callContext;
    const query = String(args.query ?? "").trim().slice(0, 120);
    if (!query) {
      return { output: [{ type: "text", text: "rejected: empty query" }], isError: true };
    }
    const url =
      `/api/screen/research/geography?query=${encodeURIComponent(query)}` +
      `&lessonId=${encodeURIComponent(String(args.lessonId ?? lessonId))}` +
      `&requestId=${encodeURIComponent(String(args.requestId ?? ""))}`;
    let res: Response;
    try {
      res = await fetch(url, { headers: { "x-tutor-code": accessCode }, cache: "no-store" });
    } catch (err) {
      return {
        output: [{ type: "text", text: `gateway unreachable: ${err instanceof Error ? err.message : String(err)}` }],
        isError: true,
      };
    }
    if (!res.ok) {
      return { output: [{ type: "text", text: `gateway ${res.status}` }], isError: true };
    }
    const text = await res.text();
    return { output: [{ type: "text", text: text.slice(0, 6000) }] };
  },
});

const requestResearchTool = defineTool({
  name: "request_geography_research",
  description:
    "Start geography research in a Durable-native background child conversation and return immediately. The child proposes the candidate when done; this turn stays reactive.",
  parameters: RequestResearchParams,
  execute: async (args: any, _api: any, callContext: any) => {
    const query = String(args.query ?? "").trim().slice(0, 200);
    if (!query) {
      return { output: [{ type: "text", text: "rejected: empty query" }], isError: true };
    }
    const child = await harness.createConversation(
      {
        ownership: { kind: "ownerless" },
        agent: {
          model: { provider: "screen-proxy", modelId: MODEL_ID },
          thinkingLevel: "low",
          instructions:
            "You are a geography research subagent for a Swedish primary-school tutor. " +
            "Use fetch_geography exactly once, then propose_geography exactly once with a short Swedish " +
            "geography page (title, 2-4 body lines, solution, generated SVG map or researched image URL, " +
            "attribution, sources). Never write visible pages; you only propose invisible candidates.",
        },
      },
      callContext,
    );
    await child.submit(
      {
        type: "input",
        content:
          `Research task for intent ${String(args.intentId)} (seq ${String(args.seq)}, need ${String(args.needKey)}, ` +
          `lesson ${lessonId}, request ${String(args.requestId)}). Query the gateway for "${query}" with ` +
          `fetch_geography, then call propose_geography exactly once with intentId "${String(args.intentId)}", ` +
          `seq "${String(args.seq)}" and needKey "${String(args.needKey)}". If a newer request superseded this one, ` +
          `the propose call will tell you; do not retry then.`,
      },
      callContext,
    );
    return { output: [{ type: "text", text: `background research started for "${query}"` }] };
  },
});

const ScreenExtension = defineExtension({
  name: "screen",
  tools: [prepareExerciseTool, proposeGeographyTool, recordArtifactTool, fetchGeographyTool, requestResearchTool],
  sections: [
    section(
      "brief",
      () => (
        "You are the Screen, the visual workspace agent for Swedish primary-school tutoring. " +
        "Write short Swedish exercises and geography pages with a clear answer. " +
        "You only propose invisible candidates through your tools; the main thread promotes them. " +
        "Never claim a page is visible. No shell, no files, no other tools."
      ),
      { tag: false },
    ),
  ],
});

async function lastErrorDetail(): Promise<string> {
  try {
    const page = await rootHandle.entries({ order: "descending" }, 10, undefined, ctx);
    for (const entry of (page as { items: unknown[] }).items ?? []) {
      const model = (entry as { model?: unknown })?.model;
      if (Array.isArray(model)) {
        for (const msg of model) {
          const detail = (msg as { errorMessage?: unknown })?.errorMessage;
          if (typeof detail === "string" && detail) return detail.slice(0, 300);
        }
      }
    }
  } catch {
    // diagnostics only
  }
  return "";
}

async function handlePrepare(intent: ScreenIntent, seq: number): Promise<void> {
  const need = `${(intent.need ?? "").trim().toLowerCase()}\n${(intent.background ?? "").trim().toLowerCase()}`;
  const geographyHint = /(geografi|karta|land|stad|landskap|värld|europa|sverige|norden)/i.test(
    `${intent.need ?? ""} ${intent.background ?? ""}`,
  );
  try {
    await noteLatestNeed(need, seq, intent.intentId);
    const submission = await rootHandle.submit(
      {
        type: "input",
        content: geographyHint
          ? `Prepare a Swedish primary-school geography page for intent ${intent.intentId} (seq ${seq}, need "${intent.need ?? ""}"). ` +
            `Background: ${(intent.background ?? "").slice(0, 500) || "none"}. ` +
            `Start background research with request_geography_research (query "${(intent.need ?? "").slice(0, 120)}", ` +
            `requestId "${intent.intentId}-${seq}", lessonId "${intent.lessonId}", intentId "${intent.intentId}", ` +
            `seq "${seq}", needKey ${JSON.stringify(need)}), then reply with one short Swedish status sentence.`
          : `Prepare a Swedish primary-school maths exercise for intent ${intent.intentId} (seq ${seq}) about ` +
            `"${(intent.need ?? "räkning").slice(0, 120)}". Background: ${(intent.background ?? "").slice(0, 500) || "none"}. ` +
            `Call prepare_exercise exactly once with intentId "${intent.intentId}", seq "${seq}", ` +
            `needKey ${JSON.stringify(need)} and the exercise, then confirm with one short Swedish sentence.`,
      },
      ctx,
    );
    const settled = await submission.wait(ctx);
    if (settled.status !== "done") {
      const detail = await lastErrorDetail();
      post({
        kind: "worker-failed",
        intentId: intent.intentId,
        reason: `preparation failed: ${settled.reason ?? settled.status}${detail ? ` (${detail})` : ""}`,
      });
      return;
    }
    await publishUnsentCandidates();
    post({ kind: "worker-log", text: `Screen prepared ${intent.intentId}.` });
  } catch (err) {
    post({
      kind: "worker-failed",
      intentId: intent.intentId,
      reason: `preparation failed: ${err instanceof Error ? err.message : String(err)}`,
    });
  }
}

async function boot(init: {
  profileId: string;
  room: string;
  lessonId: string;
  learnerName: string;
  grade?: string;
  priorNotes: { text: string; createdAt?: number }[];
  accessCode: string;
}): Promise<void> {
  accessCode = init.accessCode;
  room = init.room;
  lessonId = init.lessonId;
  learnerName = init.learnerName;
  const safeProfile = init.profileId.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 64) || "default";

  const base = OPENCODE_GO_MODELS[MODEL_ID as keyof typeof OPENCODE_GO_MODELS];
  if (!base) throw new Error(`${MODEL_ID} missing from published opencode-go catalog`);
  const baseUrl = new URL(
    `/api/screen/openai/${encodeURIComponent(room)}`,
    (self as unknown as { location: { origin: string } }).location.origin,
  )
    .toString()
    .replace(/\/$/, "");
  const proxyModel = { ...base, provider: "screen-proxy", baseUrl };
  const provider = createProvider({
    id: "screen-proxy",
    name: "Screen proxy",
    auth: {
      apiKey: {
        name: "Family code (memory only)",
        resolve: async () => ({ auth: { apiKey: accessCode }, source: "screen init" }),
      },
    },
    models: [proxyModel],
    api: { "openai-completions": openAICompletionsApi() },
  } as never);
  const models = createModels();
  models.setProvider(provider as never);

  const storage = await IndexedDbStorage.open(`open-tutor-screen-${safeProfile}`);
  const registry = createRegistry();
  registry.install(ScreenExtension);
  harness = await Harness.open(storage, { models: models as never, registry: registry as never }, ctx);
  rootHandle = await harness.root(ctx, {
    agent: {
      model: { provider: "screen-proxy", modelId: MODEL_ID },
      thinkingLevel: "low",
      instructions:
        `You are the Screen for ${learnerName}${init.grade ? ` (${init.grade})` : ""}. ` +
        "Swedish, short, primary-school level. Prior notes: " +
        (init.priorNotes.map((n) => n.text).join(" | ").slice(0, 800) || "none"),
    },
  });

  setInterval(() => {
    if (!closing) void publishUnsentCandidates();
  }, 2500);
  post({ kind: "harness-ready" });
}

(self as unknown as { onmessage: ((e: MessageEvent<MainToScreenWorker>) => void) | null }).onmessage = (e) => {
  const msg = e.data;
  void (async () => {
    switch (msg.kind) {
      case "init":
        try {
          await boot(msg.init);
        } catch (err) {
          post({ kind: "worker-failed", intentId: "", reason: err instanceof Error ? err.message : String(err) });
        }
        break;
      case "prepare":
        await handlePrepare(msg.intent, msg.seq);
        break;
      case "close":
        closing = true;
        try {
          await harness?.close(ctx);
        } catch {
          // ignore close errors
        }
        break;
    }
  })();
};
