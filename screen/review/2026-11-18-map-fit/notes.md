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
`regioner` with the län map). Reproduce with `/tmp/check_examples.py`
(not committed): `python /tmp/check_examples.py <shell-dir> <out.json>`
with an empty shell-dir for the working tree.
