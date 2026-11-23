# Points pairing, and the collapsed-figure lint

Evidence for the fix of the slanted-rectangle bug seen in production on 2026-11-22
(2 of 5 pages in one lesson). No lesson content here: synthetic figures and counts.

**What happened.** The tutor wrote
`<ot-polygon points="0 0,4 0,4 3,0 3">` — pairs separated by a comma, x and y by a
space. The shell split on whitespace and ", " only, so the tokens became `0`, `0,4`,
`0,4`, `3,0`, `3` and `num()` read `0,4` as the Swedish decimal 0.4. `points()` then
paired the wrong numbers: two points, drawn as a thin slanted line where the child
should have seen a 4×3 rectangle.

**Fix.** `pairsByComma()` in `screen/shell/shell.js` claims a points list only when
the string has no `;`, has a comma, and every comma-separated chunk is exactly one
`x y` pair; `points()` uses it and falls back to the old tokenisation otherwise. Every
form that worked before still pairs the same way, including decimal commas
(`1,5 2, 3 4,5`), `;`, ", ", whitespace only, parentheses, true minus and `a/b`.
`lintLengths()` measures with the same pairing, so a side claim is compared with the
figure that is actually on screen.

**New lint (`shape`).** `lintShapes()` reports three things a figure can lose:
a plane figure with fewer than three points, a figure whose points lie (nearly) on
one line (mean width under 12% of its longest side), and a figure drawn under 4 px
across. `free` and `schematic` figures opt out, as they do for the length lint.
The sliver rule is scale-free; the pixel rule needs the graph's own mapping and so
runs after drawing, from `settle()` and `ot.reveal()`, and clears its own findings
on every run like the length lint.

**Measured.** `tools/check_points.py` composes each form, renders it at 355×320 and
1000×700 in headless Chromium, and compares the drawn pixel box with an independent
pure-python pairing of the same attribute:

| Case | Prior shell (`origin/main`) | This branch |
|---|---|---|
| `points="0 0,4 0,4 3,0 3"` | 27.0×175.7 px, ratio 0.15 (wrong) | ratio 1.33, no issue |
| the same at 1000×700 | 58.2×378.5 px, ratio 0.15 | ratio 1.33 |
| every other accepted form | correct | correct, no issue |
| nearly flat triangle | drawn 221.5×16.6 px, silent | `shape` issue, and it clears when patched |
| 2-point polygon | drawn 221.5×0.0 px, silent | `shape` issue |
| figure under 1 px in a wide range | drawn 0.3×0.3 px, silent | `shape` issue |
| `schematic` sliver | silent | still silent |

The nine example bodies produce exactly the same lint as on `origin/main` (compared
issue by issue at 370×610 and 840×743: 0 pages differ), so the new lint does not
shout about figures that are fine. `tools/check_lengths.py` passes unchanged, which
is the length lint's own regression check after the shared pairing.

Reproduce (needs Chromium and the public CDN):

```
uv run --project server python screen/tools/check_points.py --out /tmp/points --examples
uv run --project server python screen/tools/check_points.py --out /tmp/points --prior-ref origin/main
uv run --project server pytest -q ../screen/tests/test_points_parse.py
```

`results.json` is the run recorded above. `--prior-ref` renders the same cases on the
exported shell and expects the comma-only rectangle to draw with the wrong ratio
there, which is the gap this change closes.
