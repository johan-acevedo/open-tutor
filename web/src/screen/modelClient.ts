/**
 * Same-origin Screen model client (proof-proxy pattern).
 *
 * The browser never holds the provider key. Requests go to the FastAPI
 * service at `/api/screen/openai/{room}/chat/completions`, authed by the
 * existing in-memory family code sent as `x-tutor-code` — the same header
 * the web session endpoint already uses. The access code is passed per call
 * from controller options; it is never written to storage, and responses use
 * `cache: "no-store"` so no lesson record persists anywhere.
 */
import { SCREEN_MODEL_ID } from "./screenConfig";

export { SCREEN_MODEL_ID } from "./screenConfig";
export const SCREEN_CHAT_PATH = (room: string): string =>
  `/api/screen/openai/${encodeURIComponent(room)}/chat/completions`;

const MAX_TOKENS_CAP = 8192;

export interface ScreenChatRequest {
  room: string;
  accessCode: string;
  body: Record<string, unknown>;
  fetchFn?: typeof fetch;
}

function clampMaxTokens(body: Record<string, unknown>): Record<string, unknown> {
  const raw = body["max_tokens"] ?? body["max_completion_tokens"];
  if (typeof raw === "number" && Number.isInteger(raw) && raw > 0) {
    const capped = Math.min(raw, MAX_TOKENS_CAP);
    if ("max_tokens" in body) return { ...body, max_tokens: capped };
    return { ...body, max_completion_tokens: capped };
  }
  return { ...body, max_tokens: MAX_TOKENS_CAP };
}

/** POST one bounded chat-completions request. Throws on missing room only.
 * Public Swedish mode may run with an empty TUTOR_ACCESS_CODE: the backend
 * family_authorized() permits it, so never require a non-empty credential.
 * Always call same-origin; the code is sent as-is (possibly empty) and never stored. */
export async function postScreenChat(request: ScreenChatRequest): Promise<Response> {
  const room = request.room.trim();
  if (!room) throw new Error("screen-chat: missing room");
  const body = clampMaxTokens({ ...request.body, model: SCREEN_MODEL_ID });
  const fetchFn = request.fetchFn ?? fetch;
  return fetchFn(SCREEN_CHAT_PATH(room), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-tutor-code": request.accessCode,
    },
    body: JSON.stringify(body),
    cache: "no-store",
  });
}
