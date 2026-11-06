# The diagram card: scope, evidence and limits

Implements the recommendation of [excalidraw-assessment.md](excalidraw-assessment.md): Excalidraw as one new `diagram` card **inside** the existing DOM board, for connected mind maps, flows and simple sketches. It does not replace the board. KaTeX equations, SVG, homework, HTML, video and resource cards, the avatar and the voice route are unchanged. The child cannot edit a diagram. The wire format and the acknowledgement rules are in [protocol.md](protocol.md#diagrams).

## What it does for a child

The tutor can build a mind map or a process while it talks. It starts with the subject, adds one idea at a time as the child says it, corrects a label, removes a wrong branch, and highlights the node it is talking about while the view moves in on it. Existing nodes stay where they are while a map grows. Each tool call returns only after the browser has drawn the change, so the tutor does not talk about something the child cannot see yet.

## Choices

- **Model.** The worker owns each diagram (`server/open_tutor/diagram.py`); the browser draws what it is sent. The assessment suggested keeping the model "in the agent", and that matches how this code is split: the worker already owns board ids and sends whole items, and the browser holds only what was last shown. The model names nodes and links with short ids and never sees coordinates or scene JSON. Five small tools (`show_diagram`, `add_to_diagram`, `edit_diagram`, `remove_from_diagram`, `focus_diagram`) replace asking an LLM for a large raw scene.
- **Whole item, every time.** Each change sends the full diagram with a revision number. The browser rebuilds the scene from it, so a changed label, a removed node or a moved arrow cannot leave a stale label or connector behind, a lost update is repaired by the next, and a reconnect needs no special snapshot message. The cost is that the whole scene is rebuilt on each change; the 24-node limit keeps that small, but it was not timed on a Chromebook.
- **Layout is ours.** The worker picks node centres: a radial map places each new node near its parent in a free spot and never moves existing ones; a flow is laid out left to right by longest path. The browser sizes each box from the measured text, cuts every arrow at the box edges and puts labels at the arrow's midpoint (`web/src/diagramModel.ts`). Arrows are not bound to boxes in the library, because the library does not move bindings for us; the geometry is recomputed instead. Student editing would need bindings.
- **Ordering and acknowledgement.** One lock in the worker runs diagram changes in the order the tools ran; the browser draws the newest revision and answers older waiters with it. `focus_diagram` is a revision like any other, so it is ordered after the edits before it. It uses `board.update` rather than `board.focus`, which stays for `steps` rows.
- **Fonts and network.** `@excalidraw/excalidraw` is pinned to 0.18.1 (exact). Nunito (labels) and Excalifont (library default) are served from `web/public/excalidraw/fonts` with their licence notice; the library is pointed there before it loads. The font files are registered and awaited before any text is measured. No request leaves the app's own origin and the LiveKit connection (checked in the browser run below).
- **Lazy.** The drawing library, its CSS and the Swedish glyph handling load when the first diagram arrives. The entry bundle grows by about 3 kB gzipped (card, validation, model code). The first diagram downloads roughly 1.3 MB raw / 395 kB gzipped over 10 files (byte counts of the built files, not a timing measurement).
- **Chemistry.** Labels such as `Metan (CH₄)` render as text; Nunito has no subscript digits, so they come from a fallback font. There is no molecule or bond drawing.

## Evidence

All of this ran on one Linux desktop with Chromium driven by Playwright, against a local LiveKit server, with the real `Tutor` tools calling the real browser through real RPC: `server/scripts/diagram_browser_probe.py` (fictional material; no model, voice, cloud service or session quota). It is not run in CI.

| Check | Result |
|---|---|
| Swedish mind map grows one node at a time | 4 additions, every step checked: all boxes at the worker's positions, labels centred in their boxes, arrows 3–9 px from both boxes, no orphan text, existing boxes did not move |
| Edit and remove | Longer node and arrow labels: box grows, label stays centred, arrows re-cut. Removing a node removes its box, label and arrows |
| Focus | Highlight (cyan, others dimmed) and camera in on the node and its neighbours, applied before the tool returned; clearing restores all |
| KaTeX beside a diagram | `steps` card with a focused row and a highlighted diagram together |
| Chemistry flow | Generic labels `CH₄`, `O₂`, `CO₂`, `H₂O` and arrow labels drawn, flow layout |
| Ordering | Five overlapping tool calls: sent in revision order, all drawn, scene equals the model |
| Text alternative | `role="img"` summary plus a listing of every connection |
| Network | Only the app origin; fonts from `/excalidraw/fonts/Nunito/`; no failed requests or page errors |
| Lazy-load failure | Chunk blocked: tool says "did not confirm" at once, card shows the message, retry button and open text version, the other card and the session work; after unblocking, "Försök igen" and the next call draw the whole diagram |
| Font failure | Font files blocked: not confirmed, visible message, text version |
| Lost update | LiveKit server frozen for about 12 s, past the RPC timeout (the browser did not show its own reconnecting banner in that time, so this is a stalled link, not a full reconnect): the tool did not claim success; once the server was back the next change drew the whole diagram |
| 1366×768 and 390×844 | Screenshots in the PR. See limits for 390 |

Unit tests cover the model and layout (`server/tests/test_diagram.py`), the tool, RPC and ordering behaviour including failures (`server/tests/test_tools.py`), payload validation, scene geometry, the acknowledgement rules, font loading and the card's lazy-load, error and retry paths (`web/src/*.test.ts*`).

What the first spike run found, and what was done about it:
- The library registers a font only once a scene uses it, so the first diagram's font wait failed (the acknowledgement correctly reported the failure). The worker now registers the two Latin Nunito files itself and waits for them.
- The library's phone-sized toolbar appeared at the bottom of the canvas; all library chrome is hidden.
- Focusing one node at the library's maximum zoom lost the context; the camera now fits the node and its neighbours.
- A failed card left an empty dark box; it now shows the message and the text version instead.
- Wheel and touch events on a view-only canvas would stop the board from scrolling; the canvas ignores pointers until the child presses "Zooma och flytta".

## Limits

- **390 px is not usable yet.** The existing layout gives the board column only about 140 px at that width (one breakpoint at 1024 px keeps the avatar column at 180 px beside it); the diagram stage measured 84 px wide and the map was drawn at 10% zoom. Equations on the same screen clip too. The text version is readable. This PR does not touch the layout. Pinch and pan with real fingers were not tested, and nothing here ran on a phone, a Chromebook, a Windows PC, or with a child.
- A font file that fails stays failed until the page is reloaded; the card says so and shows the text version.
- Nunito lacks subscripts and superscripts; `₂` and `²` render in a fallback font. Greek, Cyrillic and CJK glyphs are not served.
- The scene is rebuilt in full on each change and was not timed on slow hardware.
- Unreleased Excalidraw APIs and `exportToSvg` were not used. Upgrading the library needs the fonts and notice re-copied and the probe re-run.
- `npm audit` reports advisories in transitive packages of Excalidraw (`nanoid`, and `lodash-es` and a nested `katex` through Mermaid). Mermaid is not imported, but Vite emits its chunks into `dist` (about 8 MB more files on disk, never fetched).
- Worksheet annotation over a photo (the assessment's weakest case), molecule drawing and child editing are out of scope.
