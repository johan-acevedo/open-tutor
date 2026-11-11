# Browser ↔ tutor protocol

The browser and the tutor worker share one LiveKit room per session. Audio goes both ways as normal tracks. Everything else uses LiveKit text streams, byte streams and RPC, as listed here. `web/src/protocol.ts` holds the TypeScript types; `server/open_tutor/board.py` the Python side. Change both together.

## Session start

1. The browser calls `POST /api/session` with `{ "learner": { "name": "Leo", "grade": 8, "notes": [Note, …] } }`. It sends at most the five newest notes.
2. The web service creates a room `tutor-<random>`, dispatches the `open-tutor` agent into it, and returns `{ "url", "token", "room" }`. The learner JSON becomes the participant's metadata, so it travels with the token.
3. The browser connects, publishes the microphone, and waits. The tutor speaks first.

## Browser → tutor

| Channel | Topic / method | Payload |
|---|---|---|
| Text stream | `lk.chat` | What the child typed. The agent treats it like speech. |
| Byte stream | `homework` | One image (PNG/JPEG/WebP) per stream. Attributes: `kind` = `photo` \| `screenshot` \| `pdf-page`, `source` = original file name, `page` = page number (PDF only), `pages` = total pages, `itemId` = the board id the browser already gave it. |
| Text stream | `homework-text` | Pasted text. Attributes: `itemId`. |
| Text stream | `session-event` | JSON `{ "type": "end" }` when Avsluta is pressed, `{ "type": "resource-closed", "id" }`, `{ "type": "board-size", "w", "h", "device" }` (visible `.ot-board-scroll` content-box size, ResizeObserver; debounced, on change), `{ "type": "quiet", "on": true }` (reserved). |

The browser shows homework on the board itself as soon as the child adds it (kind `homework`), then sends it. The tutor never re-sends homework images.

## Tutor → browser

| Channel | Topic / method | Payload |
|---|---|---|
| RPC to browser | `board.show` | `BoardItem` JSON. The browser renders it, scrolls to it, and responds `{ "ok": true, "board": { "w", "h", "device" } }` after mounting and the layout transition finishes (images: after load). Dimensions describe the visible drawing area. The tutor speaks about the item only after this reply. |
| RPC to browser | `board.focus` | `{ "id", "step"?: number }` highlights one step of a `steps` item, or the whole item. Responds `{ "ok": true }`. |
| RPC to browser | `board.update` | `BoardItem` with an existing `id` replaces it in place. New drawings replace their placeholder; edits replace the existing board. It returns the same acknowledgement and dimensions as `board.show`. |
| RPC to browser | `board.remove` | `{ "id" }` removes that board item, for example a `pending` placeholder whose drawing failed. Responds `{ "ok": true }`. |
| Text stream | `note` | JSON `Note`. The browser saves it to the current profile in IndexedDB. |
| Text stream | `lk.transcription` | Built-in agent captions, streamed in step with the audio. The browser shows the sentence being spoken. |
| Participant attribute | `lk.agent.state` | Built-in: `initializing`, `listening`, `thinking`, `speaking`. |
| Participant attribute | `tutor.mode` | `talking` \| `quiet` \| `resource` \| `ending`. Quiet means the child is working; the avatar waits. |

## Board items

```ts
type BoardItem =
  | { id: string; kind: "text"; title?: string; markdown: string }            // short Markdown, $…$ and $$…$$ KaTeX
  | { id: string; kind: "steps"; title?: string; steps: Step[] }             // worked equation or process
  | { id: string; kind: "mindmap"; title?: string; center: string; ideas: string[] }
  | { id: string; kind: "svg"; title?: string; svg: string }                 // sanitised, no scripts
  | { id: string; kind: "html"; title?: string; html: string; height?: number; width?: number } // sandboxed iframe, scripts allowed, no same-origin; width+height = commissioned design box, scaled to fit the current pane
  | { id: string; kind: "image"; title?: string; url: string; alt: string }
  | { id: string; kind: "pending"; title: string; height?: number }       // "Ritar…" placeholder
  | { id: string; kind: "resource"; title: string; url: string; embedUrl?: string; source?: string; prompt?: string }
  | { id: string; kind: "homework"; title: string; images?: string[]; text?: string }; // browser-created only

type Step = { tex: string; note?: string; op?: string };  // op/note: how this row came from the previous one (LaTeX op, e.g. "-5", "\\div 3")
type Note = { at: string; topic: string; clicked?: string; tricky?: string; next?: string };
```

Generated HTML runs in `<iframe sandbox="allow-scripts">` with a strict CSP and no access to the page, learner storage or credentials. Links in resources open in a new tab.

The frame preserves its commissioned `width` and `height`. It scales down proportionally when the visible `.ot-board-scroll` content box becomes smaller. Controls remain interactive after scaling. HTML items without `width` keep their fluid width.

## Slow drawings

`commission_board` publishes a `pending` placeholder through `board.show`, asks the board
model for the drawing, and replaces the placeholder through `board.update` with the same `id`.
The tutor says one short waiting sentence and teaches when the tool returns. Räven uses the
working pose while a board is pending. If generation or display fails, the worker removes
the placeholder through `board.remove` and the tutor explains in words.

`edit_board` sends a saved board's HTML back to the renderer with the requested change.
The placeholder and revised board use the original id. Failed edits restore the saved
board through `board.update`, rather than removing it. The tutor receives a new screenshot
after a successful edit. Saved HTML belongs to the session and is discarded when it ends.
