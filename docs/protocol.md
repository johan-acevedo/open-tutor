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
| Text stream | `session-event` | JSON `{ "type": "end" }` when Avsluta is pressed, `{ "type": "resource-closed", "id" }`, `{ "type": "quiet", "on": true }` (reserved). |

The browser shows homework on the board itself as soon as the child adds it (kind `homework`), then sends it. The tutor never re-sends homework images.

## Tutor → browser

| Channel | Topic / method | Payload |
|---|---|---|
| RPC to browser | `board.show` | `BoardItem` JSON. The browser renders it, scrolls to it, and responds `{ "ok": true }` once it is in the DOM (images: after load). The tutor speaks about the item only after this reply. Timeout 5 s. |
| RPC to browser | `board.focus` | `{ "id", "step"?: number }` highlights one step of a `steps` item, or the whole item. Responds `{ "ok": true }`. |
| RPC to browser | `board.update` | `BoardItem` with an existing `id` replaces it in place, for example a `pending` placeholder that becomes an image. For a `diagram` it carries the whole new revision and is answered only once that revision is drawn (see [Diagrams](#diagrams)). |
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
  | { id: string; kind: "html"; title?: string; html: string; height?: number } // sandboxed iframe, scripts allowed, no same-origin
  | { id: string; kind: "image"; title?: string; url: string; alt: string }
  | { id: string; kind: "pending"; title: string }                           // "Ritar…" placeholder
  | { id: string; kind: "diagram"; title?: string; rev: number; layout: "radial" | "flow";
      nodes: DiagramNode[]; links: DiagramLink[]; focus: string[] }          // connected mind map or flow, see Diagrams
  | { id: string; kind: "resource"; title: string; url: string; embedUrl?: string; source?: string; prompt?: string }
  | { id: string; kind: "homework"; title: string; images?: string[]; text?: string }; // browser-created only

type Step = { tex: string; note?: string; op?: string };  // op/note: how this row came from the previous one (LaTeX op, e.g. "-5", "\\div 3")
type DiagramNode = { id: string; text: string; role: "center" | "idea" | "step" | "result" | "note"; x: number; y: number }; // x, y: node centre
type DiagramLink = { id: string; source: string; target: string; label?: string };
type Note = { at: string; topic: string; clicked?: string; tricky?: string; next?: string };
```

Generated HTML runs in `<iframe sandbox="allow-scripts">` with a strict CSP and no access to the page, learner storage or credentials. Links in resources open in a new tab.

## Diagrams

A `diagram` is a connected mind map or flow drawn on a canvas (Excalidraw 0.18.1, view-only, loaded when the first diagram arrives). Equations stay in `steps` and `text` cards, which use KaTeX in the page.

**Who owns what.** The tutor worker owns each diagram: node and link ids, labels, roles, layout and the highlighted ids (`server/open_tutor/diagram.py`). The model never writes coordinates or scene JSON. It calls `show_diagram`, `add_to_diagram`, `edit_diagram`, `remove_from_diagram` and `focus_diagram` with short ids; the worker validates the change as a whole (an invalid change leaves the diagram as it was), gives it the next `rev`, and sends the **whole** item. The browser keeps no history: it draws what it is given. Node centres come from the worker, stay fixed when nodes are added to a `radial` map, and are recomputed for a `flow`. Limits: 24 nodes, 40 links, 60 characters per label, coordinates within ±4000, and a flow of at most 6 steps across and 5 rows. The largest item is under LiveKit's 15 KiB RPC limit (tested).

**Acknowledgement.** `board.show` (first revision) and `board.update` (later ones) are answered `{ "ok": true }` only when the scene shows that revision or a later one, after the fonts have loaded, the elements are in the scene and every box, label and arrow has been checked. They answer with an RPC error (code 1500, Swedish message) if the drawing library or its font could not load, the scene did not match, or no answer came within 10.5 s. The worker waits 12 s for a diagram (6 s for other items, because the first diagram fetches the library) and reports "did not confirm" to the model otherwise; it never says an unconfirmed diagram is visible. A revision older than the one on the board is ignored.

**Order and recovery.** The worker runs diagram changes one at a time. The browser draws the newest revision it has and answers older waiters with it. Because every message is a full snapshot, a lost or timed-out update is repaired by the next one; after a failed send the worker uses `board.show` again, not a bare update. `focus_diagram` is a new revision with `focus` set (highlight and camera), so it is ordered with, and acknowledged like, the edits before it. `board.focus` stays for `steps` rows.

**Failure.** If the library chunk or the font file fails to load, the card says so in Swedish, offers "Försök igen" (library) and shows the text version open. The rest of the board and the session keep working.

**Accessibility.** The canvas has `role="img"` with a one-line Swedish summary, and a "Visa som text" section lists every connection and the current highlight. The canvas itself is not exposed to screen readers.
