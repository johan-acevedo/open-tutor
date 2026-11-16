# Global LLM latency for a browser voice tutor (research, 2026-11-16)

**Question:** one streaming LLM call per conversational turn, possibly via a Cloudflare Worker.
Only **time to first token (TTFT)** matters. Users are worldwide (Sweden, US East/West incl. Arizona,
Sydney, Singapore/Tokyo). Which endpoint serves **Muse Spark 1.3 Contributor** and
**DeepSeek V4.1 (Flash/Pro)** fastest everywhere?

**Bottom line up front:**
- TTFT is dominated by provider-side prefill + reasoning (1–7 s), **not geography** (~0.1–0.3 s
  intercontinental delta). Pick the fastest provider, not the closest region.
- Fastest measured from Sweden: **Command Code Provider API** (`api.commandcode.ai`),
  DeepSeek V4.1 Flash content at **3.1 s med**, Muse Spark 1.3 (effort `minimal`) content at
  **2.8 s med**. OpenCode Go is 2–3 s slower on the same models.
- Sydney penalty on the same endpoint is estimated at **+0.1–0.3 s** vs Stockholm — inside
  run-to-run variance (p90–med is 2–6 s). Per-region routing in the Worker buys almost nothing
  unless you switch to a truly edge-routed backend.
- The one genuinely "near the caller" backend serving this exact model is **Cloudflare Workers AI**
  (`@cf/deepseek-ai/deepseek-v4.1-flash-1017`, $0.30/$1.20 per 1M) — worth a bake-off for Sydney,
  not yet measured (needs a Cloudflare account, no key was available).
- Set reasoning effort to **`minimal`/`low`** for voice turns. Defaults burn 250–400 reasoning
  tokens (≈2–4 s) before the first speakable token on both DeepSeek and Muse Spark.

**Lead re-check (2026-11-16, dell5500, 5 runs):** DeepSeek V4.1 Flash on Command Code chat completions with `"thinking": {"type": "disabled"}` gave content TTFT **median 1.48 s** (1.21–1.58 s), about half the default-mode 3.1 s. Note that Command Code returns 403 to Python's default User-Agent, so send a client User-Agent. On the chat endpoint, `reasoning_effort` (`minimal`/`none`) returned 400 for Muse Spark; the agent's Muse Spark numbers used the Responses endpoint.

All claims are either **measured** (command + output in §5) or **estimated** (formula in §2);
everything else links its source. Unknowns are stated plainly.

---

## 1. Measured from Sweden (dell5500, 2026-11-16)

Short prompt (~300 tokens in, `/1965909632` out target), streaming, 10 runs per cell.
"First token" = first SSE token of any kind (incl. opaque/reasoning).
"Content" = first speakable text token — **this is the number that matters for voice.**
Keys from `~/.pi/agent/auth.json` (never printed, logged, or sent to probe services).

| Endpoint | Model (effort) | DNS / TCP / TLS to edge | TTFT first-token med (p90) | **TTFT content med (p90)** | Total med | tok/s med |
|---|---|---|---|---|---|---|
| `api.commandcode.ai/provider/v1` (chat) | `deepseek/deepseek-v4.1-flash` (default) | 1.6 / 3.6 / 23.5 ms | 1.05 s (3.19) | **3.12 s (5.17)** | 3.55 s | 40.4 |
| `opencode.ai/inference/go/openai/v1` (chat) | `deepseek-v4.1-flash` (default) | 14.5 / 16.5 / 35.0 ms | 2.98 s (7.82) | **6.51 s (12.13)** | 7.71 s | 23.8 |
| `opencode.ai/inference/go/openai/v1` (chat) | `deepseek-v4-pro` (default) | 14.5 / 16.5 / 35.0 ms | 1.97 s (2.35) | **6.74 s (13.52)** | 7.24 s | 23.0 |
| `opencode.ai/inference/go/openai/v1` (chat) | `muse-spark-1.3-contributor` (`reasoning_effort: minimal`) | as above | 2.18 s (3.40) | **2.18 s (3.40)** | 2.42 s | 39.6 |
| `api.commandcode.ai/provider/v1` (responses) | `meta/muse-spark-1.3-contributor` (`reasoning.effort: minimal`) | 1.6 / 3.6 / 23.5 ms | 2.81 s (6.29) | **2.81 s (6.29)** | 3.60 s | 21.3 |

Notes (all measured):
- **DeepSeek thinks first.** Default mode is thinking-on
  ([DeepSeek docs](https://api-docs.deepseek.com/quick_start/pricing)).
  Reasoning prefix before content: ~2 s on Command Code, ~3.5 s on Go (gap between first-token
  and content columns). With `max_tokens` too small (120), *all* tokens are reasoning and content
  never arrives (`reasoning_tokens: 60/60`, `finish_reason: length`) — size the budget ≥400.
- **Muse Spark also reasons heavily by default.** Default effort burned all 400–512 output tokens
  on (partly encrypted) reasoning with zero content on both providers. `minimal` effort fixes it:
  ~250 reasoning tokens, then content. On Go chat completions the knob is `reasoning_effort`
  (top-level; nested `reasoning.effort` is rejected with 400); on Command Code Responses it is
  `reasoning: {"effort": ...}`. `low` still burned ~400+ reasoning tokens on the tutor prompt —
  use `minimal` for voice.
- **Go requires `x-opencode-session`** (else `400 MissingSessionID`) and sends
  `server-timing: gateway;dur=8, upstream;dur=2290` — i.e. ~8 ms gateway overhead, ~2.3 s upstream
  on that probe. Per the project brief the app identifies as `open-tutor/…` with one session per
  room; probes did the same. (See [BUILD-PLAN](../../BUILD-PLAN.md), [server/README](../../server/README.md).)
- Unauthenticated connect timings to other API front doors from Sweden (edge RTT only, no key
  used): `api.deepseek.com` TLS 87 ms / 401; `api.meta.ai` TLS 54 ms / 403 (bot check);
  `api.fireworks.ai` TLS 102 ms; `api.deepinfra.com` TCP 147 ms / TLS 300 ms — consistent with a
  US origin and **no EU edge** (see §2).

### Endpoint geography (Globalping, unauthenticated ping/HTTP — no keys sent)

Both gateway hostnames are **Cloudflare anycast**: single-digit-ms ping from every probe city,
`cf-ray` terminating at the local PoP. **Anycast TLS termination does not move the GPUs** —
it only moves the handshake.

| Probe city | `api.commandcode.ai` ping / cf-ray / TLS+TTFB | `opencode.ai` ping / cf-ray / TLS+TTFB |
|---|---|---|
| Sydney | 1.7 ms / SYD / 8+9 ms | 1.8 ms / SYD / 7+15 ms |
| Phoenix | 12.1 ms / LAX / 19+19 ms | 12.1 ms / LAX / 19+24 ms |
| Ashburn (US-East) | 0.7 ms / IAD / 10+14 ms | 1.0 ms / IAD / 10+18 ms |
| Frankfurt | 6.8 ms / FRA / 14+21 ms | 1.0 ms / FRA / 13+41 ms |
| Singapore | 1.1 ms / SIN / 12+17 ms | 2.0 ms / SIN / 10+18 ms |
| Tokyo | 1.6 ms / NRT / 12+10 ms | 1.1 ms / NRT / 12+12 ms |

More (ping avg, same method):
- `api.meta.ai` — anycast on Meta's own edge (Sydney 1.4, Phoenix 11.5, Ashburn 0.8, Frankfurt
  0.6, Singapore 1.2, Tokyo 1.3 ms; per-city IPs). Inference region undisclosed in
  [Meta Model API docs](https://dev.meta.ai/docs/overview) — **unknown**.
- `api.deepseek.com` — same IP worldwide (`3.173.21.63`), ~1 ms ping on 5/6 continents
  (Phoenix 54 ms): anycast front door (likely CDN), **origin unknown**, no key available so no
  TTFT measured.
- `api.fireworks.ai` — anycast edge (Frankfurt 0.9, Tokyo 1.6, Phoenix 11.6 ms).
- `api.together.xyz` — anycast edge (1–3 ms except Phoenix 54 ms).
- `api.deepinfra.com` — **not** anycast: Sydney 169, Singapore 191, Frankfurt/Tokyo 131,
  Ashburn/Phoenix ~49 ms → single US origin. Matches DeepInfra's disclosed footprint
  (8 US states + Toronto, no region pinning on serverless;
  [DCD](https://www.datacenterdynamics.com/en/news/deepinfra-deploys-ai-inference-cloud-in-toronto-canada-data-center/)).
- `api.novita.ai` — anycast/CDN edge where probes answered (1–3 ms).

## 2. Per-region TTFT: measured vs estimated

**Estimation formula (used for every non-Sweden cell below):**

> TTFT(region) ≈ TTFT(Sweden, measured) − RTT(Sweden→origin) + RTT(region→origin)

**Assumptions (stated plainly):** GPU origin is undisclosed for both Command Code and OpenCode Go,
so US origin is assumed (both are US gateway companies; their plausible upstreams — Together
default, DeepInfra, Fireworks GLOBAL — are US-anchored; `server-timing` shows ~2.3 s upstream vs
~25 ms edge). RTT legs used: Stockholm→US ~100 ms, Sydney→US ~150 ms, Phoenix→US ~40 ms,
Singapore/Tokyo→US ~130/110 ms. Therefore the geography term is **+0.05 s (Phoenix) to +0.25 s
(Sydney/Singapore) in the worst case, and ~−0.05 s for Frankfurt**. Queuing/prefill/reasoning
(1–7 s, p90 spread 2–6 s) are assumed region-independent — the standard assumption, and the
reason the Sydney rows barely differ from Stockholm.

| Model + endpoint | Stockholm (measured content med) | Phoenix (est.) | US-East (est.) | Sydney (est.) | Singapore/Tokyo (est.) |
|---|---|---|---|---|---|
| DeepSeek V4.1 Flash via **Command Code** | **3.1 s** | ~3.1 s | ~3.1 s | **~3.3 s** | ~3.3 s |
| DeepSeek V4.1 Flash via **OpenCode Go** | **6.5 s** | ~6.5 s | ~6.5 s | **~6.7 s** | ~6.7 s |
| DeepSeek V4 Pro via OpenCode Go | **6.7 s** | ~6.8 s | ~6.7 s | **~7.0 s** | ~6.9 s |
| Muse Spark 1.3 (`minimal`) via **OpenCode Go** | **2.2 s** | ~2.2 s | ~2.2 s | **~2.4 s** | ~2.4 s |
| Muse Spark 1.3 (`minimal`) via **Command Code** | **2.8 s** | ~2.8 s | ~2.8 s | **~3.0 s** | ~3.0 s |

Honest reading: the Sydney–Stockholm gap (≈0.2 s) is **an order of magnitude smaller than
provider choice** (CC vs Go ≈ 3 s on Flash) and than run-to-run variance (p90−med ≈ 2–6 s).
The "Pro" model is not faster than Flash for voice turns — both spend ~4–5 s in reasoning at
default effort. Only Sydney cell that is *measured*, not estimated: none — Sydney rows are
estimates; what *is* measured worldwide is edge RTT (table in §1), which bounds the geography term.

## 3. Landscape: "near the caller" inference providers

"Routing" = automatic (anycast/nearest) vs caller-pinned. "Sydney verdict" = is Sydney TTFT
meaningfully better than calling one US region (given TTFT ≈ seconds, RTT ≈ 0.1–0.3 s)?

| Provider | Regions (sources linked) | Routing | Muse Spark 1.3? | DeepSeek V4.1? | Comparable small/fast model + price/1M in/out | Sydney verdict |
|---|---|---|---|---|---|---|
| **Cloudflare Workers AI** | 180+ GPU cities claimed 2024 (unverified 2026); automatic nearest-GPU routing; [pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/), [models](https://developers.cloudflare.com/workers-ai/models/) | Automatic (nearest) | No (Llama, Kimi, GLM, Qwen) | **Yes: `@cf/deepseek-ai/deepseek-v4.1-flash-1017`, $0.30/$1.20** | Same model, $0.30/$1.20 | **Best structural bet for Sydney** — inference *can* run at edge; needs a bake-off (unmeasured here) |
| **Command Code Provider API** | Undisclosed infra (self-hosted GPUs + negotiated third-party capacity; [Go plan](https://commandcode.ai/docs/plans/go), [provider docs](https://commandcode.ai/docs/provider)) | Automatic (anycast edge; GPU origin unknown) | **Yes** `meta/muse-spark-1.3-contributor`, **$0.10/$0.20** | **Yes** `deepseek/deepseek-v4.1-flash`, **$0.15/$0.60** | — | Fastest measured; Sydney ≈ SE +0.2 s (est.) |
| **OpenCode Go/Zen** | Undisclosed; user reports: US-hosted with China opt-in for some DeepSeek models ([issue #39847](https://github.com/anomalyco/opencode/issues/39847)); front door on Cloudflare (measured) | Automatic (single logical endpoint) | **Yes** `muse-spark-1.3-contributor`, **$0.10/$0.20** | **Yes** Flash $0.15/$0.60, Pro $0.66/$1.98 | — | 2–3 s slower than CC from SE; Sydney ≈ SE +0.2 s (est.) |
| **DeepSeek official** (`api.deepseek.com`) | Undisclosed; anycast front door measured (§1); [data-residency analysis](https://n4n.ai/blog/deepseek-api-data-residency-china-vs-us-hosted-providers/) says China-served | Automatic | No | **Yes** `deepseek-flash` (=V4.1-Flash-1017), `deepseek-v4-pro`; peak **$0.30/$1.20**, off-peak $0.15/$0.60, cache-hit $0.006 ([pricing](https://api-docs.deepseek.com/quick_start/pricing)) | — | Unknown (no key; unmeasured). Cheapest off-peak |
| **Fireworks AI** | 30+ regions, multi-region default (GLOBAL/US/CANADA/EUROPE/APAC) or pinned; [regions](https://docs.fireworks.ai/deployments/regions), [blog](https://fireworks.ai/blog/multi-region-deployment) | Automatic (GLOBAL) or pinned | No | **Yes**, on-demand $0.30/$1.20, spot $0.21/$0.84 (via [OpenRouter](https://openrouter.ai/deepseek/deepseek-v4.1-flash)) | — | GLOBAL routing should match CC-class; unmeasured (no key) |
| **Together AI** | Serverless default (US) + `us-api.together.ai` geo-pin; dedicated EU incl. **Sweden infra live 2025** ([PR](https://www.prnewswire.com/news-releases/together-ai-continues-european-expansion-infrastructure-now-live-and-operational-in-sweden-302545683.html)); [serverless models](https://docs.together.ai/docs/serverless/models) | Caller-pinned or default | No (Muse-Glimmer only) | **Yes** `deepseek-ai/DeepSeek-V4.1-Flash-1017`, **$0.30/$1.20**, cache $0.006 ([pricing](https://www.together.ai/pricing)) | — | Default = US-like; EU dedicated possible on Scale/Enterprise (sales) |
| **Baseten** | 20+ clouds/regions; regional pinning via regional environments/deployments ([docs](https://docs.baseten.co/deployment/regional-environments), [changelog](https://www.baseten.co/resources/changelog/regional-deployments/)); Model API `deepseek-ai/DeepSeek-V4.1-Flash` ([changelog](https://www.baseten.co/resources/changelog/deepseek-v41-flash-available-on-baseten/)) | Caller-pinned or default cloud | No | **Yes**, ~$0.30/$1.20 (via OpenRouter) | — | Pinning helps residency, not TTFT much |
| **Novita AI** | 14 regions, 4+ continents (UAE/UK/India/Brazil added 2025; [blog](https://blogs.novita.ai/gpu-regions-zones/)); serverless LLM + GPU cloud | Automatic edge (measured 1–3 ms) + region select for GPUs | No | **Yes**, ~$0.195/$0.78 (via OpenRouter) | — | Edge front door local; GPU city unknown |
| **GMI Cloud** | Silicon Valley, Colorado, Taiwan, Thailand, Malaysia + JP 1 GW project ([provider profile](https://www.subconscious.dev/providers/gmi-cloud)); "region-pin endpoints" ([Prime Inference](https://www.gmicloud.ai/en/models/prime-inference)) | Caller-pinned | No | **Yes**, ~$0.18/$0.72 (via OpenRouter) | — | Taiwan/SG-adjacent DCs best APAC option on paper; unmeasured |
| **DeepInfra** | 9 DCs: 8 US + Toronto ([DCD](https://www.datacenterdynamics.com/en/news/deepinfra-deploys-ai-inference-cloud-in-toronto-canada-data-center/)); no serverless region pinning | Single-region (US) | No | **Yes**, from ~$0.112/$0.336 (via OpenRouter) | — | **No**: Sydney ≈ US +170 ms RTT even before inference (measured) |
| **Modal** | Multi-cloud containers; routing region selectable, default via `us-east` ([docs](https://modal.com/docs/guide/region-selection.md)) | Caller-selected routing region | No | **Yes** (serverless model APIs), ~$0.30/$1.20 (via OpenRouter) | — | Only helps if you pin APAC compute yourself |
| **Parasail** | 26 DCs / 15 regions claimed ([blog](https://www.parasail.io/blog/parasail-vs-deepinfra)) | Dedicated endpoints (pinned) | No | **Yes**, ~$0.30/$1.20 (via OpenRouter) | — | Paper footprint only; unmeasured |
| **AWS Bedrock** | Cross-region inference profiles, DeepSeek-R1 US-only (`us.*` profile; [docs](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-deepseek-deepseek-r1.html)); no V4.x found | Caller-selected profile | No | **No (R1 only, no V4/Flash found)** | R1 via `us.deepseek.r1-v1:0` | US-only for DeepSeek; no Sydney win |
| **Azure AI Foundry** | Global Standard routes worldwide automatically; Data-Zone/EU pins for residency ([docs](https://learn.microsoft.com/azure/ai-foundry/foundry-models/concepts/deployment-types)) | Automatic (Global) or pinned | No | **No (V3.2/R1 only; no V4.1 found)** ([catalog](https://ai.azure.com/catalog/publishers/deepseek)) | DeepSeek-V3.2/R1 | No V4.1 to route |
| **Google Vertex AI** | MaaS `deepseek-v4.1-flash-maas` ([docs](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/maas/deepseek/deepseek-v41-flash)); regions per model card; ~$0.30/$1.20 via OpenRouter | Caller-selected region | No | **Yes (MaaS)** | — | Regional endpoints exist; unmeasured |
| **Alibaba Model Studio** | Per-region endpoints incl. Singapore, Frankfurt, Beijing ([docs](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/deepseek-api)); id `deepseek-v4.1-flash`, own pricing | Caller-pinned per region | No | **Yes** | — | Frankfurt/Singapore pins possible; unmeasured, China-terms caveat |
| **Vercel AI Gateway** | `us`/`eu`/`global` inferenceRegion pins where providers support ([docs](https://vercel.com/docs/ai-gateway/security-and-compliance/regional-inference)); auto provider ordering | Automatic or pinned | Ember/Spark-1.1/1.2 via gateway (no 1.3 seen) | **Yes** via 16 providers incl. DeepSeek direct | — | Gateway adds a hop; pinning is residency, not speed |
| **Groq** | 13 DCs (Liberty Lake, St Paul, Dallas, Houston, Kamloops, Vaudreuil-Dorion, Calgary, Vantaa, **Sydney**, London, Riyadh; [gpuclouds](https://gpuclouds.fyi/us/global/open/groq), [raise](https://groq.com/newsroom/groq-raises-usd650m-to-scale-its-ai-inference-cloud-business)) | Automatic | No | **No (R1 distills only; [models](https://console.groq.com/docs/models))** | gpt-oss-120B ~$0.075/1M, ~500 t/s | Obsolete Q for this model choice; Sydney DC exists but no V4.1 |
| **Cerebras** | US + France + Nordics DCs ([rcrwireless](https://rcrtech.com/ai-infrastructure-news/cerebras-dc-ai-demand/)); [shared catalog](https://inference-docs.cerebras.ai/models/overview) | Automatic (shared) | No | **No (R1/Llama/Qwen on shared)** | R1-70B-class at ~1,500 t/s claims | No V4.1; EU DCs don't help this pick |
| **SambaNova** | US + Japan (SoftBank; [press](https://sambanova.ai/press/sambanova-expands-deployment-with-softbank-corp-fast-ai-inference-apac)); OVH/EU via partner | Automatic | No | **Unknown (R1-671B US-hosted; no V4.1 evidence)** | — | Unmeasured; no V4.1 evidence |
| **Akamai Inference** | Closed beta Oct 2026; "AI Grid" across edge/regional/core ([press](https://www.akamai.com/newsroom/press-release/akamai-launches-ai-grid-intelligent-orchestration-for-distributed-inference-across-4400-edge-locations)); 12-model launch catalog (no DeepSeek listed) | Automatic (when GA) | No | **No evidence** | gpt-oss/Gemma/Nemotron class | Watch; not usable now |
| **Fastly** | Edge PoPs worldwide, but **no GPU inference hosting** — semantic cache + DIY gateway ([accelerator](https://www.fastly.com/products/ai-accelerator), [gateway guide](https://www.fastly.com/blog/building-an-ai-gateway-on-fastly-compute)) | N/A (cache/gateway) | No | No | Caching only | No |
| **Fly.io GPUs** | **Product killed 2026-08-01** ([post-mortem](https://bex.co/blog/2026/09/14/fly-io-killing-gpus-migration)) | — | — | — | — | Not an option |

DeepSeek V4.1 provider count: official + Command Code + OpenCode Go + Fireworks + Together +
DeepInfra + Baseten + Novita + GMI + Modal + Parasail + Vertex + Alibaba + Vercel-gateway +
OpenRouter-long-tail (Wafer, inference.net, CoreWeave, DigitalOcean, SiliconFlow, Baidu, …)
([full list](https://openrouter.ai/deepseek/deepseek-v4.1-flash), [Vercel](https://vercel.com/ai-gateway/models/deepseek-v4-1-flash)).
"Pro" = official `DeepSeek-V4-Pro-0813` (1.6T/49B-active; [GA notes](https://api-docs.deepseek.com/news/news260813.md));
no "V4.1-Pro" name exists — vendors' "Pro" is V4-Pro.

## 4. Recommendation (global user base)

1. **Primary endpoint: Command Code Provider API.**
   Fastest measured TTFT for both models from Sweden (Flash content 3.1 s vs Go 6.5 s;
   Spark-min content 2.8 s vs Go 2.2 s — a wash on Spark, but CC wins big on Flash and on
   decode speed 40 vs 24 tok/s). Cheapest too (Spark $0.10/$0.20; Flash $0.15/$0.60, and CC
   claims ~95–98% cache-hit serving). Single endpoint worldwide.
2. **Model: Muse Spark 1.3 with `reasoning.effort: minimal`** for voice turns
   (content TTFT ~2.2–2.8 s SE, ~2.4–3.0 s Sydney est.). Default effort adds seconds of silent
   reasoning before anything speakable. Keep Flash as fallback (content ~3.1 s SE). Skip Pro
   for voice — same-or-worse TTFT at 4–13× the price.
3. **Do not build per-region routing in the Worker for TTFT reasons.** Expected Sydney TTFT ≈
   Stockholm +0.1–0.3 s; Phoenix ≈ Stockholm ±0.1 s. That is noise next to 2–6 s p90 spreads.
   Route decisions should be about residency/price, not speed. (Your Worker already runs at the
   edge nearest the user — that only removes the *Worker→browser* leg, which was never the
   problem; the LLM call dominates.)
4. **If Sydney TTFT must drop below ~2 s**, the only structural fix on this model list is an
   edge-routed backend: run the bake-off on **Cloudflare Workers AI**
   (`@cf/deepseek-ai/deepseek-v4.1-flash-1017`) from Sydney/Singapore probes with a real account,
   and/or trial **Together dedicated EU** (Sweden infra exists) for EU users if residency work
   demands it. Fireworks GLOBAL is the other automatic-routing candidate worth measuring.
5. **Caveats:** Sydney/Phoenix/Singapore/Tokyo TTFT rows are *estimates* (± formula in §2), not
   measurements — no key may leave this machine, so probes only did unauthenticated timing.
   GPU origins of Command Code and OpenCode Go are undisclosed; if either is EU-based, Sydney
   penalty grows (~+0.3 s, still small). Re-run the 10× Sweden suite after any model-version
   bump (`-1017` etc.) — versions move fast (Flash was upgraded 2026-10-17).

## 5. Appendix — every command (secrets redacted; keys never left `auth.json`)

```bash
# connect timings to each front door (no auth; edge TLS termination only)
for h in api.commandcode.ai opencode.ai api.deepseek.com api.meta.ai \
         api.fireworks.ai api.deepinfra.com; do
  curl -s -o /dev/null \
    -w 'dns=%{time_namelookup} tcp=%{time_connect} tls=%{time_appconnect} total=%{time_total} code=%{http_code}\n' \
    --max-time 15 "https://$h" -H "User-Agent: Mozilla/5.0 ..."
done
# cf-ray edge PoP of the gateways from Sweden (authenticated 404s still show the edge)
curl -sI https://api.commandcode.ai/provider/v1 -H "User-Agent: Mozilla/5.0 ..."  # cf-ray ...-ARN
```

```python
# TTFT harness (full: /tmp/ttft.py in the research session; sketch of the core loop)
# key = json.load(open(os.path.expanduser("~/.pi/agent/auth.json")))["commandcode"]["key"]  # REDACTED
req = urllib.request.Request(url, data=json.dumps({
    "model": "deepseek/deepseek-v4.1-flash",
    "messages": [{"role": "user", "content": PROMPT_300TOK}],  # ~300 in, 400-600 out budget
    "max_tokens": 400, "stream": True,
    # go chat only: "reasoning_effort": "minimal"; cc responses only: "reasoning": {"effort": "minimal"}
  }).encode(), headers={
    "Authorization": "Bearer " + key,            # REDACTED at runtime, never logged
    "Content-Type": "application/json", "Accept": "text/event-stream",
    "User-Agent": "Mozilla/5.0 ...",             # go calls: "open-tutor/0.0.0 (latency-probe)"
    "x-opencode-session": "latency-probe-<uuid>",# go calls only (400 MissingSessionID otherwise)
})
t0 = time.perf_counter()
with urllib.request.urlopen(req, timeout=120) as r:   # Cloudflare 1010 blocks default python UA
    for raw in r:                                      # ...so a browser UA is required
        # first SSE data token w/ reasoning_content|reasoning_details|role → TTFT(first)
        # first delta.content (chat) / response.output_text.delta (responses) → TTFT(content)
python3 ttft.py cc-ds      # 10 runs
python3 ttft.py go-ds      # 10 runs (needs x-opencode-session; first attempt w/o it: 10×400)
python3 ttft.py go-pro     # 10 runs
python3 ttft.py go-spark   # 10 runs, reasoning_effort=minimal, max_tokens=600
python3 ttft.py cc-spark   # 10 runs, reasoning.effort=minimal, max_output_tokens=600
```

```python
# Globalping, unauthenticated (free tier 250 tests/hr; NO keys sent — ping/HTTP-HEAD/DNS only)
# POST https://api.globalping.io/v1/measurements
{"type": "ping", "target": "api.commandcode.ai", "locations": [
  {"country": "AU", "city": "Sydney", "limit": 1}, {"country": "US", "city": "Phoenix", "limit": 1},
  {"country": "US", "city": "Ashburn", "limit": 1}, {"country": "DE", "city": "Frankfurt", "limit": 1},
  {"country": "SG", "city": "Singapore", "limit": 1}, {"country": "JP", "city": "Tokyo", "limit": 1}],
 "measurementOptions": {"packets": 3}}
# repeated for targets: opencode.ai, api.meta.ai, api.deepseek.com,
#   api.fireworks.ai, api.together.xyz, api.deepinfra.com, api.novita.ai
# {"type": "http", ... "measurementOptions": {"protocol": "HTTPS", "port": 443,
#    "request": {"method": "HEAD", "path": "/"}}}   # → cf-ray colo + TLS/TTFB per city
# {"type": "dns", "target": "api.meta.ai" | "api.deepseek.com", ...}  # per-city A records
# GET https://api.globalping.io/v1/measurements/<id>  # poll to status=finished
```

Raw probe outputs kept in the research session (`/tmp/gp*.json`, `/tmp/ttft*.log`); the medians
and p90s above are computed over the 10 runs shown there.
