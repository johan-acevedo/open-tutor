# BoardKit 0.1.0 — API reference

BoardKit draws the geometry for you inside SVG. You declare *what* (clock at
10:30, 12 blocks in groups of 5); it computes positions, angles and counts.
Load it with the exact tag below, then call `BoardKit.*`. All drawing stays
inside a 1920×1080 board. Background `#181B22`, text `#F3F5F8`, accents
`#22D3EE` (cyan) and `#A78BFA` (violet). All text is ≥24px by default.

```html
<script src="https://cdn.jsdelivr.net/gh/johan-acevedo/board-kit@0.1.0/board-kit.js"></script>
<svg id="board"></svg>
<script>
var BK = window.BoardKit;
var safe = BK.board(document.getElementById('board')); // {x:60,y:60,w:1800,h:960}
var left = BK.cols(safe, [1, 1])[0];                   // split area, never overflows
BK.clock(svg, left, { hour: 10, minute: 30 });          // it draws, you declare
</script>
```

Every primitive takes `(parent, box, opts)` where `parent` is an `<svg>` or
`<g>` and `box` is `{x,y,w,h}` inside 0..1920/0..1080. Anything outside the
board, or text under 24px, throws an error — never silently misdrawn.

## Layout

- `BK.board(svg?)` → safe box `{x:60,y:60,w:1800,h:960}`. Sets 1920×1080 + bg.
- `BK.rows(box, ratios, gap?)` / `BK.cols(box, ratios, gap?)` → sub-boxes that
  exactly fill `box`. Ex: `BK.cols(safe, [2, 1], 24)[0]`
- `BK.stack(box, count, gap?, dir?)` → `count` equal boxes, `dir 'v'`/`'h'`.
- `BK.text(parent, x, y, str, {size?, fill?, anchor?, weight?})` — `size` ≥ 24.
- `BK.fmtSV(n, decimals?)` → Swedish number: `BK.fmtSV(13.5, 2)` → `"13,50"`.

## Primitives (all auto-fit inside their box)

- `clock(parent, box, {hour, minute, numerals?, highlightNumbers?, caption?})`
  — `hour` 0–23, `minute` 0–59; hour hand angle is exact.
  Ex: `BK.clock(svg, b, {hour: 10, minute: 30, highlightNumbers: [10, 11]})`
  Needs a box of about 320 px on its shorter side (more with a caption); throws a clear error if too small.
- `blocks(parent, box, {n, perGroup, pieceLabel?, groupLabel?, remainderLabel?})`
  — `n` identical pieces in groups of `perGroup`, bracket + label per group
  plus a remainder group. Labels are strings or `fn(count)`.
  Ex: `BK.blocks(svg, b, {n: 32, perGroup: 10, groupLabel: '1 kg'})`
- `portions(parent, box, {count, filled, labels?, caption?, title?})` — `count`
  equal containers; `filled` is a number (first k) or index array.
  Ex: `BK.portions(svg, b, {count: 10, filled: 8, caption: '8 av 10'})`
- `numberLine(parent, box, {min, max, step, mark?, markLabel?, unit?})` —
  throws if `step` does not divide the range evenly.
  Ex: `BK.numberLine(svg, b, {min: 0, max: 10, step: 2, mark: 6})`
- `fractionBar(parent, box, {num, den, label?})` — `num` of `den` parts filled.
  Ex: `BK.fractionBar(svg, b, {num: 3, den: 4})`
- `barModel(parent, box, {parts, total?, caption?})` — Singapore bar;
  `parts` are numbers or `{value, label, highlight}`; throws if the sum ≠ total.
  Ex: `BK.barModel(svg, b, {parts: [2, 3, 5], total: 10})`
- `scale(parent, box, {left, right, tilt})` — balance; `left/right` are
  `{label, sub?}`; `tilt` is `'left'`, `'right'` or `'balance'`.
  Ex: `BK.scale(svg, b, {left: {label: '3 kg'}, right: {label: '3,2 kg'}, tilt: 'right'})`
- `arrow(parent, {x1, y1, x2, y2, label?, color?})` — shaft + head + label.
  Ex: `BK.arrow(svg, {x1: 200, y1: 500, x2: 600, y2: 500, label: 'hälften'})`
- `leader(parent, {tx, ty, text, side?, dx?, dy?})` — label with a leader line;
  auto-moved so it never covers the target `(tx, ty)` and stays on the board.
  Ex: `BK.leader(svg, {tx: 960, ty: 540, text: 'timvisaren står mellan 10 och 11'})`
- `equations(parent, box, {rows, highlight?, size?})` — steps aligned at `=`.
  Ex: `BK.equations(svg, b, {rows: ['8 × 13,50 kr = 108 kr'], highlight: 0})`

Rules: coordinates must be inside the board; `size` must be ≥ 24;
`numberLine` step must divide the range; `barModel` parts must sum to `total`.
Violations throw (e.g. `blocks: n=32 does not divide into even groups of 7`).
Use `try/catch` while drafting; `./check.sh` reports the same problems.

## KaTeX (pretty equations)

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>
<script>renderMathInElement(document.body);</script>
```
Write `\(...\)` / `\[...\]`. Swedish comma needs braces: `\[8 \times 13{,}50 = 108\]`.
Set `.eq { font-size: 44px; }` — KaTeX scales with font-size. Fonts load from
jsdelivr, which the board allows.

## Rough.js (hand-drawn circles, arrows, underlines)

```html
<script src="https://cdn.jsdelivr.net/npm/roughjs@4.6.6/bundled/rough.js"></script>
<script>
var rc = rough.svg(document.getElementById('sketch'));
svg.appendChild(rc.rectangle(x, y, w, h, { stroke: '#22D3EE', strokeWidth: 5, roughness: 2 }));
svg.appendChild(rc.linearPath([[x1, y1], [x2, y2]], { stroke: '#A78BFA', strokeWidth: 5 }));
</script>
```
Measure first with `el.getBoundingClientRect()` (union inner `.base` boxes for
KaTeX), then draw. Keep every coordinate inside 1920×1080.
