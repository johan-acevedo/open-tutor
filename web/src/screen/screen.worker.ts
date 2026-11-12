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
import { createBlobStore, validateAssetRef, type ScreenBlobStore } from "./assets";
import { sanitizeSvg } from "./renderer";
import type {
  CandidatePage,
  ScreenArtifact,
  ScreenIntent,
  ScreenPageKind,
} from "./types";
import type { MainToScreenWorker, ScreenWorkerToMain } from "./worker-protocol";

import { SCREEN_MODEL_ID, SCREEN_THINKING_LEVEL } from "./screenConfig";

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
  assetId: str(),
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
let profileId = "";
let blobStore: ScreenBlobStore | null = null;
let closing = false;
let bootPromise: Promise<void> | null = null;
const sentCandidateIds = new Set<string>();
const MAX_MAP_BYTES = 1_200_000;
const ALLOWED_MAP_MIMES = new Set(["image/png", "image/jpeg", "image/webp"]);

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

function decodeDataUrlBytes(dataUrl: string): { mime: string; bytes: Uint8Array } {
  const match = /^data:(image\/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)$/.exec(dataUrl);
  if (!match) throw new Error("bad dataUrl");
  const mime = match[1]!;
  const b64 = match[2]!;
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  if (bytes.byteLength === 0 || bytes.byteLength > MAX_MAP_BYTES) {
    throw new Error("map size out of bounds");
  }
  if (!ALLOWED_MAP_MIMES.has(mime)) throw new Error("unsafe mime");
  return { mime, bytes };
}

const proposeGeographyTool = defineTool({
  name: "propose_geography",
  description:
    "Save one Swedish geography page as an invisible candidate. Prefer a chosen assetId from fetch_geography (validated blob-store map asset with source attribution); otherwise use a generated SVG map. Call exactly once per research task.",
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
    const sources = String(args.sources ?? "")
      .split("\n")
      .map((s: string) => s.trim().slice(0, 300))
      .filter(Boolean)
      .slice(0, 4);
    if (attribution) sources.unshift(attribution);
    // Real path: chosen blob-store map asset from fetch_geography.
    let assetRef: CandidatePage["asset"] = null;
    const chosenId = String(args.assetId ?? "").trim().slice(0, 128);
    if (chosenId && blobStore) {
      try {
        const record = await blobStore.get(chosenId);
        if (record) {
          const candidateRef = {
            id: chosenId,
            hash: record.hash,
            mimeType: record.meta.mimeType,
            provenance: record.meta.provenance.slice(0, 300) || attribution || "Wikimedia Commons",
            lessonId,
            status: "ready" as const,
            attribution: attribution || record.meta.provenance.slice(0, 300),
          };
          if (validateAssetRef(candidateRef).length === 0) {
            assetRef = candidateRef;
            if (attribution && !sources.includes(attribution)) sources.unshift(attribution);
            if (record.meta.provenance && !sources.includes(record.meta.provenance.slice(0, 300))) {
              sources.unshift(record.meta.provenance.slice(0, 300));
            }
          }
        }
      } catch {
        // fall through to SVG / legacy handling
      }
    }
    // Legacy compat: raw https image URL for the main thread to download.
    const imageUrl = String(args.imageUrl ?? "").trim();
    const httpsImage = !assetRef && imageUrl.startsWith("https://") ? imageUrl.slice(0, 500) : null;
    const page = baseCandidate(args, "geography", "Geografi", title, body.split("\n").map((s: string) => s.trim()).filter(Boolean), solution, {
      asset: assetRef,
      svgAsset: assetRef || httpsImage ? null : svg,
      sources: [...new Set(sources)].slice(0, 4),
    });
    await storeCandidate(page);
    if (assetRef) {
      // Already stored worker-side: publish immediately with the validated ref.
      // No external browser download is needed for this path.
      await publishUnsentCandidates();
    } else if (httpsImage) {
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
  description:
    "Query the bounded same-origin geography gateway (POST JSON {query}). Parses place + map candidates, stores map bytes in the per-profile blob store as artifact assets, and returns only concise place + map assetIds/metadata. Never returns base64 to the model.",
  parameters: FetchGeographyParams,
  execute: async (args: any, api: any, callContext: any) => {
    void callContext;
    const query = String(args.query ?? "").trim().slice(0, 200);
    if (!query) {
      return { output: [{ type: "text", text: "rejected: empty query" }], isError: true };
    }
    if (!blobStore) {
      return { output: [{ type: "text", text: "blob store not ready" }], isError: true };
    }
    const requestLesson = String(args.lessonId ?? lessonId);
    let res: Response;
    try {
      res = await fetch("/api/screen/research/geography", {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-tutor-code": accessCode },
        body: JSON.stringify({ query }),
        cache: "no-store",
      });
    } catch (err) {
      return {
        output: [{ type: "text", text: `gateway unreachable: ${err instanceof Error ? err.message : String(err)}` }],
        isError: true,
      };
    }
    if (!res.ok) {
      return { output: [{ type: "text", text: `gateway ${res.status}` }], isError: true };
    }
    let body: unknown;
    try {
      body = await res.json();
    } catch {
      return { output: [{ type: "text", text: "rejected: bad gateway JSON" }], isError: true };
    }
    if (typeof body !== "object" || body === null) {
      return { output: [{ type: "text", text: "rejected: bad gateway shape" }], isError: true };
    }
    const record = body as Record<string, unknown>;
    const placeRaw = record["place"] as Record<string, unknown> | null;
    const placeName =
      placeRaw && typeof placeRaw["displayName"] === "string"
        ? (placeRaw["displayName"] as string).slice(0, 200)
        : "";
    const placeLat = placeRaw?.["lat"];
    const placeLon = placeRaw?.["lon"];
    const placeLine =
      placeName && typeof placeLat === "number" && typeof placeLon === "number"
        ? `${placeName} (${placeLat.toFixed(3)}, ${placeLon.toFixed(3)})`
        : placeName || "okänd plats";
    const rawMaps = Array.isArray(record["maps"]) ? (record["maps"] as unknown[]) : [];
    const lines: string[] = [`Plats: ${placeLine}`];
    const storedIds: string[] = [];
    for (const raw of rawMaps.slice(0, 3)) {
      if (typeof raw !== "object" || raw === null) continue;
      const entry = raw as Record<string, unknown>;
      const dataUrl = entry["dataUrl"];
      const mime = entry["mime"];
      const sourceUrl = entry["sourceUrl"];
      if (typeof dataUrl !== "string" || typeof mime !== "string" || typeof sourceUrl !== "string") continue;
      if (!sourceUrl.startsWith("https://")) continue;
      if (!ALLOWED_MAP_MIMES.has(mime)) continue;
      let decoded: { mime: string; bytes: Uint8Array };
      try {
        decoded = decodeDataUrlBytes(dataUrl);
      } catch {
        continue;
      }
      if (decoded.mime !== mime) continue;
      const attribution =
        typeof entry["attribution"] === "string"
          ? (entry["attribution"] as string).slice(0, 200)
          : "";
      const license =
        typeof entry["license"] === "string" ? (entry["license"] as string).slice(0, 120) : "";
      const provenance = [sourceUrl.slice(0, 300), attribution].filter(Boolean).join(" | ").slice(0, 300) || "Wikimedia Commons";
      const assetId = newPageId("b");
      try {
        await blobStore.put(assetId, decoded.bytes, {
          mimeType: decoded.mime,
          provenance,
          lessonId: requestLesson,
        });
      } catch {
        continue;
      }
      storedIds.push(assetId);
      lines.push(
        `- karta ${storedIds.length}: assetId ${assetId}, mime ${decoded.mime}, ` +
          `bytes ${decoded.bytes.byteLength}, källa ${sourceUrl.slice(0, 120)}, ` +
          `attribution ${attribution || "Wikimedia Commons"}${license ? `, licens ${license}` : ""}`,
      );
    }
    if (storedIds.length === 0) {
      lines.push("Inga kartbilder hittades; använd genererad SVG i propose_geography.");
    } else {
      lines.push(`Använd propose_geography med vald assetId (${storedIds.join(", ")}) plus titel/kropp/facit.`);
    }
    const provenanceLine = `Proveniens: Nominatim + Wikimedia Commons, hämtad ${String(record["retrievedAt"] ?? "").slice(0, 32) || "nyligen"}.`;
    lines.push(provenanceLine);
    // Concise artifact record (no bytes): blob ids + provenance for audit.
    try {
      if (api && typeof api.commit === "function" && storedIds.length > 0) {
        const artifact: ScreenArtifact = {
          id: newPageId("a"),
          lessonId: requestLesson,
          intentId: "",
          kind: "map-data",
          payload: {
            query: query.slice(0, 200),
            place: placeLine.slice(0, 300),
            maps: lines.slice(1, 4).join("\n").slice(0, 2000),
          },
          blobIds: storedIds.slice(0, 8),
          provenance: provenanceLine.slice(0, 300),
          createdAt: Date.now(),
        };
        await api.commit(async (tx: any) => {
          const doc = (await tx.doc(ScreenArtifactsDoc)) as ArtifactsDoc;
          const list = readJsonArray<ScreenArtifact>(doc.json);
          list.push(artifact);
          doc.json = JSON.stringify(list.slice(-100));
        }, callContext);
      }
    } catch {
      // artifact audit is best-effort; the concise return value is authoritative
    }
    const text = lines.join("\n").slice(0, 3000);
    if (text.includes("base64") || text.includes("data:image")) {
      return { output: [{ type: "text", text: "rejected: map encoding leaked" }], isError: true };
    }
    return { output: [{ type: "text", text }] };
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
          model: { provider: "screen-proxy", modelId: SCREEN_MODEL_ID },
          thinkingLevel: SCREEN_THINKING_LEVEL,
          instructions:
            "You are a geography research subagent for a Swedish primary-school tutor. " +
            "Use fetch_geography exactly once, then propose_geography exactly once with a short Swedish " +
            "geography page (title, 2-4 body lines, solution, chosen assetId from fetch_geography or generated SVG map, " +
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
            `Start background research with request_geography_research. Choose a short English place or historical region name ` +
            `for query (for example "France"), not the learner's whole request or instructions. Pass ` +
            `requestId "${intent.intentId}-${seq}", lessonId "${intent.lessonId}", intentId "${intent.intentId}", ` +
            `seq "${seq}", needKey ${JSON.stringify(need)}. Then reply with one short Swedish status sentence.`
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
  profileId = init.profileId;
  try {
    blobStore = createBlobStore(profileId);
  } catch {
    blobStore = null;
  }
  const safeProfile = init.profileId.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 64) || "default";

  const base = OPENCODE_GO_MODELS[SCREEN_MODEL_ID as keyof typeof OPENCODE_GO_MODELS];
  if (!base) throw new Error(`${SCREEN_MODEL_ID} missing from published opencode-go catalog`);
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
        // Pi requires a non-empty key even when our tailnet-only development
        // service deliberately allows passwordless access. This placeholder is
        // not a credential; real deployments still send the actual family code.
        resolve: async () => ({ auth: { apiKey: accessCode || "public-screen" }, source: "screen init" }),
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
      model: { provider: "screen-proxy", modelId: SCREEN_MODEL_ID },
      thinkingLevel: SCREEN_THINKING_LEVEL,
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
        bootPromise = boot(msg.init);
        try {
          await bootPromise;
        } catch (err) {
          post({ kind: "worker-failed", intentId: "", reason: err instanceof Error ? err.message : String(err) });
        }
        break;
      case "prepare":
        // Worker-side boot promise: never touch rootHandle before Harness
        // boot/harness-ready completes. Main-thread queueing is the second
        // fence; this one removes the rootHandle-null race entirely.
        if (bootPromise) {
          try {
            await bootPromise;
          } catch {
            // boot failed; handlePrepare below reports honestly
          }
        }
        if (!harness || !rootHandle) {
          post({
            kind: "worker-failed",
            intentId: (msg as { intent?: { intentId?: string } }).intent?.intentId ?? "",
            reason: "preparation failed: harness not ready",
          });
          break;
        }
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
