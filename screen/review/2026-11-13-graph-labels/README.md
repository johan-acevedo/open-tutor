# Graph label placement and overlap lint, 2026-11-13

Side and segment labels now use measured clearance and polygon winding. Remaining
crossings, side-label overlaps and pane overflow produce actionable `crowded` lint.
This is placement plus detection, not a guarantee that every authored layout fits.

## Change

The previous fixed `1.05 * font` offset ignored label width. The vertex mean also
picked the wrong outward direction in a concave L. Labels crossed vertical and
slanted strokes, and two L labels landed inside the material.

- Use the signed polygon area for outward normals, in either vertex order.
- Offset by the measured box's reach along the normal, plus stroke clearance.
  Auto ranges reserve label room; explicit ranges are retained subject to the
  graph's existing equal-unit aspect rule.
- Nudge along an edge or flip a segment label when that avoids collisions.
  Check every straight polygon/segment outline in the graph, not just the
  label's own edge. Never shrink text to hide a collision.
- Rebuild graph lint after fitting, patches and reveals. Hidden work is omitted
  until revealed; hidden graph children are not drawn early. Updated warnings
  still reach the parent after earlier warnings have been replaced.
- The server's patch preview reads final frame lint, clearing repaired warnings
  while retaining patch exceptions. No new tags, reference lines or length lint.

The correction text says to keep given measures and use separate graphs or more
room. Removing a required measure is not an acceptable layout repair.

## Repeatable evidence

From the repository root:

```sh
uv run --project server python screen/tools/check_graph_labels.py --out /tmp/graph-labels --prior-ref 848f8c1
```

This manual Chromium check downloads the shell's public libraries; it needs no
model or key, but is not an offline CI test. It measures four unedited Hydrogen
bodies from the geometry research plus three synthetic cases at 370×610 and
1000×700. It also checks pointing, warning replacement over patches, reveal
visibility and the real server preview after repair.

`shots/results.json` records the corrected independent geometry check: the prior
shell has unreported defects; this shell has none within the checked scope.
Reported unresolved defects remain visible in the screenshots and check log.
Parent review found that the first checker read absent edge coordinates, making
part of its calculation NaN. Fixing the checker exposed five unreported outline
crossings on the worker head (`worker-head-review-failure.log`). The final shell
and checker cover neighboring straight outlines as well as the source edge.

## Hydrogen low page and patch

`model-reviewed/` is the final fresh job, with unedited raw and delivered source,
metadata and both pane renders. Total 12.51 s: generation 8.10 s, correction
2.66 s, rendering 1.75 s. This is one observed job, not a latency benchmark.
The first layout crowded the notch. The retry separated the rectangle and L
into two graphs, retained all given measures, and left the answer empty. The
same delivered body has no lint at either size: 16 px phone, 19.5 px wide.
The parent inspected both screenshots.

`model/` preserves the earlier worker trial and its real patch/pointing evidence.
That retry removed one notch label; it is not the acceptance example. Its old
clean-lint claim also predates the corrected outline check. The final lifecycle
check verifies that newly introduced crowding reaches patch callers and repaired
crowding disappears from the real server preview.

## Limits and checks

- The original tight two-figure plan remains crowded, with notch and neighboring
  outline collisions on phone and side-label pairs on wide panes. They are
  flagged. The overlong `diagonalen` in `short-edges` exceeds the phone graph box
  and is flagged too.
- Winding assumes simple polygons. Arbitrary `ot-text`, point/vertex labels,
  curved function outlines and right-angle decorations are outside this lint.
  In particular, the existing angle page's `60°` text touches `Vinkelben`; this
  change does not claim that page is completely collision-free.
- Growable fit/resizing, readability, native/library/blocked sanitizer, patch
  history and map-key checks pass. Full configured server suite: 429 passed,
  18 skipped. Evidence was rendered locally on dell5500; nothing was deployed.

## Merge with image review

Updated with main through `950b3b0` (including #52 and #49). The renderer keeps
the 5 s patch-image wait, then reads final frame lint. Renderer exceptions and
image-wait timeout advisories remain separate so refreshing lint cannot erase
them. Stub tests cover late image failures plus repaired label warnings, image
timeouts, and patch exceptions. The real renderer integration probe repairs a
crowded label and adds a recorded Commons bitmap in the same patch. At both
panes the screenshot sees a loaded 960 px bitmap and no stale crowding; both
screenshots inspected. It makes no model call and intercepts the image URL,
while the shell's public CDN assets still need network access.

```sh
uv run --project server python screen/review/2026-11-13-graph-labels/check_preview_merge.py /tmp/preview-merge
```
