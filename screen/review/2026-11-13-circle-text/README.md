# Circle and positioned text: do two reference lines change anything?

One synthetic ask per subject, each run **baseline** (the reference on `main` at `848f8c1`) and
**candidate** (the same reference plus two short blocks, injected into the static system prompt
for that job only), with **Gemini 4 Hydrogen, reasoning low**. Every unedited body rendered at
370×610 and 1000×700 and measured; one real patch on the candidate page. Four page jobs plus one
patch job, four provider answers plus one cut look pass, no lint retry, no failure.

| # | Ask (Swedish, one teaching step) | Arm | Model | Look | Total | Lint on the unedited body | Repaired? |
|---|---|---|---|---|---|---|---|
| 1 | circle r = 4 cm, radius drawn and pointable, area must not show | baseline | 7.21 s | — | 8.56 s | clean | no |
| 2 | same ask | candidate | 3.50 | 2.06 (answered OK) | 6.72 | clean | no |
| 3 | 60° angle, 60° inside the vertex, "Vinkelben" at the slanted leg's end, no arc | baseline | 7.71 | — | 8.85 | clean | no |
| 4 | same ask | candidate (v1) | 4.56 | 3.35 (cut by the budget) | 9.00 | clean | no |
| 5 | same ask | candidate (v2, sharpened text rule) | 8.99 | — | 10.20 | clean | no |
| 6 | *patch* on page 4: move both labels, keep them clear, vertex pointable | candidate | 5.20 | — | 6.46 | `issues: []`, `patch_issues: []` | — |

Timings are one sample each and are **not** evidence about speed: the baseline model call was both
the slowest (7.71 s) and not the slowest (7.21 s), and the arms ran minutes apart. No causal speed
claim is made anywhere in this note.

Ask texts, candidate text, provider settings and per-call timings: `raw/<case>/ask.txt`,
`raw/<case>/reference_candidate.txt`, `raw/<case>/meta.json`. Bodies: `raw/<case>/raw.html` (the
model's unedited answer) and `delivered.html`. Screenshots: `raw/<case>/*.png`. Measurements:
`raw/<case>/measure.json`, and `measure-after.json` for the patched page.

## The candidate text that was tested

Swedish, appended to the system prompt for the candidate arms only (636 chars, v2 705 chars):

> **Cirkel.** Det finns ingen cirkeltagg: rita bågen som två kurvor i en `ot-graph`, med samma färg.
> `<ot-point id="medelpunkt" x="0" y="0">`, `<ot-segment id="radie" from="0 0" to="4 0">4 cm</ot-segment>`,
> `<ot-fn color="cyan" domain="-4 4">sqrt(16 - x^2)</ot-fn>` och `<ot-fn color="cyan" domain="-4 4">-sqrt(16 - x^2)</ot-fn>`
> (16 är radien i kvadrat; flytta x och y för en annan medelpunkt). Givna mått skrivs ut, arean ritas inte.
>
> `<ot-text id="…" x="2" y="2">60°</ot-text>` skriver en text centrerad på punkten (x, y) i grafens
> koordinater. Den flyttas bara in i grafens ruta, aldrig undan från linjer: välj en punkt med luft runt.

v2 replaced the last sentence with "Inget flyttar texten undan en linje, och en bred text når tillbaka
halva sin bredd: lägg punkten utanför figuren, inte på en linje och inte vid en linjes ände."

The shipped reference text is the English translation of these blocks, in the voice of the rest of
`REFERENCE.md`. The wording of the English lines was not itself run through the model; only the
guidance content was, in Swedish.

## What the shell really does with these two tags

Measured on a hand-written body (`raw/recipe-selftest/recipe.html`), no provider call:

- `<ot-fn>` accepts `sqrt`, `^`, a decimal comma and `domain`; two half circles with `domain="-4 4"`
  gave curves 8.0 units wide with 4.0 units above and 4.0 below the centre, i.e. a closed circle of
  radius 4 on the shell's own axis scale, at both sizes. Each curve takes its own series colour
  unless `color=` is set on both.
- `<ot-text x="…" y="…">` renders its content as a centred `.ot-lbl` (CSS `translate(-50%,-50%)`),
  draws no marker, has no `label-pos`, and is only clamped into the graph box by `keepInside`, never
  moved off a line. It is registered as a data tag in the shell and survives the sanitizer, but it
  appeared in no reference, example or check before this change (`grep -r ot-text` then found only
  `shell.js`).
- Pointing is a gap for `ot-text`: `ot.point(id)` returns true, yet `graphPoint` only draws a ring for
  `OT-POINT` and only changes JSXGraph stroke widths for drawn objects, so an `ot-text` id gives the
  child no visible feedback. The pointing sweep measured a delta of zero (children, `.ot-pointed`,
  stroke width) for `kant`, `gradtal` and `vinkelben`; the same sweep on the vertex point adds one
  ring element and on a segment adds 2.3–4.0 to its stroke width.

## Circle: both arms already drew it correctly

| Case, size | Font | Drawn arc, units | Radius segment | "4 cm" clear of its line by | Leak | Colours |
|---|---|---|---|---|---|---|
| baseline, 370 | 17.5 px | 8.0 wide, 4.0 up + 4.0 down | 4.0 units = label 4 | 8.8 px | none | upper cyan, lower **violet** |
| baseline, 1000 | 30.25 | same | same | 15.1 px | none | two colours |
| candidate, 370 | 17.5 | same | same | 8.8 px | none | both cyan |
| candidate, 1000 | 30.25 | same | same | 15.1 px | none | both cyan |

Both arms drew the two-curve circle without the candidate text: this baseline did **not** repeat the
`<ot-circle>` invention seen in `review/2026-11-13-geometry`, and needed no lint retry. Pointable ids
existed in both (`medelpunkt`, `radie`; the candidate also gave the arcs ids) and pointing at `radie`
thickens the radius visibly at both sizes.

So the only observable difference on the circle page is that the candidate's `color="cyan"` on both
curves makes one circle of one colour, where the baseline's two unpainted halves take two series
colours — visible at 1000×700 and mild at 370×610. The recipe line is therefore justified as
"document the supported shape and use one colour", not as "fix a defect in this batch": one baseline
page is too little to contradict the earlier invention, and it is explicitly not a reliable-gain claim.

The answer-leak clause in the candidate ("given measures are shown, the area is not drawn") was not
needed in either arm — neither text contained `area`, `50,2`, `cm²` or `omkrets`. It is precautionary,
kept because the page is one multiplication away from the answer and the clause costs one sentence.

## Positioned text: v1 and v2 both lose to the baseline on a wide label

Drawn angle from the two segments: 59.83° in all three arms on the given 60° rays. Blank cells mean
the arm has no such measurement.

| Arm | "60°" from vertex | "60°" inside the wedge | Widest overlap with a leg | "Vinkelben" from the leg end | "Vinkelben" crosses its leg | Spare dots in the figure |
|---|---|---|---|---|---|---|
| baseline (point labels) | 4.3 / 4.4 em | yes | −12.6 px (clear) | 3.5 em | −18.7 / −32.5 px (clear) | 2 |
| candidate v1 (`ot-text`) | 3.5 / 3.7 em | yes | −15.9 px (clear) | 1.8 / 1.9 em | **+9.1 / +13.6 px** | 1 |
| candidate v2 (sharpened) | 3.1 / 3.3 em | yes | −13.8 px (clear) | 1.3 / 1.4 em | **+18.1 / +29.1 px** | 1 |

(pairs are 370×610 / 1000×700; a positive overlap is the text's box reaching back over the stroke)

- `ot-text` did what the candidate says: the 60° label sits closer to the vertex, is centred and
  clear of both legs, and no longer leaves an anchor dot. The baseline's anchor points put two bare
  dots in the figure — one at (0.9, 0.5) in the middle of the angle, unexplained to the child, one at
  the slanted leg's end — because `<ot-point>` always draws its marker.
- The wide label is where the candidate loses. A ten-character text centred on a point 1.3–1.9 em
  beyond a slanted leg reaches back over it; the baseline's `label-pos="ne"` offset (0.18 em right,
  1.25 em up of the anchor) keeps the same text clear at 3.5 em from the end.
- Sharpening the sentence (v2) made it **worse**, not better (9→18 px at 370, 14→29 px at 1000).
  Telling the small model that a text is centred did not make it compute half a text width. This is
  negative evidence about reference wording, not about the tag: the missing piece is an offset
  (`label-pos` on `ot-text`), which is a runtime change and out of scope here.
- The patch job moved both labels on the live page with two `<ot-patch>` ops against existing ids,
  `missing_targets: []`, no patch issues, ids kept by the replacement. The 60° label moved to
  2.5–2.6 em from the vertex; "Vinkelben" still crossed its leg by 8.7 / 12.9 px even though the ask
  said explicitly not to touch the line. Ids after the patch: `gradtal`, `vinkelben`, `vinkelspets`,
  `ben-1`, `ben-2`.

## What the reference change is, and what is not proven

`screen/REFERENCE.md` gains two blocks under the coordinate system: the two-curve circle (with
pointable ids, one colour and the given-measure/answer rule) and `ot-text` (centred, no dot, no
offset, wide text belongs on a point label). Only the parts with evidence are in the lines: the wide
text fallback is the measured failure of v1/v2, so the line points at the construct that worked.

Not proven, or still open:

- One job per arm. The circle improvement (one colour) is a single pair; the earlier invention of
  `<ot-circle>` came from a different batch and was not reproduced here.
- No arc/sector, tangent, inscribed-angle or circle-with-a-cut case was run. Two `ot-fn` halves draw
  a closed circle with vertical tangents at x = a ± r and nothing else; they do not support an
  educational circle task that needs a visible arc, an angle at the centre or a construction line.
- A circle whose centre is off the x-axis needs the shifted form (`sqrt(16 - (x-a)^2) + b`), which the
  candidate only describes in words; no page tested that.
- `ot-text` has no visible pointing feedback (measured, three ids). A reference line cannot fix it.
- The English shipped lines were not run through the model; the tested wording was Swedish.
- Pane controls: the jobs rendered and were measured at 370×610 for generation; both sizes were only
  measured afterwards. A real Chromebook pane and a real child were not involved.
- Label placement inside polygons and side labels is the old shell (PR #56 is not on `main`); no
  conclusion here covers the side-label defect recorded in `review/2026-11-13-geometry`.

## Repeat

```sh
# four page jobs (key from $OPEN_TUTOR_ENV; never printed)
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env SCREEN_MODEL=gemini-4-hydrogen SCREEN_API=chat \
  SCREEN_REASONING=low SCREEN_THINKING= server/bin/with-env uv run --project server python \
  screen/tools/probe_circle_text.py run --out /tmp/circle-text --cases \
  cirkel-bas,cirkel-ref,vinkel-bas,vinkel-ref,vinkel-ref2

# one real tutor follow-up on the delivered candidate page
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env ... probe_circle_text.py patch \
  --dir /tmp/circle-text --case vinkel-ref

# re-render and re-measure saved bodies: no provider call, no key
uv run --project server python screen/tools/probe_circle_text.py measure --dir screen/review/2026-11-13-circle-text/raw

# what the two tags really do, by hand: no provider call
uv run --project server python screen/tools/probe_circle_text.py selftest --out /tmp/circle-recipe
```

`measure` is the repeatable tool: per case folder it writes `measure.json` (per size: font, lint,
drawn arc extents in graph units, segment lengths against their labels, the drawn angle, each label's
box against the line it sits next to, ids, pointing effect, visible text and any forbidden string) and
the screenshots at both sizes. It makes no model calls and needs no key; Chromium still fetches the
public CDN libraries and fonts. It is not a network-free CI test, and no test in the repo depends on it.

Worker suite on this base after the reference edit: see the PR body (the reference is read by every
job, so the full configured server suite was run once).
