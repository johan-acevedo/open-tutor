/**
 * Bounded geography research gateway client.
 *
 * The first-slice geography tool calls `/api/research/geography` through the
 * same-origin FastAPI service (public Nominatim/Wikimedia data, enforced
 * HTTPS/DNS/private-address/redirect/size/time/content-type limits
 * server-side). The gateway returns provenance with small static assets; the
 * Screen then chooses a researched map asset or a generated SVG.
 */
import { MAX_BLOB_BYTES } from "./assets";

export const GEOGRAPHY_PATH = "/api/screen/research/geography";

export interface GeographyResearchQuery {
  query: string;
  lessonId: string;
  requestId: string;
  accessCode: string;
  fetchFn?: typeof fetch;
}

export interface GeographyFeature {
  name: string;
  lat: number;
  lon: number;
  attribution: string;
  imageUrl?: string;
}

export interface GeographyResearchResult {
  requestId: string;
  lessonId: string;
  query: string;
  features: GeographyFeature[];
  provenance: string[];
  fetchedAt: number;
}

export type GeographyVisual =
  | { kind: "researched"; feature: GeographyFeature }
  | { kind: "generated" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Validate one gateway feature; returns null when unusable. */
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

/** Validate the gateway response body into a typed result. */
export function normalizeResearchResult(
  body: unknown,
  query: GeographyResearchQuery,
): GeographyResearchResult {
  if (!isRecord(body)) throw new Error("geography: response is not an object");
  const rawFeatures = body["features"];
  if (!Array.isArray(rawFeatures)) throw new Error("geography: missing features array");
  const features = rawFeatures
    .map(normalizeFeature)
    .filter((f): f is GeographyFeature => f !== null)
    .slice(0, 5);
  const rawProvenance = body["provenance"];
  const provenance = Array.isArray(rawProvenance)
    ? rawProvenance.filter((p): p is string => typeof p === "string").map((p) => p.slice(0, 300)).slice(0, 8)
    : [];
  if (provenance.length === 0) throw new Error("geography: missing provenance");
  return {
    requestId: query.requestId,
    lessonId: query.lessonId,
    query: query.query,
    features,
    provenance,
    fetchedAt: Date.now(),
  };
}

export async function fetchGeographyResearch(
  query: GeographyResearchQuery,
): Promise<GeographyResearchResult> {
  const text = query.query.trim();
  if (!text) throw new Error("geography: empty query");
  if (!query.accessCode) throw new Error("geography: missing access code");
  const fetchFn = query.fetchFn ?? fetch;
  const url =
    `${GEOGRAPHY_PATH}?query=${encodeURIComponent(text)}` +
    `&lessonId=${encodeURIComponent(query.lessonId)}` +
    `&requestId=${encodeURIComponent(query.requestId)}`;
  const res = await fetchFn(url, {
    method: "GET",
    headers: { "x-tutor-code": query.accessCode },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`geography: gateway ${res.status}`);
  return normalizeResearchResult(await res.json(), query);
}

/**
 * The Screen's medium choice: a researched map asset when the gateway
 * returned an approved image URL, otherwise a generated SVG. Pure and
 * tested; downloading/hashing the image happens in `downloadAssetBytes`.
 */
export function selectGeographyVisual(result: GeographyResearchResult): GeographyVisual {
  const withImage = result.features.find((f) => f.imageUrl);
  if (withImage) return { kind: "researched", feature: withImage };
  return { kind: "generated" };
}

/** Bounded same-origin-or-https download for a researched image URL. */
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
  const res = await fetchFn(parsed.toString(), {
    headers: accessCode ? { "x-tutor-code": accessCode } : {},
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`asset-download: ${res.status}`);
  const buffer = await res.arrayBuffer();
  if (buffer.byteLength === 0 || buffer.byteLength > MAX_BLOB_BYTES) {
    throw new Error("asset-download: size out of bounds");
  }
  return new Uint8Array(buffer);
}
