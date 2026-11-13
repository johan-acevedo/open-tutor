# Qualified length lint for measured plane polygons

**Design statement.** The lint answers one question on an explicitly to-scale
plane figure: do the drawn side lengths agree with the numbers in their
labels, independent of absolute drawing scale? Its inputs are the two things
the writer already declares: `ot-polygon points` (graph-unit coordinates) and
`sides` (one label per edge, A→B→C…). It computes exact Euclidean edge lengths
in graph units — exact geometry, not projected pixels; `ot-graph` enforces
equal units unless `free` — parses each label strictly as `NUMBER UNIT`
(mm/cm/dm/m, decimal comma or point), converts to millimetres, and compares
the implied scale (drawn ÷ labelled) of every known side against the figure's
own median scale. A side more than 15% off is flagged with its polygon, side
number, label text and direction (shorter/longer); with exactly two known
sides there is no majority to direct, so both sides are named jointly without
direction. Anything that is not an unambiguous length claim is an unknown and
stays quiet: `?`, algebra, angles, areas, bare numbers, TeX, word measures,
mixed-dimension markers, fewer than two known sides, missing/degenerate/
non-finite coordinates, `ot-segment` labels (foreshortened 3D edges live
there), `free` graphs, `schematic` figures and invisible (unrevealed) answers.
The message quotes the model's own label and gives a correction direction
(check the label or redraw the side) but never states a target value, so a
child's unknown result cannot leak through a retry.

**Tolerance (15%).** Model coordinates carry at most ~1 decimal; the absolute
edge error is then ≲0.1 graph units, and a labelled edge is at least ~1 unit
long in practice (a label must fit beside it — tighter cases already earn
`crowded`), so rounding contributes ≲10%. 15% sits above that and below the
smallest genuine label slip: one unit off on a school figure of a few units is
17–25% (the canonical 4-vs-5 is 20%). Residual risk, stated not solved:
sub-unit labelled edges with coarse coordinates could false-positive; the
`ok-small` probe pins current behaviour (quiet), and narrowing (not a bolder
threshold) is the cure if evidence ever shows otherwise.

## Evidence

`tools/check_lengths.py` renders every case below at 370×610 and 1000×700
with the worktree shell, asserts a trusted boot (finite fontPx, no
boot/load/draw issue), and compares shell `length` lint against an
independent pure-python verdict computed from the page source. `--prior-ref`
renders the same bodies with that ref's shell: inconsistency must render fine
but silent there. Chromium fetches the usual public shell CDN assets; CI
coverage is `screen/tests/test_length_lint.py` (pure decision logic, no
browser/key). Repeat: `uv run --project server python
screen/tools/check_lengths.py --out /tmp/lengths [--prior-ref 950b3b0]`.

| Case | Independent verdict | Shell (new) | Prior shell 950b3b0 |
|---|---|---|---|
| bad-4vs5 (4-unit side says 5 cm) | 1 finding: side 1, ~20% shorter | warns both sizes | renders fine, silent |
| joint-two (two known sides disagree) | 1 joint finding, no direction | warns both sizes | renders fine, silent |
| ok-rect, ok-scaled (×2.5 copy), model-plan (real writer rect+L) | quiet (scale-free) | quiet both sizes | quiet |
| ok-tri-round (3,46), ok-mixed-units, ok-small | quiet (rounding/units) | quiet both sizes | quiet |
| ok-unknown, ok-algebra, ok-angle, ok-area, model-ratblock (segments) | quiet (unknowns/mixed/segments) | quiet both sizes | quiet |
| ok-free, ok-schematic | quiet (opt-outs) | quiet both sizes | quiet |
| ok-nonfinite, ok-degenerate | quiet (no claim, no crash) | quiet both sizes | quiet |

Lifecycle (`check_lengths.check_lifecycle`, all passing): a `later` polygon
warns only after `ot.reveal`; a consistent hidden figure stays quiet after
reveal; replacing the bad label by patch clears the finding from `ot.issues`
(repaired warnings not retained); the verdict is identical at both sizes
(attribute-only, never layout-sensitive); `schematic` survives composition on
the native `setHTML` path and the forced DOMPurify fallback; the repaired body
passes the real server renderer (`Screen._default_render_page`) clean.

Live writer test (`model/`, Gemini 4 Hydrogen low, real prompt and renderer):
a 3-4-5 triangle ask drew `points="0 0, 4 0, 0 3"` with `sides="4 cm | 5 cm
| 3 cm"` — exact — and delivered lint-clean in 9.93 s with no retry; the
corner-points patch applied clean in 3.26 s. Inspected at both sizes before
and after the patch: right-angle mark, labels outside, empty answer box (no
leak), corners pointable. No false positive on real output.

## Limits and integration notes

- Foreshortened faces with numeric `sides` (a cuboid drawn with per-face
  measures) would warn; such sketches must carry `schematic`. The cuboid probe
  body uses segments and stays quiet. One REFERENCE.md line teaches the opt-out.
- Server patch-preview returns on main accumulate the first render's issues
  for every lint kind (pre-existing; PR56's preview change reads final lint).
  No length-side change is needed there: `lintLengths()` drops stale length
  findings before re-adding, so final lint is already correct, and the lint
  retry renders the corrected full body fresh (unaffected).
- PR56 owns side-label placement and the shared `lint()`/reveal hook points;
  this change only reads attributes and adds kind `length` (actionable by
  default, so the existing bounded retry applies with no server change).
  Observed while inspecting: the live page's "3 cm" label sits very close to
  its edge — placement, i.e. PR56's domain, reported not fixed here.
