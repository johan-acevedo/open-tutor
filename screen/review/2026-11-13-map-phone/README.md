# Phone regions map, 2026-11-13

Follow-up to the merged map key work (PR #41) for one case: a full län map
(`<ot-map view="sverige" regions="län">`) on a phone.

PR #41 put the key in a strip below the fitted map, but the strip was still **inside** the
map box, over the ocean, and the country was fitted to the `sverige` view box, which keeps
Norway, Finland and the Baltic in frame. On a real page at 370×610 that left a 45×104 px
Sweden in a mostly empty 327×217 px box, with the key's first rows printed over Skåne.

## What changed

**Two boxes in normal flow, no overlay.** The map layer is a flex container with the drawing
box (`.ot-map-canvas`: svg, region shapes, labels) and the key (`.ot-map-legend`) as siblings.
On a wide pane the key is an upright column beside the map; on a phone it is a wrapped strip
under it. Nothing is drawn behind the key, so the fade that hid the map under it is gone.

**Tight fit.** With `regions="län"` the projection is fitted to the 21 region polygons
themselves (4.5 % padding), whatever `view` says. The neighbours are still drawn, as context
at the edge of the box. Sweden now covers 91 % of the drawing box height on every pane.

**A taller map on a phone.** `ot-map[regions] { min-height: 16em }` below 600 px wide, so the
box is not a short wide strip. Below, in the limitations: this costs about 1 px of body text.

**The side key is for landscape panes only.** The key goes beside the map when the pane is at
least 480 px wide and clearly landscape (`w > 1.3 h`); otherwise it goes under. A 370 px pane
never gets a 132 px key column that leaves a 189 px map.

Everything else about the component is unchanged: letter codes sized by the map, hidden codes
with their key row dimmed, `ot.point('lan-<bokstav>')` outlining a region, `ot-region` marking
and naming, `crowded` lint, patches redrawing the map.

## Numbers, same unedited model pages, same panes

The pages are the unedited DeepSeek V4.1 Flash bodies in `../2026-11-13-map-key/`
(`page.html`, `page-ref.html`, `page-early.html`, plus `mark.patch.html`); no new model call
was made, the syntax did not change. Measured by `screen/tools/check_map_key.py`; "filled" is
the country's height and width as a share of the **drawing box**, not of the map element.

| page | pane | key | codes on map | code size | country (px) | drawing box (px) | filled |
|---|---|---|---|---|---|---|---|
| page.html | 370×610 | under | 12/21 → **20/21** | 7 → 8.1 px | 45×104 → **85×192** | 327×217 → 330×211 | 48 → **91 % h** |
| page.html | 370×558 | under | 18/21 → **19/21** | 7 → 7 px | 64×144 → **67×151** | 330×236 → 331×165 | 61 → **91 % h** |
| page.html | 760×900 | beside | 21/21 → 21/21 | 13.5 → 13.5 px | 140×320 → 141×318 | 691×350 → 407×350 | 91 → 91 % h |
| page.html | 1000×700 | beside | 20/21 → **21/21** | 13.1 → 13.1 px | 138×314 → 136×309 | 945×340 → 682×340 | 92 → 91 % h |
| page-ref.html | 370×610 | under | 14/21 → **18/21** | 7 → 7 px | 49×110 → **67×152** | 324×245 → 327×167 | 45 → **91 % h** |
| page-ref.html | 1000×700 | beside | 20/21 → 20/21 | 11.2 → 11.2 px | 116×266 → 117×264 | 943×290 → 671×290 | 92 → 91 % h |
| page-early.html | 370×610 | under | 15/21 → **18/21** | 7 → 7 px | 54×124 → **70×158** | 328×234 → 330×174 | 53 → **91 % h** |
| page-early.html | 1000×700 | beside | 21/21 → 21/21 | 12.3 → 12.3 px | 128×293 → 128×291 | 940×319 → 658×319 | 92 → 91 % h |

Wide panes draw the country at the same size as before — a tall country in a wide box is
fitted by height either way — but the box the key sits in is now the page background, the
country fills it, and `page.html` gains its 21st letter. The phone gains 85 % more country
height and 8 more letters on the map; the last letter is dimmed in the key, and `crowded` is
reported, which the brief accepts for phones.

Screenshots (drawing box + key, patched and unpatched) are in this folder. I looked at
`page-370x610.png`, `page-370x558.png`, `page-1000x700.png` and both `-patched.png` files
myself: the key is clear of sea and country, Sweden fills the box, the three marked regions
(Norrbotten amber, Stockholm violet, Skåne cyan) and their names are drawn, and the key rows
for them are lit.

## Limitations

- **Phone text drops about 1 px.** `page.html` at 370×610 goes from 16.5 to 15.25 px, so the
  shell reports `dense` (its floor is 16 px below 600 px wide). The map is the teaching step
  here and the same pane was already below the floor at 370×558; the honest cure is a shorter
  page. The server treats `dense` as actionable, so a phone render can spend its one lint
  retry on cutting text.
- **A phone drawing box stays landscape** (330×211). A portrait box needs the map element at
  ~420 px on a 610-tall pane, which puts the text at 12–13 px. Not worth it.
- **`page-ref.html` at 1000×700 still leaves one letter out** (the 21st is dimmed in the key):
  it has the largest answer block, so its map box is 290 px tall, as before this change.
- Codes on a phone are 7–8 px; they are there to be paired with the key, not read from afar.
- The map element's phone `min-height` uses the viewport-width breakpoint the shell already
  uses for phones (600 px), not a container query.

## Repeat it

```sh
# separate key box, tight bounds, codes, pointing and marking on the three model pages
uv run --project server python screen/tools/check_map_key.py

# same, writing the screenshots in this folder
uv run --project server python screen/tools/check_map_key.py --shots

# the same checks on the shell from PR #41: they must fail there (see check-prior-shell.txt)
screen/tools/check_prior_shell.sh
```

`check-current-shell.txt` and `check-prior-shell.txt` are the captured output. The prior shell
has no `.ot-map-canvas` at all and its phone country covers 48 % of the box; the checks stop on
the first of those, and the `--table-only` table above the assertion records both.
