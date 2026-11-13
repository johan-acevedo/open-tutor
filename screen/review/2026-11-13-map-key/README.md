# Map key layout, 2026-11-13

A full län map (`<ot-map view="sverige" regions="län">`) put its 21-letter key in a strip
under the map. Sweden is taller than wide, so the map was fitted into the height that was
left, in a box that was mostly empty to the left and right: the letters came out at 9–10 px
and the key covered the bottom of the country.

The pages here are unedited DeepSeek V4.1 Flash output for
"Visa Sveriges 21 län på en tydlig karta med bokstavskoder och nyckel för en elev i
årskurs 6. Eleven ska hitta Skåne och Norrbotten."

- `page.html` — written after the change, before the reference stopped saying the key is
  under the map (its prose still says "i nyckeln under kartan").
- `page-ref.html` — the same ask after that reference wording changed; its prose names the
  key without saying where it is.
- `page-early.html` — the same request written before the change; kept so the two shells can
  be compared on identical input. This page is the one in
  `/tmp/screen-try-txoatcz5/s1/` in the earlier round.
- `mark.patch.html` — marks Skåne, Stockholm and Norrbotten (the example's patch).

## What changed

The key is measured at draw time, and the map keeps whichever of two layouts draws the
country bigger:

- **Beside the map**: the key becomes one or two columns on the right and the map gets the
  whole height. Two key sizes are tried (0.68 em, then 0.6 em) so a narrow-ish pane still
  gets a readable key. Rejected when the key would take more than 40 % of the width, when it
  is taller than the box, or when the taller map does not actually come out bigger.
- **Under the map** otherwise, as on a phone. The strip is now placed below the fitted map
  instead of being anchored to the bottom of the box, so it no longer sits over Skåne.

The country is also slid (never scaled) to the middle of the room the map has: the `sverige`
view box includes Norway and Finland as context, which put Sweden off to one side.

Nothing else about the map changed: the 21 letter codes and their leader lines, the key rows
dimmed for codes that did not fit, `ot.point('lan-<bokstav>')`, `ot-region` marking and
`crowded` reporting all behave as before. The key sits over the map's ocean colour, with a
fade behind it so the neighbour borders do not run through the letters.

## Numbers, same pages, same panes

Measured by `screen/tools/check_map_key.py`; "codes" is how many of the 21 letters are on the
map (the rest are dimmed in the key).

| page | pane | key | codes before → after | letter size | country (px) | map box | crowded before → after |
|---|---|---|---|---|---|---|---|
| page.html | 1000×700 | beside | 20 → 21 | 10.5 → 13.1 px | 109×248 → 138×314 | 945×340 | yes → no |
| page.html | 760×900 | beside | 18 → 21 | 9.3 → 13.5 px | 94×215 → 140×320 | 691×350 | yes → no |
| page.html | 370×610 | under | 12 → 12 | 7 px (floor) | 45×104 → 45×104 | 327×217 | yes → yes |
| page-ref.html | 1000×700 | beside | 18 → 20 | 8.5 → 11.2 px | 87×198 → 116×266 | 943×290 | yes → yes (1 left out) |
| page-ref.html | 760×900 | beside | 18 → 21 | 9.2 → 13.3 px | 94×213 → 140×317 | 692×347 | yes → no |
| page-ref.html | 370×610 | under | 15 → 14 | 7 px (floor) | 51×118 → 49×110 | 324×245 | yes → yes |
| page-early.html | 1000×700 | beside | 20 → 21 | 9.4 → 12.3 px | 97×220 → 128×293 | 940×319 | yes → no |
| page-early.html | 760×900 | beside | 18 → 20 | 8.4 → 12.3 px | 86×194 → 128×291 | 696×319 | yes → no |
| page-early.html | 370×610 | under | 15 → 15 | 7 px (floor) | 54×124 → 54×124 | 328×234 | yes → yes |

`page-ref.html` has the largest answer block of the three, so its map box is only 290 px tall
at 1000×700 and one region still loses its letter; the other two pages go from 20/21 to 21/21
there. Every wide pane moves the key beside the map and grows the letters by 2.5–4 px.

On the 390×844 phone in the example gallery every page renders exactly as before (the
examples and `screen/tests/` compare equal, except that the län example's patch now leaves 4
regions without a letter instead of 5).

## Repeat it

```sh
# no provider calls: layout, codes, pointing and marking on both pages, three panes
uv run --project server python screen/tools/check_map_key.py

# screenshots and lint for one body (writes page-<pane>.png next to it)
uv run --project server python screen/tools/screenkit.py render \
  screen/review/2026-11-13-map-key/page.html --out screen/review/2026-11-13-map-key \
  --sizes 370x610,760x900,1000x700 --patch screen/review/2026-11-13-map-key/mark.patch.html

# a fresh page from the real model (key comes from the env wrapper, never printed)
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env \
  uv run --project server python server/bin/screen-try \
  "Visa Sveriges 21 län på en tydlig karta med bokstavskoder och nyckel för en elev i årskurs 6. Eleven ska hitta Skåne och Norrbotten."
```

`*-before-*.png` are the same bodies on `origin/feat/smart-screen` (8fa6de6).
`results.json` holds the shell's own lint for both pages on both shells.

## Still wrong

- **The phone is unchanged.** At 370×610 the map box is only 217–234 px tall because the page
  holds a title, a paragraph, the map and the answer box; the key takes 92–113 px of it and the
  letters sit on the 7 px floor with 6–9 regions left out. The cure is less page content (the
  narrow-page and readability work), not a smaller map. A side key does not fit there: two
  columns of eleven names need about 160 px of a 325 px box, and the key type would drop below
  10 px.
- **The key eats width on medium panes.** At 760×900 it takes 252 px of 691; the map still more
  than doubled in height, but a shorter legend wording would help. `screen/REFERENCE.md` no
  longer says the key is under the map, and `page-ref.html` (written after that) says only
  "Nyckeln visar vilken kod som hör till vilket län".
- **A marked region's name is drawn at page size** and can cover its neighbours (`Stockholm`
  over `AB` in `page-1000x700-patched.png`). Unchanged by this work, worth its own fix.
