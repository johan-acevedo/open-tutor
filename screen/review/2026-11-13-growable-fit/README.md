# Exclude stale drawings from font measurement

A real family session reported a short six-node overview at 603×743 shrinking below
10 px, with half the screen empty. That session was inspected locally and is not copied
here. `synthetic.html` uses unrelated outing-planning text to reproduce the same shape.

The mind map correctly asks for more height. The next font fit, however, changes its
host's em dimensions while its absolutely positioned drawing still has coordinates
from the old size. Those coordinates contribute to page `scrollHeight`, so every
candidate font appears too large. The fitter falls to 11 px and adds a scale transform.
Resizing makes the stale-coordinate feedback worse (`check-before.txt`).

Six CSS lines exclude generated drawing layers, chart canvases and image wrappers/credit
from layout **only during the synchronous font measurement**. Host minimum heights and
ordinary page text remain measured. Drawing resumes after the font is chosen, including
the existing component request for more height. No clipping or lint threshold change.

Synthetic reproduction: 603×743 goes from 10.09 effective px with false overflow/dense
to 20.5 px without either issue. At 370×610 it uses 16.25 px; wide is 19.25 px. All node
boxes remain visible. I inspected the three committed after renders and the before render.
The private reported page now renders locally at 19 px with no issues; only that result
is recorded here, not its source or screenshot.

Fresh **Gemini 4 Hydrogen, reasoning low**, real Screen job, no look (`SCREEN_LOOK=0`):
8.02 s generation, 9.19 s total at 603×743, clean lint. `hydrogen.html` is its unedited body.
It uses 24.25 px at 1000×700, clean lint. Its longer introduction and one long node still
require 15.75 px on a 370×610 phone, so `dense` remains visible. This is a real content
limit, not the false 9 px shrink. I inspected both phone and wide model-page renders.
No reference syntax changed; no model instructions were added for this shell defect.

Model request (synthetic learner, grade 5): “Gör en kort, lugn tankekarta om att planera en
utflykt. Använd ot-mindmap med en mitt och sex ot-node, vardera en kort fet rubrik och en
kort small-rad. Bara rubrik, en inledningsrad och kartan. Inga bilder, ingen svarsruta.
Barnet ska själv välja vad som är viktigast.”

`check_fit.py` runs mind map, cycle, graph, map, chart, image, clock, balance, number line
and fraction through 603×743 → 370×610 → 1000×700 → 370×610. It checks effective font,
remaining overflow/dense/draw/crowded issues, and visible node bounds. All 40 checks pass
(`check-results.json`). Source inspection found the same stale-pixel risk in graph views
and chart canvases; image views are excluded consistently. This does not claim every
component reproduced the session's exact failure. Existing readability checks still
catch genuinely dense text and long headings, and the map key/point/patch checks pass.
Full server suite: 291 passed. No service, env, server or web app changes.

```sh
uv run --project server python screen/tools/check_fit.py --out /tmp/fit-check
uv run --project server python screen/tools/check_readability.py
uv run --project server python screen/tools/check_map_key.py
uv run --project server python screen/tools/screenkit.py render screen/review/2026-11-13-growable-fit/hydrogen.html --out /tmp/hydrogen-fit --sizes 370x610,1000x700
```

For a prior-shell check, export `frame.html`, `shell.css`, `shell.js` and
`data/lan-sverige.json` from the base commit into one directory, then run
`check_fit.py --shell /path/to/exported-shell --case mindmap --out /tmp/fit-before`.
It must fail; the recorded before run used the unchanged feature shell before these
six CSS lines were added. Browser checks use the usual public shell CDN assets,
but no model or key; only the explicitly noted Hydrogen job called inference.
