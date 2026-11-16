# Loading overlay + streaming image prefetch (2026-11-16)

Same PR as the reveal-mode / screen-status work: when the learner switches
subject, the fox dims the old page and shows "Laddar <ämne>…" at once, and
image search + download + vision review now runs while the page model is still
writing instead of after its full text arrives.

## Loading overlay

- `screen/shell/shell.js`: `ot.loading(topic)` creates `#ot-loading`, a fixed
  veil (dim + slight blur) with a pill carrying a spinner and the Swedish
  label `Laddar <topic> …`. The topic travels as `textContent`, never HTML
  (checked: `<img onerror>` in the topic stays inert text, nothing executes).
  Empty topic clears. A successful `ot.patch` clears a stale veil by itself.
- `screen/shell/shell.css`: veil, pill, spinner (`ot-spin`; disabled under
  `prefers-reduced-motion`), dark-theme tokens only.
- Browser: new `board.loading` RPC (`{id, topic}`, empty clears), validated in
  `web/src/validate.ts`, forwarded to the mounted frame in `useSession.ts`
  (also unregistered on teardown), `PageShellMessage` gains the `loading`
  variant. Documented in `docs/protocol.md` next to the previously undocumented
  patch/reveal/point RPCs.
- Server: `SmartTutor.screen_loading(topic)` (empty clears);
  `screen_failed` best-effort clears a stale veil so no "Laddar …" survives a
  failed job.

Screenshots (real shell, example page `klockan.html`, `check_loading.py`):

- `klockan-loading-370x610.png` / `klockan-loading-1000x700.png`: dimmed page
  with the "Laddar historia …" pill, phone and wide.
- `klockan-cleared-370x610.png` / `klockan-cleared-1000x700.png`: after clear
  + patch (patch auto-clear path).

## Streaming image prefetch

- `screen/tools/page_images.py`: `complete_slots()` parses the streamed HTML
  incrementally and reports only fully closed `<ot-image>` elements (attrs plus
  child labels, which the vision review judges). `prepare()` and the new
  `prepare_deferred()` consume finished prefetches by the existing slot key
  (`query|src`, `alt`); `used_keys` records what the final page consumed.
- `server/open_tutor/screen.py`: `PrefetchPool` feeds on every attempt's
  streamed text (`on_text` through the model-call stack into the real
  `responses`/`chat` delta loops). Tasks are shared by slot key, so a hedged
  or raced second attempt never pays for a review twice; the winner's
  `discard_except()` cancels the loser's unique slots at decision time, and
  `finish()` cancels the rest at job end through the existing reaper bound.
  Fakes without `on_text` behave exactly as before (no prefetch, inline
  resolve afterwards).
- Show first, fill when approved: `prepare_deferred()` substitutes the text
  fallback for in-flight slots with an id and returns them as `pending`. After
  the page is on screen, `_fill_pending_images` awaits the approvals (bounded:
  10 s to appear, 10 s per slot, 20 s total) and delivers all approvals as one
  `<ot-patch>` with one preview render. Rejected reviews, missing targets
  (lint retry changed the slot away) and failed previews are dropped quietly;
  a held or superseded page never fills. Fills are `PatchResult(quiet=True)`
  so a failed fill is a context note, never a spoken apology.

## Timings (synthetic fakes, same 0.6 s write + 0.6 s review sleeps both sides)

- Sequential (no streaming): image visible in first paint at **1.21 s**.
- Streaming with prefetch: review overlaps the write; first paint at 0.6 s
  (fallback), approved image filled at **0.61 s**.
- Real-provider review calls take several seconds, so the overlap on a live
  job is the whole review, not 0.6 s; the first paint additionally never waits
  for it at all.

## Tests

- `server/tests/test_screen.py`: prefetch starts mid-stream (search observed
  before the stream ends), two slots review concurrently (sequential would
  deadlock), raced loser's unique slot is cancelled mid-review while the
  winner's fills in, lint-dropped slot fills nothing, `complete_slots` unit
  tests, prefetch-beats-sequential timing assertion.
- `web/src/validate.test.ts`: `board.loading` accept/reject cases.
- `screen/tools/check_loading.py`: shell assertions above + these PNGs.

## Not tested

- No live provider calls and no real session in this change: prefetch against
  real Commons + a real review model, and the fill patch arriving mid-lesson,
  still need one live lesson on the dev setup.
- A page whose model streams malformed HTML (an `<ot-image>` that never
  closes): the slot never completes, resolves inline at prepare as before.
- Fill races with a tutor-asked patch to the same target: both are plain
  patches; last applied wins, same as two quick patches today.

## Review follow-ups (same PR)

- Slot keys are full slots (every attribute + child labels); the pool returns
  only `SlotDecision`, and `PageImages.render` builds every HTML from the
  served slot. A resolved body re-prepares without re-review via `rendered`
  (exact full slot identity of our own output, no `query`).
- Image deadline = job start + limit − render reserves (about 17 s).
- Delivered patches record target ids per page (`_page_touched`); fills drop
  touched or vanished slots. Patch history is per page id; the fill
  re-checks visibility after its preview render.
- `aclose` finishes the pool through the reaper bound; held-ready and
  auto-show clear the veil (`SmartTutor._clear_loading`).
