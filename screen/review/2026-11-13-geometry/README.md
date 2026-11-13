# Geometry pages: what the writer draws, and the smallest fixes

Six real **Gemini 4 Hydrogen, reasoning low** jobs (the deployed page writer), each rendered
unedited at 370×610 and 1000×700 and measured. Answers "what does the current writer do with
circles, angles, solids and labelled outlines", "where is the side-label defect", and "which
tag or check is worth building" — as a proposal, not code.

| # | Ask (Swedish, one teaching step) | Model | Wall | Lint on the unedited body | Repaired? |
|---|---|---|---|---|---|
| 1 | circle r = 4 cm, radius labelled and pointable, no area | 12.75 s | 17.16 s | `unknown tag <ot-circle>` | yes, one lint retry (2.61 s) → circle drawn as two graphs |
| 2 | 60° angle, vertex pointable, no answer | 10.59 | 11.73 | clean | no |
| 3 | cuboid 4 × 3 × 2 cm, height pointable, no volume | 11.56 | 12.68 | clean | no |
| 4 | cylinder r = 3, h = 5, radius pointable, no volume | 6.84 | 8.04 | clean | no |
| 5 | rectangle 4 × 3 + L (3, 2, 1 cm) with side labels and a perimeter answer box | 7.25 | 8.48 | clean | no |
| 6 | *patch* on page 3: mark the height, move 2 cm off the line | 4.82 | 6.12 | `patch_issues: []` | — |

Pane 370×610 (the writer was told "narrow, one reading column"); font 17.5 px at 370×610 and
30.25 px at 1000×700 on every page, no `dense`, no overflow. Provider, settings and exact
commands: `provenance.json`. Raw bodies, delivered bodies, patches, screenshots, `meta.json`
(with the Screen's own `repair` record) and `measure.json` per case: `raw/<case>/`.

**Latency is reported apart from quality.** Generation alone was 6.8–12.8 s, so the look pass
never ran on any of the six jobs: page 1 went straight to the lint retry ("look pass skipped:
correct lint directly"), the other five had "look pass skipped: page target budget". Lint was
clean on the five pages whose labels are visibly wrong (below). CI-time checks are not evidence
for this work; every quality claim here is from a screenshot I inspected.

## What the writer actually wrote

- **Circle (1).** It reached for `<ot-circle center="0 0" r="4">` — a tag that exists nowhere in
  the reference or the shell. Lint said `unknown tag <ot-circle>`, and the raw render is a centre
  point and a radius segment with **no circle at all** (`raw/cirkel/cirkel-*.png`). The existing
  lint retry then rewrote it as two `ot-fn` curves (`sqrt(16 - x^2)` and `-sqrt(16 - x^2)`,
  `domain="-4 4"`) and it renders correctly at both sizes (`cirkel/delivered-*.png`). That
  corrected body is the model's own output, unedited — the strongest evidence for the reference
  line proposed below. Minor: a hairline seam where the two halves meet at 1000×700.
- **Angle (2).** Two `ot-segment` rays at 60.0° (`atan(3.46/2) = 59.99°`), and `60°` as the
  *vertex point's* label. No arc. Both rays carry the text "Vinkelben", and the slanted one's
  label crosses its own line by 26 px at 370×610 and 45 px at 1000×700.
- **Cuboid (3).** Oblique projection from three `ot-polygon fill="none"` faces plus three labelled
  `ot-segment`s. Dimensions are right: height 2.0 units ↔ 2 cm, length 4.0 ↔ 4 cm, depth 1.803 ↔
  3 cm (a deliberate foreshortening — see the check below). The height label "2 cm" crosses its
  own line by 3–4 px.
- **Cylinder (4).** Top and bottom from three `ot-fn` curves (ellipse 3 × 0.6 units), two side
  segments, radius 3.0 ↔ 3 cm and height 5.0 ↔ 5 cm. Reads well at both sizes. Height label
  crosses its line by 3–5 px. No volume, no π.
- **Rectangle + L (5).** `ot-polygon sides=…` twice, plus a perimeter answer box. **All ten side
  labels agree with the drawn lengths exactly** (implied scale 1.000 on every side, spread 0).
  But the L's labels are placed wrong — this is the reported 4 cm / 3 cm outline problem.
- **Patch (6).** Two patches against real ids: `target="hojd"` (the height segment) and
  `target="ratblock" do="append"` (a new point `hojd-punkt` with the "2 cm" label). Both targets
  exist, nothing is missing, `patch_issues` is empty, the new point is pointable, and the label
  now sits outside the figure (`ratblock-patch/*-patched.png`). After the patch the whole page
  measures with no flags.

## The two measured defects share one cause

`measure.json` per case; "edge_px" is the label centre's distance from its own line, "overlap" =
the label's half-extent along that line's normal minus that distance (positive = the text reaches
back over the stroke).

| Page, size | Flag |
|---|---|
| plan, 370×610 | 4 labels cross their own outline by 3 px; 1 label **inside** the L |
| plan, 1000×700 | 4 labels cross by 4–5 px; 2 labels **inside** the L |
| vinkel, both | "Vinkelben" on the slanted ray crosses its line by 26 px / 45 px |
| ratblock, both | "2 cm" on the height edge crosses by 3 px / 4 px |
| cylinder, both | "5 cm" on the height edge crosses by 3 px / 5 px |

Why (in `drawGraph`, `screen/shell/shell.js`):

1. `sideLabel()` (`shell.js:1271`, offset at 1277) puts the label's **centre** a fixed `1.05 * f` out along the edge
   normal and centres it there. Its half-extent along that normal is `w/2` for a vertical side, so
   every label wider than ≈ 2.1 em crosses its own line. This is the "4 cm on the outline" case,
   3–5 px, and the extreme 26–45 px on a slanted ray.
2. For a polygon the outward side is decided from `cen`, the **mean of the vertices**
   (`shell.js:1233`). That point is not in the material for a concave shape: the L in `plan/raw.html`
   is `points="6 0, 9 0, 9 1, 7 1, 7 2, 6 2"`, whose mean is (7.33, 1.0) — exactly on the notch
   edge and inside the notch. The notch edge's label is then decided by a floating-point tie and
   lands *below* the edge, inside the bottom bar; the notch's vertical edge label flips *left*,
   inside the upright. Two of six labels inside the figure, on a page Hydrogen wrote unprompted.

**Smallest fix (recommended, not implemented — ~12 lines in `shell.js`, no reference change):**

- Replace `cen` with the polygon's winding: compute the signed area from `spx` once and pass
  `area < 0 ? 1 : -1` into `sideLabel`, which multiplies its normal by it. Outward is then
  per-edge and correct for any simple concave polygon; the tie disappears. Segment labels keep
  today's rule.
- Make the offset reach-aware: tag each side label with its normal (`data-nx`/`data-ny`) and, in
  the existing `keepInside()` pass that already walks `.ot-lbl`, shift it out by
  `max(0, reach + 0.25 * f - 1.05 * f)` with `reach = |nx| > |ny| ? w/2 : h/2`. That is where
  the same class of bug is already handled, and it needs no second layout pass.

## Can a check catch a wrong length? (prototype, in `screen/tools/probe_geometry.py`)

The user's gap — "no numeric check that a plane figure's drawn lengths match labels" — is real:
inner lint passes all six pages. The probe computes, per `ot-polygon` with `sides`, each drawn
edge length in graph units and the number in its label, then the *spread of the implied scale*
(scale-free, so any drawing scale is fine).

- Real plane page (5): all ten sides imply 1.000 — the check is silent, correctly.
- Synthetic `sides="5 cm | 3 cm | 4 cm | 3 cm"` on a 4 × 3 rectangle: "labels imply 0.80–1.00
  units per labelled cm (spread 20%)" — caught.
- Deliberate perspective is not a mismatch: the cuboid's depth is 1.803 units for "3 cm"
  (implied 0.601), but it is an `ot-segment`, not a `sides` label. **Apply the check to
  `ot-polygon sides` only**, never to segments or to a figure drawn in perspective.

## Pointing and answer leaks

- Pointable parts existed and worked in every case (`ot.point(id)` → true): `radie` (1, 4),
  `spets` (2), `hojd` (3 and the patched `hojd-punkt`), `rektangel` (5). Pointing inside an
  `ot-graph` works because `drawGraph` stores `_px` and `ot.point` routes to `pointAt`.
- No page gave a result away: circle radius only, angle 60° only (given, not computed), cuboid and
  cylinder dimensions only (no volume, no π), the plan page's answer box empty with no perimeter
  value. The per-case `forbid` scans (area 50,2; volume 24/141; cm³; "omkrets =") found nothing.
  Caveat: that was my reading, not the pipeline's — the look pass never ran on these jobs.

## Ranked proposal

1. **Three reference lines, no code.** (a) The circle recipe the writer itself produced after one
   lint line: two `ot-fn` halves plus a centre point and a labelled radius segment — it removes an
   invented tag and a 2.6 s retry on every circle page. (b) A solids convention: visible faces as
   `ot-polygon fill="none"`, each measure as its own labelled `ot-segment`, and the ask-named part
   given the id (`hojd`, `radie`). All three solids pages already did this unprompted; saying it
   costs a paragraph and makes it reliable. (c) Document `ot-text`, which the shell implements but
   the reference omits, so a label can sit anywhere in a graph (an angle label off the vertex).
2. **The `sideLabel` fix above.** Highest quality gain per line: it removes the reported
   outline-label defect, the labels inside an L, and the ray label lying across its own line — all
   measured on real output. No reference change, no new tag.
3. **The scale-free side-length lint** (item "Can a check catch…"), reported through the existing
   lint-retry path with a message that names the side. Only `ot-polygon sides`; ±5 % spread.
   Justified because nothing checks this today and the retry path already exists and works.
4. **`ot-circle`** (`center`, `r`, optional radius label; ~15 lines in `drawGraph`, one reference
   row, pointable). Worth it if circle pages are frequent — the workaround works, but the model
   reaches for `ot-circle` first, so the name is what it expects.
5. **An angle arc** (`arc` on a segment pair, or `ot-arc`). Lowest value: one 60° angle with a
   vertex label reads fine, and `ot-text` covers the label placement.
6. **A solids tag: not yet.** No evidence it earns its cost: 3/3 solids pages were readable with
   two existing tags, dimensions were right, and the only defect was label placement (item 2).
   A `rätblock/cylinder/prisma/pyramid/kon/klot` tag must own projection, hidden edges, six
   labels and its own reference/examples — a large surface for the part that already works. If a
   real lesson later misses, build **one** tag, not six, with the fewest attributes that cover the
   approved family:
   `<ot-solid kind="rätblock|cylinder|prisma|pyramid|kon|klot" a="4" b="3" c="2" hidden="dashed">`
   with pointable dimension ids `hojd`, `radie`, `bas`, `sida` (so `reveal`/`point` work), and a
   later `net` attribute for nets. Prism, pyramid, cone, sphere and nets are **untested** here.

## What I did not do, and what is untested

Not done, by instruction: no plane-figure component (the real pages and case 5 already draw
correct lengths); no implementation of items 2–6; no prompt/reference/examples change in the app;
no service restart, no `agent.py` or web app change, no merge/rebase of main, no PR #52 image work;
no hand-edited model body — the corrected circle is the writer's own retry output, labelled as
such; no model call in CI.

Untested: prisms, pyramids, cones, spheres, nets; the steered candidate lines (they are in
`probe_geometry.py` as `cirkel-styrd` / `vinkel-styrd` and were not run — the writer supplied the
circle recipe itself); concave shapes other than an L; a figure whose `sides` order does not match
its points order; circles large enough to show the two-half seam prominently; a real child's pane.

## Repeat

```sh
# the six real jobs (key from $OPEN_TUTOR_ENV; never printed)
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env env \
  SCREEN_MODEL=gemini-4-hydrogen SCREEN_API=chat SCREEN_REASONING=low SCREEN_THINKING= \
  uv run --project server python screen/tools/probe_geometry.py run \
    --out /tmp/geometry --cases cirkel,vinkel,ratblock,cylinder,plan,ratblock-patch

# re-render and re-measure saved bodies: no provider call, safe anywhere
uv run --project server python screen/tools/probe_geometry.py measure \
  --dir screen/review/2026-11-13-geometry/raw
```

`probe_geometry.py measure` is the CI-shaped artifact: per case folder it writes `measure.json`
(per size: font, lint, every side's drawn length vs its label, every label's distance to its own
outline, ids and whether each is pointable, visible text and any forbidden string) and the
screenshots at both sizes. No network. Full server suite: 429 passed, 18 skipped (no runtime code changed).
