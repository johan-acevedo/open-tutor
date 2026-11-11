// Loaded explicitly for this app's board requests.
export default function (pi) {
  pi.on("before_provider_request", (event) => {
    const raw = process.env.BOARD_MAX_TOKENS;
    const parsed = raw === undefined || raw === "" ? 16384 : Number(raw);
    if (!Number.isFinite(parsed) || parsed <= 0) return undefined;
    const cap = Math.floor(parsed);
    const payload = event.payload;
    if (payload === null || typeof payload !== "object") return undefined;
    let changed = false;
    const next = { ...payload };
    for (const key of ["max_tokens", "max_completion_tokens"]) {
      const current = next[key];
      if (typeof current === "number" && current > cap) {
        next[key] = cap;
        changed = true;
      }
    }
    return changed ? next : undefined;
  });
}
