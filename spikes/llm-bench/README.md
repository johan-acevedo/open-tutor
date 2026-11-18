# spikes/llm-bench — global DeepSeek V4.1 Flash TTFT bake-off (2026-11-16)

Temporary rig. Compares, from 10 Globalping cities:
- **A**: Workers AI `@cf/deepseek-ai/deepseek-v4.1-flash-1017`, `reasoning_effort: "none"`
- **B**: Command Code `deepseek/deepseek-v4.1-flash`, `thinking: {type: disabled}`
- **C**: OpenCode Go `deepseek-v4.1-flash`, `thinking: {type: disabled}` + `x-opencode-session`

Backend as a **path segment** (`/bench/<a|b|c>`): Globalping percent-encodes `?`
in `request.path`, so query strings do not route. `run-global.py` resumes by tally
and backs off on 429 (anonymous quota is 250 tests/hr; 300-run A/B/C needs ~2 windows).

## Files
- `worker.js` + `wrangler.toml` — bench Worker (measures TTFT server-side).
- `direct-baseline.py` — 10 runs/backend direct from Sweden (no Worker).
- `run-global.py` — Globalping driver (needs deployed Worker).
- `direct-baseline.jsonl` — Sweden results, 2026-11-16 ~10:35 UTC.

## Deploy (needs a token with Workers Scripts:Edit on your Cloudflare account —
## a Workers-AI-only token CANNOT deploy)
```bash
cd spikes/llm-bench
export CLOUDFLARE_API_TOKEN="<token with Workers Scripts:Edit>"
export CLOUDFLARE_ACCOUNT_ID="<your-account-id>"  # from the Cloudflare dashboard
export BENCH_PATH="$(openssl rand -hex 16)"   # 32 hex chars, never commit the value
wrangler deploy
echo "$BENCH_PATH" | wrangler secret put BENCH_PATH
# keys come from an env file you keep outside the repo
#   AGENT_AUTH_ENV=/path/to/agent-auth.env
grep COMMAND_CODE_API_KEY "$AGENT_AUTH_ENV" | cut -d= -f2- | tr -d '\n' | wrangler secret put COMMAND_CODE_API_KEY
# smoke test (expect colo ARN from Sweden, reasoning_chars 0 on A):
curl "https://open-tutor-llm-bench.<your-subdomain>.workers.dev/$BENCH_PATH/bench?backend=a"
curl "https://open-tutor-llm-bench.<your-subdomain>.workers.dev/$BENCH_PATH/bench?backend=b"
```

## Run global probes
```bash
WORKER_BASE="https://open-tutor-llm-bench.<your-subdomain>.workers.dev/$BENCH_PATH" python3 run-global.py
# 10 cities x (A B A B x limit 5) = 200 probe runs; ~1 hr with polling
```

## Delete when done
```bash
wrangler delete open-tutor-llm-bench
curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/workers/scripts/open-tutor-llm-bench" \
  | head -c 300  # expect "workers not found" / success:false
```
