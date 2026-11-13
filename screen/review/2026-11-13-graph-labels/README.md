# Graph label placement + overlap lint, 2026-11-13

Side/segment labels in `ot-graph` no longer cross their own stroke, and what is
still crowded becomes actionable lint instead of a silent overlap.

## What was wrong

`sideLabel` (`screen/shell/shell.js`) centred every label a fixed `1.05 * font`
out along the edge normal, ignoring the label's real width/height, and picked the
polygon side from the vertex mean — which sits in the notch of a concave shape.
Vertical `4 cm`/`3 cm` labels crossed their outline by 3–5 px, the slanted
`Vinkelben` by ~25/43 px, and two L labels went inside the material.

## What changed (shell only, no tags, no geometry)

- Outward per edge from the polygon winding (signed area; both vertex orders),
  not the vertex mean. Segment labels keep the above-the-line default.
- Reach-aware offset from the measured box: `(|nx|*w + |ny|*h)/2` plus a
  line/margin gap — the corrected two-axis clearance, never a dominant-axis guess.
- Auto ranges widen for the longest side label so labels fit inside the pane
  instead of being clamped back across their stroke. Author-set `x`/`y` win;
  leftovers become lint.
- Neighbour collisions: tangential nudge, segment side flip, never text
  shrinking. What cannot be placed cleanly is recorded per graph and emitted as
  `crowded: label ... use a shorter label, fewer figures or more room` — the
  existing bounded retry repairs from that wording. Lint is rebuilt after every
  final draw, so it describes the delivered page, never an intermediate fit pass.
- Point anchors, ticks, hidden/later labels and unrelated maths are untouched
  and never flagged. No length lint in this change.

## Evidence

- `inputs/` — the four unedited Hydrogen bodies from
  `review/2026-11-13-geometry/raw` (plan, vinkel, ratblock, cylinder).
- `../tools/check_graph_labels.py` — repeatable render + independent geometry
  recomputation at 370×610 and 1000×700. Fails on the prior shell
  (`--prior-ref HEAD`: 14 unreported defects — own-stroke crossings,
  inside-material labels, label-label overlaps), passes on this shell with every
  leftover flagged as `crowded` lint. `shots/results.json` has both runs;
  `shots/*-prior-*.png` are the before renders.
- `model/` — one fresh Hydrogen-low job on the research plan ask (7.7 s +
  5.4 s, both model calls under the 12 s target). First attempt crowded the
  notch (`labels '2 cm' and '2 cm' overlap by 17 px`); the bounded retry dropped
  one crowded notch label and delivered with zero residual lint.
  `model/patched-370x610.png`: restoring the dropped label via patch surfaces
  the same `crowded` lint in `patch_issues`; `ot.point` still finds both ids.

## What really improved, and what did not

- plan/vinkel/ratblock/cylinder: labels clear of their strokes at both sizes;
  CW and CCW L stay outside the material. `l-cw` is fully clean.
- Honestly still flagged: the plan notch (`'2 cm' and '1 cm' overlap`, 12–27 px —
  two 72 px labels cannot share a 63 px notch), one rect/L neighbour pair on the
  writer's tight layout at 1000×700, and `short-edges`' `diagonalen` at 370×610.
  These read as lint with the fix direction, not as clean pages.
- Limits: winding only fixes simple polygons; dense multi-figure pages still
  need the writer to separate figures or shorten labels; lint describes the
  delivered pane (the model page is clean at 370×610 but flags at 1000×700 —
  same body, wider font). No new layout engine, no shrunk text.

`check_fit` (incl. resize), `check_readability`, `check_sanitizer`,
`check_patch_history` and `check_map_key` pass on this shell.
