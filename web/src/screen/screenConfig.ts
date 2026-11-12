/**
 * Browser-owned Screen model configuration — the single source of truth.
 *
 * Both the same-origin chat path (`modelClient.ts`) and the Pi Durable worker
 * (`screen.worker.ts`) report and use these values, so the Sessionsinfo panel
 * shows the actual model and reasoning level instead of a duplicated guess.
 * Dependency-free so the module Web Worker can import it.
 */

export const SCREEN_MODEL_ID = "deepseek-v4.1-flash";

export const SCREEN_THINKING_LEVEL = "low" as const;

export type ScreenThinkingLevel = typeof SCREEN_THINKING_LEVEL;
