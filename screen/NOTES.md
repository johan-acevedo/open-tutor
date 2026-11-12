# Smart Screen: choices, tried and rejected

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
  `<script>` in a body still runs (HTML stays flexible), but no example uses it.
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
