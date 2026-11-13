# Circle and positioned-text reference comparison

Five reference lines document a circle made from two supported function curves
and `ot-text` annotations without point markers. No runtime or tag change.
The final English reference was tested in its actual prompt position. Both new
Hydrogen-low pages are readable at 370×610 and 1000×700, with no lint or repair.

## Jobs and results

Synthetic asks only; generation pane 370×610. Every unedited body was rendered
at both sizes. Metadata, prompts, raw/delivered bodies, measurements and shots
are under `raw/<case>/`. The baseline reference is pinned to main `848f8c1`.

| Case | Generation | Look | Total | Result |
|---|---:|---:|---:|---|
| cirkel-bas | 7.21 s | — | 8.56 s | Correct circle, halves in two series colours |
| cirkel-ref | 3.50 | 2.06 | 6.72 | Correct circle, both halves cyan |
| vinkel-bas | 7.71 | — | 8.85 | Correct angle, extra anchor dots from point labels |
| vinkel-ref | 4.56 | capped at 3.35 | 9.00 | Correct angle, centred text removes those dots |
| vinkel-ref2 | 8.99 | — | 10.20 | More room between wide text and the leg endpoint |
| vinkel-ref patch | 5.20 | — | 6.46 | Existing ids replaced, labels moved, no patch issues |
| cirkel-final | 4.06 | 2.38 | 7.68 | Exact final English prompt; correct, one colour |
| vinkel-final | 4.08 | 3.17 | 8.36 | Exact final English prompt; correct, no extra dots |

Seven page jobs and one patch, twelve provider calls including four look calls
(one cut short). No lint retry or failure. This small, sequential sample does
not establish latency differences or failure rates.

Both circle arms already drew two square-root curves correctly: 8 units wide,
4 above and 4 below the centre, with a 4-unit radius and no calculated answer.
The earlier geometry batch invented `ot-circle`; that did not recur here.
The recipe documents a supported construction and gives both halves one colour;
this batch does not prove it prevents unsupported tags in general.

The angle rays draw 59.83°, consistent with the ask's rounded coordinates for
60°. The final annotation sits inside the wedge, clear of both legs. The wide
`Vinkelben` box is 8.4 px from the finite leg centreline on phone and 16.9 px on
wide. Both final pages use 17.5/30.25 px text. Parent inspected all four final
screenshots plus baseline, candidate and patch comparisons.

## Parent correction to the measurement

The worker reported 9/14 px overlap for v1 and 18/29 px for v2, and concluded
v2 was worse. Those were false positives. Projecting a rectangle's width onto
an infinite line's normal does not test intersection with a finite segment,
especially beyond its endpoint. The screenshots showed the text above the end.

`clearance()` now clips the finite segment against the text rectangle. Disjoint
geometry uses the minimum endpoint-to-box/corner-to-segment distance. The gap
excludes stroke thickness; it is a box-to-centreline measurement, not a glyph
or ink measurement. Zero means intersection. Corrected wide-label gaps:

| Arm | 370×610 | 1000×700 |
|---|---:|---:|
| baseline | 16.6 px | 28.8 px |
| v1 | 0.4 | 1.5 |
| v2 | 8.4 | 16.9 |
| patch | see `measure-after.json` | see `measure-after.json` |
| final English | 8.4 | 16.9 |

V1 is tight at phone size; v2 increases the gap. All measurements were rerun
without further model calls. The old projection's false positive is pinned by
`screen/tests/test_circle_text_measure.py`: it reports ~7.27 px overlap for a
box actually 5 px beyond an endpoint. The regression fails on the worker source
and passes with the corrected finite geometry.

## Scope and limits

- The original candidate arms used Swedish guidance, saved verbatim per folder.
  The final English wording is shorter and tested separately with the real
  prompt, not appended a second time. Hashes are in final-job metadata.
- `ot-text` is centred at graph coordinates, draws no marker, has no offset
  attribute or automatic line avoidance, and is clamped only into the graph box.
- Radius and vertex ids give visible pointing feedback. `ot-text` ids return
  true from `ot.point` but give no visible effect; the reference states that
  limitation. The patch keeps its ids and has no missing targets. Runtime
  pointing remains a separate fix; this PR does not claim all annotations point.
- No off-centre circles, arcs, sectors, tangents or constructions were tested.
  Two function halves supply a circle outline, not every circle-related task.
- This uses main's pre-PR56 shell. It does not judge PR56's side-label layout.
  No real child, production session, service restart or deployment was involved.

## Repeat

```sh
# Historical baseline/candidate comparison (paid model calls).
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env env \
  SCREEN_MODEL=gemini-4-hydrogen SCREEN_API=chat SCREEN_REASONING=low SCREEN_THINKING= \
  uv run --project server python screen/tools/probe_circle_text.py run \
  --out /tmp/circle-text --cases cirkel-bas,cirkel-ref,vinkel-bas,vinkel-ref,vinkel-ref2

# Exact current English reference in its actual prompt position (paid calls).
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env env \
  SCREEN_MODEL=gemini-4-hydrogen SCREEN_API=chat SCREEN_REASONING=low SCREEN_THINKING= \
  uv run --project server python screen/tools/probe_circle_text.py run \
  --out /tmp/circle-final --cases cirkel-final,vinkel-final

# Real patch follow-up (paid call).
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env env \
  SCREEN_MODEL=gemini-4-hydrogen SCREEN_API=chat SCREEN_REASONING=low SCREEN_THINKING= \
  uv run --project server python screen/tools/probe_circle_text.py patch \
  --dir /tmp/circle-text --case vinkel-ref

# Re-render saved evidence and a hand-written syntax probe, no model/key.
uv run --project server python screen/tools/probe_circle_text.py measure \
  --dir screen/review/2026-11-13-circle-text/raw
uv run --project server python screen/tools/probe_circle_text.py selftest \
  --out /tmp/circle-recipe
```

Chromium needs the shell's public CDN libraries/fonts; manual render commands
are not network-free CI tests. The pure geometry regression tests use no
network or key. Full configured server suite from `server/`: 432 passed, 18 skipped.
The three new pure geometry tests also pass separately.
