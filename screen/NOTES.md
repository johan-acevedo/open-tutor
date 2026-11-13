# Smart Screen: choices, tried and rejected

## Graph label placement + overlap lint, 2026-11-13

Side/segment labels in `ot-graph` are placed from the polygon winding with a
measured two-axis clearance, and what is still crowded becomes `crowded: label …`
lint with the fix direction instead of a silent overlap. Auto ranges widen for
the longest side label; author-set ranges win and leftovers are flagged honestly.
The bounded retry repairs from that wording (fresh Hydrogen-low plan job: first
attempt crowded the notch, retry dropped one label, zero residual lint). Point
anchors, ticks and hidden labels are never flagged; no length lint. Repeatable
before/after: `tools/check_graph_labels.py` fails on the prior shell and passes
here; renders in `review/2026-11-13-graph-labels/`. Genuinely tight notches stay
flagged, not silently clean.

## Toolbox follow-up, 2026-11-13

Fit correction: a visual's old absolute pixel positions must not size the next font
measurement. Generated drawing layers, chart canvases and image views are excluded only
while measuring their em-sized hosts, then redrawn. The six-node mind map now uses the
pane instead of shrinking into its upper half. Ten visual kinds are checked through
portrait/wide resizes by `tools/check_fit.py`. Synthetic and new Hydrogen low evidence:
`review/2026-11-13-growable-fit/`. Real dense pages still warn; lint was not weakened.

Successive patch previews now replay earlier patches before the candidate. This fixes
false missing-id lint for ids inserted by a previous patch; the model already received
that source/history. Genuine patch errors are saved and sent to the tutor as a failure
before any RPC, preserving the visible page. Preview animations finish immediately
instead of a fixed one-second pause; child animations are unchanged. Synthetic real
Chromium evidence and checks: `review/2026-11-13-patch-history/`.

Timing now takes priority. New jobs stop at 20 s and aim for 12 s. Clean pages
use a look only while that soft budget has room; known lint buys one capped
correction directly. Each optional model call is at most 6 s, and a look never
starts a second correction chain. This can miss answer leaks on clean pages.
Five real DeepSeek jobs now stayed below 20 s but did not meet 12 s; the first
model call alone took 12.4–16.5 s. See `review/2026-11-13-page-budget/` for the
evidence, separate-batch caveat and the old/new look comparison.

Model comparison controls are prepared without live calls: `SCREEN_MODEL=gemini-4-hydrogen`
uses Google and `GEMINI_API_KEY`, thinking `low` or `medium` via `SCREEN_REASONING`.
DeepSeek accepts `SCREEN_THINKING=disabled` as a separate toggle, omitting effort.
Recorded HTTP tests cover routes, keys, image inputs and incompatible settings;
live acceptance and quality are still for the lead to verify. Commands are in
`docs/smart-screen.md`. No Go probes/helpers until Johan settles billing.

Pane/repair review: corrected-page renders are bounded too, with a short margin
for saving and delivery. A renderer timeout keeps the already rendered page.
Retry acknowledgements and patch responses are not accepted as page bodies.
The failing-before/passing-after regression and real DeepSeek renders are in
`review/2026-11-13-pane-retry/`.

Page and patch markup is sanitized before it joins the live document. Both
composers escape the body into an inert template. Boot reads that text, then
uses native `setHTML` or loads DOMPurify 3.4.17 when the native method is absent.
The same parser handles patches. Scripts, event handlers, model styles and
embedded documents are removed. Teaching attributes such as `correct` and `later`
survive. Invalid colour markup cannot be interpolated into component SVG.
If the fallback cannot load, source remains inert and the shell reports a boot
issue. It never inserts the original unsanitized HTML as a fallback.

`tools/check_sanitizer.py` exercises both paths, blocked fallback loading,
component/reveal preservation and example RPC sizes. The largest example's
serialized `PageItem` is 1,348 UTF-8 bytes. Escaping happens after RPC, so it
does not enlarge the message. `tools/probe_local_shell.py` runs the existing
live E2E probe with local built assets in that browser only, without restarting
the dev services. Safari's actual browser remains Johan's device check.

Narrow panes up to 600 px use one column for rows and grids even when the pane
is landscape. Their title is smaller, and the reference asks for two to four
title words. Lint reports phone text below 16 px, includes any fallback scale,
and flags titles longer than two lines. It does not enforce delivery policy.
The server owns correction and the decision to show a page with remaining issues.

Real DeepSeek pages, patches, screenshots and repeatable commands are in
`review/2026-11-13-readability/`. The line page and both patches still get dense
on phones. The line page also repeats an answer before asking for it. The
reference now explicitly includes visual answer leakage, but prompt wording
alone did not solve either problem.

`tools/check_readability.py` checks actual browser reading order and warnings.
`smalltest/run.py` accepts `--model`, `--requests` and `--sizes` so a targeted
DeepSeek check need not call Muse or use yesterday's pane sizes.

Map layout for a full län map (this change, on top of `fix/map-side-key`): the 21-letter key
used to live inside the map box, over the sea, and the country was fitted to the `sverige` view
box, which keeps Norway, Finland and the Baltic as context. On a 940×319 pane that left a
97×220 px country with 9 px letters; on a phone the key covered Skåne and Götaland and Sweden
was 45×104 px in a mostly empty 327×217 px box.

Two boxes in normal flow, never an overlay:

- **The drawing box** (`.ot-map-canvas`) holds the svg, the labels and the region shapes.
- **The key** is its own flow box: a wrapped strip under the drawing box on a phone, an upright
  column (or two) beside it on a wide pane. Nothing is drawn behind it, so no fade or gradient
  is needed to hide the map under the letters.

The map is fitted to the 21 region polygons themselves, not to the `sverige` view, with 4.5 %
padding. Sweden now covers 91 % of the drawing box height on every pane instead of ~48 % on a
phone, and the neighbours stay as context at the edge of the box.

A pane keeps the key beside the map only when it is at least 480 px wide and clearly landscape
(w > 1.3 h); otherwise the key goes under the map. On a phone the region map also asks for a
taller share of the page (`min-height: 16em` below 600 px) so the box is not a short wide strip.

Same pages, same panes, before → after (`tools/check_map_key.py`):

- 1000×700: country 138×314 in a 945×340 overlay box → 136×309 in a 682×340 drawing box with a
  251 px key column; 20 → 21 codes at 13.1 px, no `crowded` issue.
- 370×610: country 45×104 → 85×192 in a 330×211 drawing box; key moved out of the map; 12 → 20
  codes on the map, still `crowded` (the 21st is dimmed in the key).
- 760×900: 140×320 in 691×350 → 141×318 in 407×350; 21 codes, no `crowded`.

Not done: a phone box stays landscape (330×211). A portrait box would need the page text at
12–13 px on a 610-tall pane, so the honest cure is less page content; the shell reports
`dense` (15.25 px) and `crowded` on these long pages instead of hiding it. The `dense` report is
what makes the server offer one lint retry on a phone.
`tools/check_map_key.py` pins the separate key box, the tight bounds, the codes, pointing and
marking, and `tools/check_prior_shell.sh` shows the same checks failing on the shell from
PR #41. Evidence: `review/2026-11-13-map-phone/`.

Work package 1 of `docs/smart-screen.md` (example screens, shell and components), 2026-11-12.

## Layout of this folder
- `shell/frame.html`, `shell/shell.css`, `shell/shell.js`: the shell. `frame.html` is the template; the CSS and JS
  are inlined into it with the page body (`tools/screenkit.py: compose()`). About 125 kB, 36 kB gzipped.
- `REFERENCE.md`: what the screen model reads (about 2 000 tokens).
- `examples/`: eight page bodies, each with one `.patch.html`, and `index.json` with the tutor's requests.
- `tests/`: pages that exercise components the examples do not use.
- `tools/screenkit.py`: compose, and render in headless Chromium inside a sandboxed frame like the app.
  `tools/prompt.py`: the static prompt (role + reference + examples, about 4 300 tokens).
- `smalltest/`: the test with the two small models (`requests.json`, `run.py`; output in `out/`, not committed).
- `gallery/`: `build.py` renders everything into `gallery/site/` (not committed); `serve.py` serves it.

## Main choices
- **The model writes no JavaScript.** Every component is a declarative tag with attributes and plain child text.
  Small models get JS signatures, escaping and timing wrong; they get HTML attributes right.
  Model scripts and event handlers are stripped before pages or patches enter the live DOM.
- **Fit by font size, not by scaling a fixed canvas.** Everything is in `em`. The shell binary-searches the largest root
  font size (capped at about 1/23 of the pane height and 1/21 of its width) at which the page fits without scrolling,
  then lets growable visuals (graph, map, chart, image, clock, balance, cycle, mind map) take the spare height and draws
  them at their final pixel size. Text reflows, so the same body works at 1366×768 and 390×844; rows stack in
  portrait. A visual that is crowded asks for more height or smaller text and the shell refits (at most six times).
  If nothing fits at 11 px the page is scaled down and an issue is reported.
- **A page is hidden until finished.** `html.ot-boot` hides the body until libraries, fonts, maps and images are in
  and every visual is drawn; a CSS fail-open shows it after 8 s if the shell never runs.
- **The shell reports problems.** `ready` carries `issues`: KaTeX errors, unknown `ot-` tags, duplicate ids, a page
  that only fits below 14 px, crowded diagrams, unknown countries, images without credit, patch targets that do not
  exist, reveals with nothing to reveal. This is the "look, fix" half of "draft, look, fix, then show": the Screen
  agent can fix from the list before it even looks at the screenshot.
- **Patches are HTML too**: `<ot-patch target="id" do="replace|append|prepend|before|after|remove|reveal">`. Same
  syntax as a page, so the model needs to learn nothing new. A changed element fades in (from 35 % when replaced,
  from 0 when new) and gets a soft violet glow that fades over 2 s, drawn as an overlay so it never disturbs layout.
  Components redraw synchronously inside the patch task, so there is no blank frame. A patch keeps the current text
  size unless the page would overflow.
- **Reveal without layout shift.** `ot-hidden` reserves the answer's space under a striped cover; `later` on any
  element keeps its space invisible. Revealing moves nothing else on the page.
- **Swedish conventions built in.** Decimal comma inside maths (`$9,5$` is typeset correctly without `{,}`), true minus,
  `sv-SE` number formatting on axes and charts, f.Kr./e.Kr. on timelines, 24-hour digital time.
- **Sweden's 21 län ship with the shell, not with the page.** `<ot-map regions="län">` needs the region
  polygons. The 10m Natural Earth admin-1 world file is 40 MB (over jsDelivr's limit) and the 50m file has no
  Sweden, so `shell/data/lan-sverige.json` holds the 21 features cut out, topology-simplified with mapshaper and
  quantised to 1/1000 degree (28 kB; see `shell/data/README.md`). `compose()` inlines it in the frame, like the
  shell itself: no request, and nothing in the page body (LiveKit RPC is ~15 kB). Letter codes on the map
  (`AB` … `BD`) plus a key, since 21 names never fit: beside the map on a wide pane, under it on a phone (see
  "Map key layout"). Codes are sized by the map, not by the page font,
  and a label that cannot sit over its region moves to a free spot with a leader line, or is left out (its key row
  dims) with a `crowded` issue when the pane is too small. Every region is pointable as `lan-<bokstav>`.
- **Computed, not written, maths procedures.** `ot-written` computes uppställning itself (carries, växling, partial
  products, liggande stolen with step-by-step `steps="n"`), so a small model cannot get the arithmetic wrong.
  Right angles in polygons are detected and marked; timeline events sort themselves by year.

## Libraries
| Use | Choice | Why |
|---|---|---|
| Maths | KaTeX 0.19.1 + auto-render | Models know TeX very well; same version as the web app |
| Coordinate system | JSXGraph 1.14.1, wrapped in `ot-graph` | Proven renderer; the wrapper adds our grid, Swedish tick labels, label placement and equal units |
| Charts | Chart.js 4.6.1, wrapped in `ot-chart` | Proven; the data comes from a plain `<table>` the model already knows; values are printed on bars |
| Maps | d3-geo (d3 7.9.0) + Natural Earth 50m + historical-basemaps | Replaces Leaflet, see below |
| Images | Wikimedia Commons API (`query=`), or `src` + `credit` | Free, licensed, credit comes with the file |
| Font | Lexend (variable, fontsource) | See below |
| Teaching aids, timeline, cycle, mind map, steps, written methods | our own, SVG + HTML | No library fits a dark, calm, Swedish school style in one tag |

## Tried and rejected
- **Leaflet for maps → d3-geo with vector data.** Leaflet needs a tile server; OpenStreetMap's tile policy asks for a
  valid Referer, which a sandboxed `srcdoc` frame cannot send, and tiles are busy, light-themed and slow on a
  Chromebook. A static vector map is calm, crisp at every size, matches the dark theme, needs no attribution beyond the
  data, and lets us colour a country or a historical realm by name (Swedish, English or ISO code). Pan and zoom are not
  needed on a page the tutor talks about. Natural Earth's `ISO_A2` is `-99` for France and Norway, so matching also uses
  `ISO_A2_EH`, `ADM0_A3` and the Swedish `NAME_SV`. Its rings are wound the wrong way for d3 and are rewound.
- **Atkinson Hyperlegible Next → Lexend.** Atkinson draws the zero slashed (0̸) with no stylistic set to turn it off;
  in Swedish maths that reads as Ø. Lexend has a plain zero, clear letterforms and is designed for reading ease.
  Andika (single-storey a, as children write it) is the alternative for åk 1–3 if Johan prefers it.
- **Scaling a fixed design canvas (as boards do today).** It makes text tiny on phones and wastes width on wide
  panes. Font-size fitting reflows instead.
- **Ring layout for cycles and mind maps on phones.** Boxes overlapped. In portrait they become a column with
  arrows down and a return arrow on the side (cycle) or a trunk with branches (mind map).
- **Deciding the column layout per box size.** It flipped between attempts of the fit loop and shrank a page to 11 px;
  the rule is now simply "portrait screen → column".
- **Labels outside a visual's box.** They counted as page overflow and forced a refit after a patch; labels are now
  pulled back inside their visual.
- **Fading a replaced element in from 0.** The old content vanishes first, so it read as a blink; replacements now
  start at 35 % opacity.
- **Mermaid for diagrams.** Not adopted: several MB of script, its own layout surprises, and hard to theme calmly. The two
  diagram tags cover the common school cases (cycle, mind map); labelled parts are `ot-image` + `ot-label`.
- **Leading zeros, carries for multi-digit multiplication.** Carries are drawn for addition, subtraction (växling) and
  one-digit multiplication only; more would clutter the uppställning.

## Content security policy for page frames
Today's board policy plus one directive:
```
default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net;
style-src 'unsafe-inline' https://cdn.jsdelivr.net; font-src https://cdn.jsdelivr.net; img-src data: https:;
connect-src https://cdn.jsdelivr.net https://commons.wikimedia.org
```
- `connect-src https://cdn.jsdelivr.net`: maps fetch their GeoJSON (Natural Earth, historical-basemaps).
- `connect-src https://commons.wikimedia.org`: `ot-image query=` searches Commons. If the Screen agent resolves
  images on the server instead (recommended for production, see below), this part can go.
- `'unsafe-eval'` stays: function terms in `ot-graph` are compiled with `new Function` after a whitelist check.
The frame stays `sandbox="allow-scripts"` without same-origin. Answers and drafts leave the frame only by
`postMessage`; the parent must check `event.source === iframe.contentWindow` (the origin is `"null"`).

## Measured
- Ready time in headless Chromium on dell5500 (libraries warm in cache): 0.2–0.6 s for most pages, 1.3 s for the map
  page (three GeoJSON files, about 1 MB compressed).
- A second sandboxed frame in the same app page reused the cached libraries (`transferSize` 0), so the opaque
  origin does not defeat the HTTP cache in Chromium.

## Not done or not happy with yet
- `ot-image query=` takes Commons' first good result; nothing filters what a child might see. The Screen agent should
  search on the server, look at the result (it sees its own render before the child does) and write `src` + `credit`.
- The liggande stolen layout follows the common Swedish textbook form as I know it (quotient above, dividend under
  the line, divisor after a vertical bar). Johan or a teacher should confirm it against the children's books; kort
  division and trappan are not built.
- Maps load about 1 MB of GeoJSON per page; a trimmed, pre-simplified file served from our own origin would be faster.
- Phones: a dense page drops to 15–16 px text. That is readable on a phone in the hand, but the screen model should
  prefer fewer blocks.
- Only Chromium was used to render. The shell avoids newer CSS (`:has`, nesting, container queries, `@starting-style`)
  and uses custom elements, flexbox, grid and Web Animations, all widely available, but iPhone Safari has not been tried
  on a real device.

## Small-model test (2026-11-12)

Five requests the examples do not cover (`smalltest/requests.json`), one page and one patch each, sequential calls on
the OpenCode Go subscription. Muse Spark 1.3 Contributor: Responses API, reasoning minimal. DeepSeek V4.1 Flash:
Chat Completions, reasoning low. Static prompt about 4 300 tokens; Muse reported it cached from the second call on.
Text size is the root font the shell chose (laptop 1366×768 / phone 390×844); larger is better, 18.5 px is the phone cap.
Run 1 used the reference without the density rule (its text sizes were rendered with a slightly older shell).

| Model | Request | Page: first text / done | Patch: done | Text size laptop / phone | Run 1 (before the density rule): done, text size |
|---|---|---|---|---|---|
| muse | tiotal | 3.11 / 5.17 s | 4.03 s | 33.25 / 18.5 px | 4.16 s, 33.25 / 18.5 px |
| muse | norden | 3.07 / 5.5 s | 3.93 s | 33.25 / 18.5 px | 5.45 s, 31.5 / 18.5 px |
| muse | verb | 5.65 / 8.15 s | 6.35 s | 33.25 / 18.5 px | 3.88 s, 31.75 / 18.5 px |
| muse | andragrad | 4.51 / 7.34 s | 7.43 s | 17 / 13.75 px | 6.45 s, 18.25 / 13.25 px |
| muse | vikingar | 6.8 / 9.71 s | 5.65 s | 29.5 / 18.5 px | 6.07 s, 28.25 / 16 px |
| deepseek | tiotal | 5.15 / 6.72 s | 3.59 s | 33.25 / 18.5 px | 8.6 s, 31.75 / 18.5 px |
| deepseek | norden | 2.56 / 5.98 s | 1.37 s | 30 / 18.5 px | 8.52 s, 19.5 / 14.25 px |
| deepseek | verb | 2.22 / 4.76 s | 1.34 s | 33.25 / 18.5 px | 5.26 s, 31 / 18.5 px |
| deepseek | andragrad | 4.61 / 8.41 s | 2.77 s | 18.75 / 15.5 px | 12.21 s, 14.75 / 11.25 px |
| deepseek | vikingar | 1.67 / 5.37 s | 1.47 s | 29.5 / 18 px | 10.81 s, 24.25 / 13.5 px |

What the outputs show:
- Both models imitate the examples closely: right tags, right attributes, ids where the tutor will act, `ot-hidden` /
  `ot-answer` where the child should work, Swedish notation. No unknown tags, no KaTeX errors, no scripts.
- All ten patches are valid and minimal (append a mark, recolour one country, reveal one gap, replace one point, add
  one timeline event).
- Weak spots: pages get dense when the request is big (andragrad: graph plus a six-step pq solution is too much for
  one phone screen); labels sometimes crowd on maps (the shell now moves them apart); one model put a place outside
  the view (Reykjavik, before `norden` included Iceland). The lint list catches these, so the Screen agent can fix or
  split the page before it is shown.
- Timings vary between runs by a few seconds; one run each, so treat them as indicative.

## Frame protocol notes (2026-11-12 shell fixes)

Full reference at the top of `shell/shell.js`. What the parent can rely on:
- `{ot:'hello'}` (parent → frame) makes the shell post its `ready` message again: at once when it is
already ready, otherwise as soon as it becomes ready. For a parent that attached its listener late.
- A failed boot still shows the page and still posts `ready`, with a `boot` issue describing the failure.
- One overall boot deadline of 10 s: past it the page is shown with whatever arrived, and a `slow` issue
names what was still loading (`libraries`, `map data and fonts` and/or `images`).
- `patched.issues` holds only issues new since the previous `ready`/`patched` report: each distinct problem
(kind + message + element) is reported once, however often later patches re-trigger it.
- `point`/`reveal` to an id that does not exist posts `{ot:'patched', issues:[…]}` at once, with a
"no element with id" issue, instead of sending nothing.
- A patch that itself throws still posts `patched`, with the error as its issue.
- A patch keeps typed answers: drafts go back onto every input that still exists by id. A `replace` keeps
the target's id whatever id the replacement arrived with. Replaced graphs and charts free their
JSXGraph board / Chart.js instance, and a map added by a patch draws from its own data before anything
is reported or shown.

## Pane context, look repair and one lint retry (2026-11-13)

Server side of the readability work (parent's PR #38 brought the shell lint: `dense` below 16 px under
600 px wide, `heading` for a title over two lines). Files: `server/open_tutor/screen.py`,
`server/tests/test_screen.py`.

- The page request now states the pane: `Pane: 370×610 px, narrow. Write one reading column, a short
  title (two to four words) and one teaching step or one visual. No second column, no side panel,
  nothing that needs scrolling.` At 1000×700 it only states the size and "fill it without scrolling".
  The size was already in `meta.json`; the writer never saw it.
- The look pass now gets the page source it is repairing, the ask, the pane and the shell's exact
  issue lines, and checks three things: readability at this pane, faithfulness to the ask, and
  whether the page gives the answer away. For the last one it names the question the page asks and
  checks every visible number, mark, label and picture step against it. Lint only sees layout, tags,
  maths and ids; the prompt says so instead of pretending lint finds leaks.
- One corrective retry after the look when actionable lint remains: ask + pane + the source it is
  correcting + the exact lint text. Advisory issues (`slow`, `load`, `image` credit) never retry, and
  `SCREEN_LINT_RETRY=0` turns it off. A retry that fails, times out or comes back with more actionable
  lint is dropped and the page in hand ships.
- Delivery comes first: optional steps start only while a full-size model call (roughly the first
  answer's time) plus the final render still fit the 45 s job limit, and the look/retry calls are
  wrapped in a timeout for the time that is left. Remaining actionable lint goes to `meta.json`
  (`residual_lint`, `repair`) and the log line `delivered with residual lint`. No model fallback, and
  patches are not retried.

Real DeepSeek V4.1 Flash low, 2026-11-13, one page each (`Screen` with `get_pane_size`, default model
call and renderer, pages in `/tmp`; ask: 3/4 + 1/8 for the two pane sizes):

| Case | Pane | Total | Look | Retry | Deliverable |
|---|---|---|---|---|---|
| fractions 3/4 + 1/8 | 370×610 | 30.35 s | fixed the body | not needed | lint clean; 370×610 17.5 px, 370×558 17 px, 1000×700 21 px |
| fractions 3/4 + 1/8 | 1000×700 | 32.16 s | OK | not needed | clean at 1000×700; dense (13 px) when re-rendered at 370 wide, as expected from the wide ask |
| leak check, "how many eighths is 3/4" | 370×610 | 19.57 s | OK | not needed | no answer shown: 3/4 bar plus an empty eighths bar and a "2 per quarter" hint |
| short division, question + answer steps | 370×558 | 37.69 s | hid `2 och 4` behind `later` | not needed | real leak catch: the first body printed the answer digits as a visible step |
| pq-form, graph + four steps | 370×430 | 33.35 s | rewrote the steps, still dense | **skipped: no time left** | page delivered at 33 s with `residual_lint: dense 12.75px`, logged and in `meta.json` |

What this does not fix: the model's own judgement still decides a leak (the hint "2 åttondelar på varje
fjärdedel" passed, and it is a hint rather than the answer); and the step-note column can overflow the
card at 370×558 without the shell reporting `overflow` (seen in the division page), so that page still
needed a human glance.
