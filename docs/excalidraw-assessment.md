# Excalidraw as Open Tutor's teaching board: assessment

Checked 2026-11-04. Research only: no application code changed, nothing installed into this repo, nothing committed. **Status:** the recommended `diagram` card was built afterwards; see [diagram-card.md](diagram-card.md) for what was implemented, what the spike found and the open limits.

**Evidence labels.** *Read* means I read source, docs or package metadata. *Ran* means I ran it in a throwaway Vite spike outside this repo (React 19.3.1, Vite 8.3.5, `@excalidraw/excalidraw@0.18.1`, headless Chromium 1252 on a Linux desktop, the same React and Vite versions as `web/package.json`). *Untested* means a claim I could not check. Nothing here was run on a Chromebook, Windows or a phone.

## Answer

**Do not replace the whole board with Excalidraw. Use it, if at all, as a new `diagram` card inside the current DOM board, for mindmaps, flow-style diagrams and annotated sketches.** Equations, homework paper, HTML demos, videos and resource cards stay as they are.

Excalidraw is a good drawing engine and a poor fit for most of what the board does today. Its one big payoff for us is that it makes *incremental, ID-addressed edits to a diagram* straightforward. That is where our current board is weakest: the mindmap is a card of text chips with no connectors, and `show_svg` makes the model write a whole SVG each time and offers no way to edit one part. A second payoff arrives later if you ever allow student editing, because that is a prop flip rather than a rebuild.

I would not adopt it yet. I would run the 2-day spike below first, because three behaviours I hit (dark-theme colour inversion, font-load clipping, bindings that do not follow raw edits) mean the agent-facing layer is real work, not a thin wrapper.

## What we have vs what Excalidraw adds

Read from `web/src/components/Cards.tsx`, `server/open_tutor/board.py`, `docs/protocol.md`.

| Need | Today | With Excalidraw |
|---|---|---|
| Equations, steps, row highlight | KaTeX `steps` card with `board.focus` on a row. Good. | Nothing better. Excalidraw has no LaTeX. Keep ours. |
| Mindmap / book-review ideas | `mindmap` kind: centre plus chips, no arrows. | Real nodes and bound arrows, pan/zoom, add node-by-node while the tutor talks. Clear gain. |
| Diagrams | Model writes raw SVG (60 KB cap), sanitised, replaced wholesale. | Edit one node or arrow by id. Gain, but we must supply layout. |
| Homework, resources, HTML, video | DOM cards, sandboxed iframes, `board.show` ack. | Excalidraw could embed iframes, but our sandbox and quiet-mode logic would not carry over. Keep ours. |
| Speech/visual sync | RPC `board.show` replies only after the item mounts. | No built-in acknowledgement. We reuse our own pattern (below). |

The BUILD-PLAN rejected tldraw because its SDK needs a production licence key. That objection does not apply: Excalidraw is MIT. The other objection, "a canvas editor adds interaction work", mostly disappears in view mode.

## Agent control: what is supported and what is our job

Released API (0.18.1, tagged 2026-04-21) supports `updateScene`, `scrollToContent` (with `fitToViewport`, `animate`, `duration`), `getSceneElements`, `addFiles`, `onChange`, and `convertToExcalidrawElements`, which turns compact "skeleton" objects (shapes with a `label`, arrows with `start`/`end` ids) into full elements. It has no highlight, no layout, no acknowledgement and no "run these operations" API. Newer, **unreleased** builds (preview `0.18.0-4ce8305`, 2026-10-27, read only) add `setViewport`, `selection`, `mutateElement`, `applyDeltas` and render overrides. `master` has also made a breaking export change (`exportScene` replaces `exportToSvg`), so pin an exact version.

What I observed when running 0.18.1:

- **Ids are discarded by default.** `convertToExcalidrawElements` regenerates every id unless you pass `{ regenerateIds: false }`. The official MCP passes `false`. Without it the model's ids (`n1`, `e2`) mean nothing.
- **Bindings are metadata, not geometry.** An arrow with only `start`/`end` ids got a 100 px horizontal default shape, though the binding was recorded. An arrow with explicit `points` drew correctly. When I moved a bound rectangle through `updateScene`, its label text and the arrow stayed behind. So **our code computes every position, arrow endpoint and bound-text move.** The unreleased `mutateElement`/`applyDeltas` may fix that (untested).
- **Highlight is ours.** Changing `strokeColor`/`backgroundColor` through `updateScene` worked and was visible in the next frame. That is our `focus` operation.
- **Camera works.** `scrollToContent(ids, { fitToViewport: true, animate })` zoomed correctly on the released API.
- **Acknowledgement is ours.** `updateScene` returns nothing and applies on the next render. Use the same trick as `useReportMounted`: wait two animation frames, confirm the ids exist in `getSceneElements()`, then reply `{ok:true}` to the RPC.

### Keeping the model away from scene JSON

Never let the model emit Excalidraw JSON. Give it a small operation set and keep scene state, ids and layout in our code:

```
diagram_create(title, nodes[{id,text,role?}], links[{from,to,label?}], layout: "radial"|"flow"|"columns")
diagram_add(nodes?, links?)        // appended, laid out by us
diagram_edit(id, text?, role?)     // role -> colour from the style guide
diagram_remove(ids)
diagram_focus(ids | null, zoom?)   // highlight + camera
```

Our code does layout (a radial mindmap is a few lines; flows can use Mermaid, see appendix), maps to skeletons, applies them to a serialised queue, and replies after render. The official Excalidraw MCP uses a looser format: the model writes JSON elements with `cameraUpdate`, `delete` and `restoreCheckpoint` pseudo-elements, and a cheat sheet in the prompt. It works for a chat assistant but costs many tokens per diagram, which hurts a voice loop.

## Math, chemistry, Swedish, images, interactive content

- **Math.** No LaTeX. Unicode math text works, but accuracy and typography are weaker than KaTeX. I rendered KaTeX **inside** the scene through `renderEmbeddable` and `validateEmbeddable` (an `embeddable` element carrying a private `ot:` link): fractions and ⇒ rendered cleanly in dark card styling. Two caveats: a small "open link" icon appeared on it in view mode (hiding it was not tested), and I did not test how it behaves while zooming. Verdict: keep equations in the DOM `steps` card; use in-scene KaTeX only for short labels.
- **Swedish.** Excalifont's unicode ranges cover å ä ö Å Ä Ö, ×, ÷, `·` and the true minus U+2212 (read from `fonts/Excalifont/index.ts`; rendering confirmed in the spike).
- **Superscripts, subscripts, Greek capitals.** U+00B2/B3 (²/³), U+2082 (₂) and U+0394 (Δ) are **not** in Excalifont. They rendered through fallback fonts, so `H₂O` and `x²` came out visibly mixed-typeface but readable.
- **Chemistry.** Excalidraw has no molecule or bond model. A double bond would be two lines we position ourselves. For structure drawings I would render server-side from SMILES to SVG with a cheminformatics library and show it as an image or DOM card (untested; library not chosen). Excalidraw suits labelled reaction flows, not skeletal formulas.
- **Images and uploads.** Image elements accept PNG, JPEG, WebP, SVG and others via `addFiles` data URLs (read from `constants.ts`). Worksheet annotation (shapes over a photo) is possible, but the arrows' positions would come from the model's guess at image coordinates. I did not test how accurate that is, and I expect it to be the weakest of the five acceptance cases.
- **Progressive reveal.** Works by appending elements: five node-plus-arrow steps with a frame wait each took about 470 ms total in the spike. There is no built-in draw-on animation in the released API (the official MCP fakes it with `exportToSvg` and `morphdom`).
- **HTML, video, resources.** Keep as DOM cards.

A **hybrid DOM + Excalidraw** surface is the better fit: the existing scrolling stack of cards, with one card type hosting an Excalidraw canvas. That keeps `board.show` / `focus` / quiet-mode logic unchanged.

## Embedding and styling

- **Build.** It built cleanly with React 19.3.1 and Vite 8.3.5 in about 2 s. Peer range is React 17–19. Entry JS was 1.57 MB raw, about 487 KB gzipped, plus 172 KB CSS (31 KB gzipped, including KaTeX's CSS in my test). Roughly 220 more chunks (Mermaid and others) load lazily. Self-hosted fonts are about 480 KB excluding the 13 MB CJK pack, which we can skip. **Load it lazily** so sessions without a diagram never pay this. I did not measure our current bundle, so I cannot give the delta.
- **Required setup.** `import "@excalidraw/excalidraw/index.css"`, copy `dist/prod/fonts` into `web/public/`, set `window.EXCALIDRAW_ASSET_PATH` before it loads, and give the container a non-zero height (installation docs).
- **Dark theme gotcha (ran).** `theme="dark"` inverts stored colours. My `#F3F5F8` text came out dark, `#22D3EE` came out teal, and the `#181B22` background came out light grey. Using `theme="light"` with `viewBackgroundColor: "#181B22"` and explicit light stroke colours reproduced our palette exactly. Its menu and zoom chrome stays light-styled and needs CSS or hiding.
- **Font-load gotcha (ran).** Text created before Excalifont loaded was measured with a fallback font and clipped when drawn. Awaiting `document.fonts.load("28px Excalifont", "Åäö")` before converting fixed it.
- **Look.** The default hand-drawn style is friendly. Whether it suits 15-year-olds is your call; `roughness: 0` and the Nunito or Helvetica fonts are available (untested visually).
- **Read-only.** `viewModeEnabled` with `zenModeEnabled` worked: no drawing toolbar, only a menu button and zoom buttons remained. Gesture panning was not tested. Student editing later means switching the prop and exposing the toolbar.
- **Mobile and accessibility.** It rendered in a 390×844 touch context. Pinch and pan gestures were not tested. The canvas exposes no accessible tree (two `<canvas>` elements, no ARIA labels), so a screen reader gets nothing; we would need a caption or text alternative. `exportToSvg` is a useful fallback: the 7 KB SVG I exported had real `<text>` nodes, the right Swedish glyphs and an embedded font subset, and could feed our existing `SvgCard`. It does not include the KaTeX embeddable.

## Licensing, self-hosting and network

- **Licence.** The library, `@excalidraw/excalidraw`, is MIT. In the installed 0.18.1 dependency tree (239 packages, walked from its `dependencies`, including the lazy Mermaid chain) I found 177 MIT, 38 ISC, 10 Apache-2.0, 7 BSD-3-Clause, DOMPurify (MPL-2.0 OR Apache-2.0), Pako (MIT AND Zlib), and a few CC0/Unlicense/0BSD. Two packages (`khroma`, `fuzzy`) have no plain `license` field in `package.json`; `khroma` ships MIT licence text, and I did not read `fuzzy`'s licence file closely (its `package.json` uses the old `licenses` array). No GPL or AGPL appeared. Fonts are SIL OFL 1.1 (Excalifont's header says so), so ship the licence notice with them.
- **What is required.** Only the npm package and its self-hosted fonts. There is no key, account or backend. Zero requests left `127.0.0.1` in my spike once fonts were self-hosted (browser request log; the only error was a favicon 404). Without `EXCALIDRAW_ASSET_PATH`, fonts default to a public CDN.
- **What is optional and should stay off.** Sharing and live collaboration live in the excalidraw.com app, not in the npm package, which has no socket or Firebase dependencies. Text-to-diagram and AI "magic frame" features need a backend (`aiEnabled={false}`). The official MCP's `export_to_excalidraw` tool uploads an encrypted scene to `json.excalidraw.com`; never wire that into a children's session.

## Reliability and performance with concurrent voice

- **Cost.** 300 labelled rectangles (600 elements) converted in 33 ms and rendered in about 180 ms total on this desktop. A Chromebook will be slower; untested. Cap element count per diagram.
- **Concurrency.** Voice runs off the main thread, but a heavy redraw can still make the page janky. Apply diagram operations through one serial queue, reply to the RPC after render, and keep the authoritative diagram model (nodes, links, layout) in the agent. After a reconnect the agent re-sends a full snapshot. Raw edits are not transactional, so this is our responsibility.
- **Reusable official pieces.** `excalidraw/excalidraw-mcp` (v0.3.2, last commit 2026-03-24) is an MCP **App**: it renders inside a chat host such as Claude or ChatGPT. It cannot act as our LiveKit tool server and has no acknowledgement path. README and `package.json` say MIT, but the repo has no LICENSE file (checked). Reuse its vocabulary and its skeleton-conversion code as a reference only. `@excalidraw/cli` is official but manages Excalidraw+ workspaces with an API key; only `render` to PNG is local. Third-party MCP servers exist (for example `mcp-excalidraw-server` 2.1.2 by `yctimlin`, MIT, updated 2026-10-04). I checked npm metadata only and would not depend on them.

## Smallest sensible spike (about 2 days)

Conceptual files, none created: `web/src/board/DiagramCard.tsx` (lazy; mounts Excalidraw in view mode, preloads fonts, applies a queue), `web/src/board/diagramModel.ts` (nodes/links to skeletons, layout, colours from the style guide), `server/open_tutor/diagram.py` (pydantic ops, id allocation, snapshot), one new `kind: "diagram"` in `protocol.ts`/`board.py`. Reuse `board.show`, `board.update`, `board.focus`.

Acceptance, each judged by eye on a 1366×768 desktop and a 390×844 phone viewport:
1. **Mindmap.** Five of the child's phrases appear one at a time with bound connectors, in our palette, with no clipped text.
2. **Equation.** A `steps` card beside a diagram card shows the highlighted row and a highlighted diagram node together.
3. **Chemistry.** A reaction flow with `H₂O` / `CO₂` labels, plus a SMILES-rendered molecule as an SVG card for contrast.
4. **Worksheet annotation.** A photo with two circled regions, to measure whether model-estimated coordinates are usable. I expect this to fail without a vision grounding step.
5. **Phone.** The diagram fits, pinches and pans, and the fixed bottom bar stays clear.

**Effort (my estimate, not measured):** spike 1.5–2.5 days; a shippable `diagram` kind with the five operations, layout, acknowledgement, snapshot on reconnect and phone CSS 4–7 days; student editing later +3–5 days. Assumes one developer who knows this codebase and no changes to the voice pipeline.

---

## Appendix A: operation to API mapping

| Agent operation | Excalidraw call (0.18.1 unless noted) | Our code |
|---|---|---|
| `diagram_create` | `convertToExcalidrawElements(sk, {regenerateIds:false})`, `updateScene({elements, captureUpdate: NEVER})`, `scrollToContent` | layout, colours, explicit arrow `points` |
| `diagram_add` | same, appended to current elements | placement near existing nodes |
| `diagram_edit` | `updateScene` with a copied element, bumped `version` | also update the bound label |
| `diagram_remove` | `updateScene` with `isDeleted: true` (the official MCP's `delete` pseudo-element does the same) | remove bound text and arrows |
| `diagram_focus` | colour change via `updateScene`; `scrollToContent(ids, {fitToViewport, animate})` | `setViewport` is unreleased |
| acknowledgement | none built in | two-frame wait, then check ids |
| flowchart from text | `@excalidraw/mermaid-to-excalidraw` 3.4.0 (0.18.1 pins 2.2.2); docs-based, untested | optional |

## Appendix B: what I ran

Spike in the scratchpad, not in this repo: `npm install @excalidraw/excalidraw@0.18.1 react@19.3.1 vite@8.3.5 katex@0.19.1`, `vite build`, then Playwright scripts against a static server. Results: scenes rendered as described, KaTeX embed worked, `exportToSvg` produced 7,043 bytes with real text, 300-rect stress converted in 33 ms. Not run: unreleased APIs (types read from the preview package only), gesture input, touch zoom of the KaTeX embed, a Chromebook, Windows, a screen reader, Mermaid conversion.

## Sources (checked 2026-11-04)

- Repository, `master` at `dd2f8fc` (2026-11-03): https://github.com/excalidraw/excalidraw
- Package, `latest` 0.18.1, preview `0.18.0-4ce8305` (2026-10-27): https://www.npmjs.com/package/@excalidraw/excalidraw
- Release 0.18.1 (2026-04-21): https://github.com/excalidraw/excalidraw/releases/tag/v0.18.1
- Installation, fonts, asset path: https://docs.excalidraw.com/docs/@excalidraw/excalidraw/installation
- Element skeleton (beta, `regenerateIds`, bindings): https://docs.excalidraw.com/docs/@excalidraw/excalidraw/api/excalidraw-element-skeleton
- Imperative API (`scrollToContent`, `updateScene`): https://github.com/excalidraw/excalidraw/blob/master/dev-docs/docs/@excalidraw/excalidraw/api/props/excalidraw-api.mdx
- Changelog (unreleased viewport/selection/export changes): https://github.com/excalidraw/excalidraw/blob/master/packages/excalidraw/CHANGELOG.md
- Excalifont unicode ranges and OFL header: https://github.com/excalidraw/excalidraw/blob/master/packages/excalidraw/fonts/Excalifont/index.ts
- Official MCP App (`157aa23`, 2026-03-24): https://github.com/excalidraw/excalidraw-mcp
- Official CLI (`55fe7f4`): https://github.com/excalidraw/cli
- Mermaid converter: https://www.npmjs.com/package/@excalidraw/mermaid-to-excalidraw
- Third-party example: https://www.npmjs.com/package/mcp-excalidraw-server
- Project context read: `README.md`, `PRD.md`, `BUILD-PLAN.md`, `design/STYLE-GUIDE.md`, `docs/protocol.md`, `docs/mobile-readiness.md`, `server/open_tutor/board.py`, `agent.py`, `web/src/components/Cards.tsx`, `Board.tsx`, `useSession.ts`.
