/**
 * Bounded geography research gateway client.
 *
 * First-slice geography calls `POST /api/screen/research/geography` with
 * JSON `{ query }` through the same-origin FastAPI service (public
 * Nominatim/Wikimedia data, enforced HTTPS/DNS/private-address/redirect /
 * size/time/content-type limits server-side). The gateway returns concise
 * place data plus up to 3 static map image candidates as bounded data URLs
 * with `sourceUrl`/`retrievedAt`/attribution/license:
 *
 *   `{ query, place, maps: [{ dataUrl, mime, bytes, sourceUrl,
 *      retrievedAt, attribution, license }], retrievedAt }`
 *
 * The main thread may decode `dataUrl` bytes into the per-profile blob
 * store (no external browser download needed for the real path). The worker
 * `fetch_geography` tool parses/validates maps, stores bytes as artifact
 * assets, records concise provenance, and returns only concise
 * place + map assetIds/metadata to the model — never base64.
 */
import { MAX_BLOB_BYTES } from "./assets";

export const GEOGRAPHY_PATH = "/api/screen/research/geography";

const ALLOWED_MAP_MIMES = new Set(["image/png", "image/jpeg", "image/webp"]);

export interface GeographyResearchQuery {
  query: string;
  lessonId: string;
  requestId: string;
  accessCode: string;
  fetchFn?: typeof fetch;
}

export interface GeographyPlace {
  displayName: string;
  lat: number;
  lon: number;
  boundingBox?: number[] | null;
  address?: Record<string, string>;
  category?: string;
  type?: string;
}

export interface GeographyMap {
  dataUrl: string;
  mime: string;
  bytes: number;
  sourceUrl: string;
  retrievedAt: string;
  attribution: string;
  license: string;
}

export interface GeographyGatewayResponse {
  query: string;
  place: GeographyPlace | null;
  maps: GeographyMap[];
  retrievedAt: string;
}

export interface GeographyResearchResult extends GeographyGatewayResponse {
  requestId: string;
  lessonId: string;
  fetchedAt: number;
}

/** Legacy shape kept only for compatibility with older callers. */
export interface GeographyFeature {
  name: string;
  lat: number;
  lon: number;
  attribution: string;
  imageUrl?: string;
}

export type GeographyVisual =
  | { kind: "researched"; feature: GeographyFeature }
  | { kind: "researched-map"; mapIndex: number; sourceUrl: string; attribution: string }
  | { kind: "generated" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Validate one gateway feature; returns null when unusable. (Legacy compat.) */
export function normalizeFeature(raw: unknown): GeographyFeature | null {
  if (!isRecord(raw)) return null;
  if (typeof raw["name"] !== "string" || !raw["name"].trim()) return null;
  if (!isFiniteNumber(raw["lat"]) || !isFiniteNumber(raw["lon"])) return null;
  if (typeof raw["attribution"] !== "string" || !raw["attribution"].trim()) return null;
  const feature: GeographyFeature = {
    name: raw["name"].slice(0, 120),
    lat: raw["lat"],
    lon: raw["lon"],
    attribution: raw["attribution"].slice(0, 300),
  };
  if (typeof raw["imageUrl"] === "string" && raw["imageUrl"].startsWith("https://")) {
    feature.imageUrl = raw["imageUrl"].slice(0, 500);
  }
  return feature;
}

function normalizePlace(raw: unknown): GeographyPlace | null {
  if (raw == null) return null;
  if (!isRecord(raw)) throw new Error("geography: bad place");
  if (!isFiniteNumber(raw["lat"]) || !isFiniteNumber(raw["lon"])) return null;
  if (typeof raw["displayName"] !== "string") return null;
  const place: GeographyPlace = {
    displayName: raw["displayName"].slice(0, 300),
    lat: raw["lat"],
    lon: raw["lon"],
  };
  if (Array.isArray(raw["boundingBox"])) {
    const nums = raw["boundingBox"].filter(isFiniteNumber).slice(0, 4);
    if (nums.length === 4) place.boundingBox = nums;
  }
  if (isRecord(raw["address"])) {
    const address: Record<string, string> = {};
    for (const [k, v] of Object.entries(raw["address"]).slice(0, 12)) {
      if (typeof v === "string") address[k.slice(0, 40)] = v.slice(0, 100);
    }
    place.address = address;
  }
  if (typeof raw["category"] === "string") place.category = raw["category"].slice(0, 40);
  if (typeof raw["type"] === "string") place.type = raw["type"].slice(0, 40);
  return place;
}

/** Validate one gateway map entry; returns null when unusable. */
export function normalizeMap(raw: unknown): GeographyMap | null {
  if (!isRecord(raw)) return null;
  const dataUrl = raw["dataUrl"];
  const mime = raw["mime"];
  const bytes = raw["bytes"];
  const sourceUrl = raw["sourceUrl"];
  if (typeof dataUrl !== "string" || !dataUrl.startsWith("data:image/")) return null;
  if (typeof mime !== "string" || !ALLOWED_MAP_MIMES.has(mime)) return null;
  if (!isFiniteNumber(bytes) || bytes <= 0 || bytes > MAX_BLOB_BYTES) return null;
  if (typeof sourceUrl !== "string" || !sourceUrl.startsWith("https://")) return null;
  if (!dataUrl.startsWith(`data:${mime};base64,`)) return null;
  return {
    dataUrl,
    mime,
    bytes,
    sourceUrl: sourceUrl.slice(0, 500),
    retrievedAt: typeof raw["retrievedAt"] === "string" ? raw["retrievedAt"].slice(0, 64) : "",
    attribution: typeof raw["attribution"] === "string" ? raw["attribution"].slice(0, 300) : "",
    license: typeof raw["license"] === "string" ? raw["license"].slice(0, 120) : "",
  };
}

/** Validate the gateway response body into a typed result. */
export function normalizeResearchResult(
  body: unknown,
  query: GeographyResearchQuery,
): GeographyResearchResult {
  if (!isRecord(body)) throw new Error("geography: response is not an object");
  if (typeof body["query"] !== "string") throw new Error("geography: missing query");
  const place = normalizePlace(body["place"] ?? null);
  const rawMaps = body["maps"];
  if (!Array.isArray(rawMaps)) throw new Error("geography: missing maps array");
  const maps = rawMaps
    .map(normalizeMap)
    .filter((m): m is GeographyMap => m !== null)
    .slice(0, 3);
  const retrievedAt = typeof body["retrievedAt"] === "string" ? body["retrievedAt"] : "";
  return {
    query: body["query"].slice(0, 200),
    place,
    maps,
    retrievedAt,
    requestId: query.requestId,
    lessonId: query.lessonId,
    fetchedAt: Date.now(),
  };
}

/** Decode a `data:image/...;base64,...` URL into MIME + bytes. */
export function decodeDataUrl(dataUrl: string): { mime: string; bytes: Uint8Array } {
  const match = /^data:(image\/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)$/.exec(dataUrl);
  if (!match) throw new Error("geography: bad dataUrl");
  const mime = match[1]!;
  const b64 = match[2]!;
  const binary = typeof atob !== "undefined" ? atob(b64) : Buffer.from(b64, "base64").toString("binary");
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  if (bytes.byteLength === 0 || bytes.byteLength > MAX_BLOB_BYTES) {
    throw new Error("geography: dataUrl size out of bounds");
  }
  if (!ALLOWED_MAP_MIMES.has(mime)) throw new Error("geography: unsafe mime");
  return { mime, bytes };
}

export async function fetchGeographyResearch(
  query: GeographyResearchQuery,
): Promise<GeographyResearchResult> {
  const text = query.query.trim();
  if (!text) throw new Error("geography: empty query");
  if (text.length < 2 || text.length > 200) throw new Error("geography: query out of bounds");
  // Public Swedish mode may run with an empty TUTOR_ACCESS_CODE: the backend
  // family_authorized() permits it, so never require a non-empty credential.
  // Always call same-origin; send the code as-is (possibly empty).
  const fetchFn = query.fetchFn ?? fetch;
  const res = await fetchFn(GEOGRAPHY_PATH, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-tutor-code": query.accessCode,
    },
    body: JSON.stringify({ query: text }),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`geography: gateway ${res.status}`);
  return normalizeResearchResult(await res.json(), query);
}

/**
 * The Screen's medium choice: a researched map asset when the gateway
 * returned at least one valid map, otherwise a generated SVG. Pure and
 * tested; the worker stores decoded map bytes in the blob store (docs carry
 * only the `ScreenAssetRef`), the main thread verifies the ref on ingest.
 */
export function selectGeographyVisual(result: GeographyResearchResult): GeographyVisual {
  const first = result.maps[0];
  if (first) {
    return {
      kind: "researched-map",
      mapIndex: 0,
      sourceUrl: first.sourceUrl,
      attribution: first.attribution || "Wikimedia Commons",
    };
  }
  return { kind: "generated" };
}

/** Bounded same-origin-or-https download for a legacy researched image URL. */
export async function downloadAssetBytes(
  url: string,
  accessCode: string,
  fetchFn: typeof fetch = fetch,
): Promise<Uint8Array> {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error("asset-download: bad url");
  }
  if (parsed.protocol !== "https:") throw new Error("asset-download: https only");
  const sameOrigin =
    typeof location !== "undefined" && parsed.origin === location.origin;
  const res = await fetchFn(parsed.toString(), {
    // The family code is a credential for our own service only. Never send it
    // to a model-selected third-party asset URL.
    headers: sameOrigin && accessCode ? { "x-tutor-code": accessCode } : {},
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`asset-download: ${res.status}`);
  const buffer = await res.arrayBuffer();
  if (buffer.byteLength === 0 || buffer.byteLength > MAX_BLOB_BYTES) {
    throw new Error("asset-download: size out of bounds");
  }
  return new Uint8Array(buffer);
}
