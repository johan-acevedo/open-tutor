# Browser-owned Pi Durable screen — technical proof

Isolated proof that a **Pi Durable session can live in the learner's browser**
(IndexedDB), prepare exercises with a live model, gate answers behind a fox
command, keep a page deck with child input, survive close + reopen, and show
the fox the actual visible pixels.

It does **not** touch production code. Everything lives under
`experiments/browser-screen/`.

## What was proven (all scripted, all green)

`node scripts/verify.mjs` → **15/15 PASS** against the real served app with
live models (2026-11-11):

- worker boots a browser-owned session (`IndexedDbStorage("open-tutor-proof-v1")`, same conversation `samtal 1` across reopen)
- live model (`deepseek-v4.1-flash` via proxy) prepares Swedish exercises
- fox reveal is bound to **page id + revision**: current page reveals, stale
  commands rejected, duplicates ignored
- child input preserved across page switches AND after full browser close + reopen
- live vision describes the **actual canvas PNG**: sees question, child input,
  and whether facit is shown (`15` visible) vs hidden (`··· dolt ···`)

## Architecture

```
Learner's browser (owns everything durable)
  page (pixels) <-> screen worker (Pi Durable Harness + IndexedDB)
                          |  same-origin /api/proxy/openai
                          v
Tiny local proxy (loopback only) -> upstream inference
  forwards bounded chat requests, holds the provider key + session header,
  persists NOTHING (no transcripts, exercises, images, uploads)
Fox: simulated command box ("visa svaret") + REAL live vision read of the
rendered board. No voice integration in this proof.
```

- Session/model: `@earendil-works/pi-durable` **1.5.2** (pinned), IndexedDB adapter.
- Narrow tool: `prepare_page(topic, question, solution)` only. No shell/files.
- Pages: deck with immutable revision ids, per-page input + reveal state.
  The model can also read the board PNG back (vision round-trip).

## Run it

```sh
cd experiments/browser-screen
npm install                              # pinned 1.5.2 packages + dev tools
npm run build && npm run typecheck      # build = `vite build app`, typecheck = `tsc -p app`
npm test                                 # proxy bounds (node --test tests/*.test.mjs)
node scripts/verify.mjs                  # full proof, fresh tmp profile
cat verification/result.json           # aggregate result (committed)
```

Service (installed out of repo, logs out of repo):

```sh
cp deploy/open-tutor-proof.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now open-tutor-proof.service
# isolated tailscale route — leaves the existing 443/8443 serve routes alone:
tailscale serve --bg --yes --https 9443 http://127.0.0.1:9773
```

Open `https://dell5500.tail2e1c4e.ts.net:9443/` (tailnet) and enter the page
code from `~/.config/open-tutor-proof/env` (`PROOF_TOKEN`, mode 600, never in repo).
`PROOF_SELF_ORIGINS` in the unit must match the public origin or the proxy
rejects browser `Origin` headers. `public/` is build output (git-ignored);
screenshots on failure go to `/tmp`, never the repo.

## Things found while proving (all fixed except the last)

1. Upstream needs `x-opencode-session` — proxy sets it (was HTTP 400 `MissingSessionID`).
2. Pi sends `max_tokens: 384000` by default — proxy **clamps** to 8192 instead
   of rejecting (bounds spend, keeps the agent working).
3. Assistant tool-call turns use `content: null` — validator allows it when
   `tool_calls`/`tool_call_id` present.
4. `provider` must be overridden on the proxied model or requests dispatch to
   the wrong provider (`no API implementation for "undefined"`).
5. `locks.request()` never resolves while the callback holds the lock — the
   worker probes a flag instead of awaiting it (boot deadlocked before this).
6. Error text was cleared by a trailing empty status — failures now surface.
7. Answer box kept the previous page's text while focused — it now follows page id.
8. **NOT fenced (open work):** a second tab is supposed to open read-only via
   Web Locks, but HeadlessChrome 158 granted `ifAvailable` requests even with
   the lock demonstrably held (plain requests correctly wait). Verified
   2026-11-11. Until there is a real leader election, **use one tab** — two
   owners would both write the same IndexedDB (Pi requires one writer).

## Simulated vs real

Real: Durable session, IndexedDB persistence, live exercise generation, live
vision read of rendered pixels, page deck, revision-bound reveal rules.
Simulated: the fox (labelled command box + vision prompt, no voice/room), the
lesson context (typed topic, no uploads/transcript yet).

Next: real leader election, fox/room integration, uploads + transcript into the
lesson record, export/import for backup.

## Latest verification run

`node scripts/verify.mjs` writes `verification/result.json` (aggregate,
committed): per-step PASS/FAIL plus `gaps` for known-open items. Reference
run 2026-11-12 on dell5500, live `opencode-go/deepseek-v4.1-flash`:
**15/15 checks green**, same conversation `samtal 1` across full browser
close/reopen, vision described the visible revealed page ("Sida 1 av 2"
with shown facit) and the hidden page correctly. The script also probes
second-tab fencing and records it under `gaps` without failing the run
(item 8 above — second tab wrongly shows owner on this Chromium).
