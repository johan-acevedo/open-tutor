# Concurrent candidate reviews, live comparison 2026-11-18

Same scripted page body (one `<ot-image query>` slot, phone pane 370×610) and the
same dev settings (`SCREEN_IMAGES=commons+parallel`, Gemini 4 Hydrogen low) under
two checkouts: `before` = `origin/main` (`a2685c1`, candidates downloaded and
vision-reviewed one after another) and `after` = `t3/concurrent-image-reviews`
(the top candidates reviewed at once, `SCREEN_IMAGE_REVIEWS=3`). Real Commons
and Parallel fast searches, real bounded downloads, real vision review, real
shell render. `compare.py` streams the page so the prefetch pool resolves the
slot while "writing", as in production; eight fictional asks, two runs each.

Reproduce:

```
git worktree add /tmp/open-tutor-before origin/main
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env \
  OPEN_TUTOR_REVIEW_ROOT=/tmp/open-tutor-before \
  uv run --project /tmp/open-tutor-before/server \
  python screen/review/2026-11-18-concurrent-reviews/compare.py before
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env \
  uv run --project server python screen/review/2026-11-18-concurrent-reviews/compare.py after
uv run --project server python screen/review/2026-11-18-concurrent-reviews/summarize.py
```

## Headline

| | before (`origin/main`) | after |
|---|---|---|
| Runs that shipped a picture | 11 / 16 (69 %) | **12 / 16 (75 %)** |
| Median image slot time | 4.74 s | 4.86 s (+0.12 s) |
| Slowest image slot | 15.31 s | 15.05 s |
| Runs the 17 s image budget cut | 5 | **1** |
| Completed vision reviews | 22 | 34 (≈1.5×) |
| Reviews cancelled by a decision | 5 | 18 |

The wait costs about a tenth of a second on the happy path (the winners are
still first-ranked, so the slot does not wait for the rest) and roughly half a
vision call per slot, because the second and third candidates are now judged
even when the first is accepted. What it buys is the case that actually bit us:
budget-cut runs fell from five to one.

## Per ask (two runs each; image slot seconds, recorded candidate events)

| Ask | before | after |
|---|---|---|
| Portrait of Gustav II Adolf | accepted `File:Gustav II Adolf of Sweden.jpg` (7.56 s / 4.69 s, 1 event each) | same file (5.42 s / 4.31 s, 3 events) |
| Portrait of Gustav Vasa | accepted `File:Gustav Vasa.jpg` (2.62 s / 2.02 s, 1) | same file (2.76 s / 2.61 s, 3) |
| Colosseum | accepted `File:Photo of The Colosseum in Rome, Italy.jpg` (3.09 s / 4.22 s, 1) | same file (4.17 s / 2.41 s, 3) |
| Roman Empire map | accepted `File:Roman empire at its greatest extent.JPG` (3.19 s / 3.43 s, 1) | same file (3.35 s / 3.44 s, 3) |
| Swedish Empire 1658 | accepted `File:LocationSwedishEmpire.png`, then **text fallback** (4.03 s, 1 / 15.31 s, 2 — the second review never fit) | same file both runs (6.11 s / 4.62 s, 3) |
| A flower | accepted `File:Tulip Tulipa clusiana 'Lady Jane' …` (4.89 s / 4.78 s, 1) | same file (5.09 s / 6.66 s, 3) |
| Dandelion in bloom (åk 4) | text fallback (15.3 s with 2 and 4 events: the good candidate was never reached) | text fallback (12.67 s / 11.59 s, **5 events: all three Commons and both Parallel candidates judged**) |
| Water cycle | text fallback (15.3 s, 4 events) | text fallback (6.63 s, 3 / 15.05 s, 3 — one Parallel review ran past the reserve) |

## What this says

- **The failure the change targets is gone in the run that hit it.** The
  Swedish Empire map's second `before` run judged two candidates, ran out of
  the 17 s budget and fell back to text; `after` judged three and accepted the
  same Commons file in 4.62 s. The dandelion ask shows the other half: five
  candidates judged instead of two to four, in less time than before, and the
  verdicts are informative (butterfly on the flower, B&W seed head, seed ball,
  one Parallel image "corrupted and mostly grey") instead of "we never looked".
- **Preference order held in every run.** Where Commons ranked a good picture
  first, the accepted file is identical to `origin/main` in both modes; no
  lower-ranked Parallel picture displaced a Commons one.
- **The water-cycle illustrations are genuinely bad, not a concurrency bug.**
  Both checkouts reject the same three Parallel files (`Vattnets Kretslopp för
  Skolo`, 17–21 kB) as cropped or mostly grey, and the earlier comparison's
  accepted USGS illustration did not come back from the search today. Worth a
  separate look at what Parallel serves for PDF-derived diagrams; nothing about
  it is new here.
- **Cost.** Every slot now spends up to three (Parallel phase: up to three
  more) vision calls instead of stopping at the first acceptance, bounded by
  the same deadline; a slot's best-ranked review keeps the hedge, the rest run
  as single attempts, so a page with an armed backup spends at most N+1 calls
  per phase instead of 2N. `SCREEN_IMAGE_REVIEWS=1` restores `origin/main`'s
  sequential behaviour exactly.
- **Not tested live:** a real lesson with a child, and the multi-slot case
  (the per-page gate that keeps two slots from doubling concurrent reviews is
  unit-tested, not measured here). No page failed in any run; no Parallel
  cool-down triggered.

Per-run folders hold `body.html`, `shot.png`, `images.json` (per-candidate
source, rank, decision, reason, download/review/finish times) and `row.json`;
each run's own `meta.json` carries the same under `images`, including
`review_concurrency`.
