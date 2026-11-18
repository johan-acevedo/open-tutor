# ot-map: fit the highlighted marks (2026-11-18)

Production 2026-11-18: a "Sverige som störst" page used `<ot-map>` with an
`<ot-area>` (historical borders) and two `<ot-place>` markers, but the map was
fitted to all of Europe -- the realm a small shape in the top corner. The page
had written an explicit `view="europa"`, which overrides the fit.

## Change

`screen/shell/shell.js` (`drawMap`): when a map has highlighted areas/places
(and/or countries) with no explicit `view` and no `regions="län"`, the fit
target is the union of the highlighted geometry + places (as before), now with
a regional minimum extent: bounds smaller than 8° lon × 6° lat are widened to
that window. A single city therefore gets a regional frame instead of a
street-level zoom (or, as rendered here, an empty sea). An explicit `view`
(naming a region or four numbers) still wins; the full län map keeps its own
fitting to the 21 region polygons.

`screen/REFERENCE.md`: without `view` the map fits what you mark; leave `view`
out when highlighting so it fills the frame, use it only for context.

## Bodies (fictional)

- `b1-empire.html`: Swedish-realm area (`year="1658"`, matches the 1650
  "Sweden" feature) + Stockholm + Riga, no view.
- `b2-empire-view.html`: same with `view="europa"` (production shape).
- `b3-single-city.html`: one `ot-place` (Stockholm), no view.

Rendered with `screen/tools/screenkit.py` at 370×610 and 840×743, before
(shell from `origin/main`) and after.

## What the shots show

- b1: unchanged -- the realm (lon 8.4-31.3, lat 53.2-80.6) is far above the
  minimum, so the fit is identical before/after. Stockholm and Riga readable.
- b2: unchanged -- explicit `view="europa"` still shows all of Europe. This is
  the production symptom; the cure is writer guidance (omit `view` when
  highlighting), not a shell override.
- b3: before = empty sea (degenerate point fit), no lint issue; after = a
  regional frame (southern Sweden, Norway, Finland, the Baltic) with the dot
  and label. Lint still clean.

## No regressions in the nine examples

`examples-before.json` (shell from `origin/main`) vs `examples-after.json`
(this change): all nine example screens with their patches at 370×610 and
840×743 -- lint issues, patch issues and fitted font sizes are identical
(zero diffs, including `romarriket` with area + places and no view, and
`regioner` with the län map). Reproduce with `screen/tools/check_examples.py`:
`uv run --project server python screen/tools/check_examples.py <shell-dir> <out.json>`
with an empty shell-dir for the working tree.

## Edge cases: antimeridian, poles, `later` marks (2026-11-18 review follow-up)

Cross-family review found two regressions in the minimum-extent padding above:

- Antimeridian: places at (179°, 10°) and (-179°, 10°) measured a -358° span,
  padded a box around Greenwich, and both markers disappeared (`place outside
  the map`). The fit now unwraps `d3.geoBounds` output that spans the
  antimeridian (`b[1][0] < b[0][0]`) to the shorter arc and pads around it;
  the fit centre is normalised back into range for the projection rotation.
- Poles: places at (0°, 86°) and (8°, 87°) had the widened north edge capped
  at 84°, leaving the marks outside (the south edge the same, and past 89°
  the cap even inverted the box). The padded frame is still kept inside the
  valid map, but never cut past the marks themselves -- the marks always win.

Bodies (fictional): `c1-antimeridian.html` (two places across the date line),
`c2-poles.html` (two northern + two southern near-pole stations),
`c3-later-place.html` (Stockholm + Visby with `later`). Rendered at 370×610
and 840×743 with the shell from `origin/main` (`before-c*`), with this PR
before the fix (`place outside the map` on all of c1/c2, zero dots), and with
the fix (`after-c*`): c1 shows both date-line dots with no lint issues, c2
shows all four polar dots with no lint issues -- the same markers that were
visible on `origin/main`.

Also fixed while here (pre-existing, few lines): an `<ot-place later>` was
drawn immediately -- `drawMap` ignored `later`/`hidden` on map children and
`ot.reveal` never redrew the map. `later`/`hidden` marks are now skipped for
focus and drawing, and reveal redraws the closest `ot-map` (the newly shown
mark joins the fit). c3 (`before-c3`: old shell draws both dots up front;
`after-c3`: one dot pre-reveal in `-hidden.png`, two post-reveal in `-revealed.png`)
was verified by dot counts at both sizes (2/2 before the fix, 1/2 after). Limitation kept:
revealing a whole container at once does not redraw a nested map, same as
nested graphs.
