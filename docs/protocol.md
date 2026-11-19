# Browser ↔ tutor protocol

The browser and the tutor worker share one LiveKit room per session. Audio goes both ways as normal tracks. Everything else uses LiveKit text streams, byte streams and RPC, as listed here. `web/src/protocol.ts` holds the TypeScript types; `server/open_tutor/board.py` the Python side. Change both together.

## Session start

1. The browser calls `POST /api/session` with `{ "learner": { "name": "Leo", "grade": 8, "notes": [Note, …], "band": "middle" } }`. It sends at most the five newest notes. `grade` is `null` when the tutor has not learned it yet; `band` (`primary` | `middle` | `upper`) is the age band for the page load, picked by the request host. On a voice-first start `name` is `""`: the call begins with no name and the tutor learns it by voice early in the call (`learner.setName`).
2. The web service creates a room `tutor-<random>`, dispatches the `open-tutor` agent into it, and returns `{ "url", "token", "room" }`. The learner JSON becomes the participant's metadata, so it travels with the token.
3. The browser connects, publishes the microphone, and waits. The tutor speaks first.

## Browser → tutor

| Channel | Topic / method | Payload |
|---|---|---|
| Text stream | `lk.chat` | What the child typed. The agent treats it like speech. |
| Byte stream | `homework` | One image (PNG/JPEG/WebP) per stream. Attributes: `kind` = `photo` \| `screenshot` \| `pdf-page`, `source` = original file name, `page` = page number (PDF only), `pages` = total pages, `itemId` = the board id the browser already gave it. |
| Text stream | `homework-text` | Pasted text. Attributes: `itemId`. |
| Text stream | `session-event` | JSON `{ "type": "end" }` when Avsluta is pressed (or the menu leave flow starts), `{ "type": "resource-closed", "id" }`, `{ "type": "board-size", "w", "h", "device" }` (visible `.ot-board-scroll` content-box size, ResizeObserver; debounced, on change), `{ "type": "quiet", "on": true }` (reserved). |

The browser shows homework on the board itself as soon as the child adds it (kind `homework`), then sends it. The tutor never re-sends homework images.

## Tutor → browser

| Channel | Topic / method | Payload |
|---|---|---|
| RPC to browser | `board.show` | `BoardItem` JSON. The browser renders it, turns to it, and responds `{ "ok": true, "board": { "w", "h", "device" } }` after mounting and the layout transition finishes (images: after load). Dimensions describe the visible drawing area. The tutor speaks about the item only after this reply. |
| RPC to browser | `board.focus` | `{ "id" }` turns to an existing item. Responds `{ "ok": true }`. |
| RPC to browser | `board.update` | `BoardItem` with an existing `id` replaces it in place. It returns the same acknowledgement and dimensions as `board.show`. |
| RPC to browser | `board.patch` | `{ "id", "patch" }` applies `<ot-patch>` HTML to that page's shell. Responds `{ "ok": true }`; rejects when no page frame with that id is mounted. |
| RPC to browser | `board.reveal` | `{ "id", "part" }` uncovers a hidden answer or `later` part on that page. Responds `{ "ok": true }`. |
| RPC to browser | `board.point` | `{ "id", "part" }` highlights one part of that page. Responds `{ "ok": true }`. |
| RPC to browser | `board.loading` | `{ "id", "topic" }` dims that page and shows "Laddar <topic>…" at once while the next page is prepared; an empty topic clears it. A successful patch clears it too. Responds `{ "ok": true }`. |
| Text stream | `note` | JSON `Note`. The browser saves it to the current profile in IndexedDB. |
| RPC to browser | `learner.setGrade` | `{ "profileId", "grade" }`, from the tutor's `set_learner_grade` tool. Acknowledged request/response: the browser applies the grade only when `profileId` is still the active profile (all writes run through one serialized queue; stale targets are rejected with an error), replies `{ "ok": true, "grade" }`, and the tool updates the call only on acknowledgement. A failed call leaves the lesson exactly as it was. |
| RPC to browser | `learner.setName` | `{ "profileId", "name" }`, from the tutor's `set_learner_name` tool. Acknowledged request/response: the browser creates the local profile for the name (or attaches to an existing local profile with the same name, serialized like the switch below), remembers it as the assumed student, and replies `{ "ok": true, "profile": { "id", "name", "grade" } }` — the tool updates the call (id, name, and grade when the attached profile already knows it) only on acknowledgement. A repeat call with a corrected name is the same path again. A failed call saves nothing: the tool carries on with the lesson and mentions nothing. |
| RPC to browser | `learner.switch` | `{ "name" }`, from the tutor's `switch_student` tool. The browser resolves or creates that student's profile (serialized; one profile per name), arms a post-lesson prefill, and replies `{ "ok": true, "profile": { "id", "name", "grade" } }`. The tool then ends this lesson exactly like Avsluta (the note is saved, the tutor says goodbye); afterwards the browser shows the start page prefilled for the new student — no automatic reconnect, no continuation session, and the hourly session cap simply counts B's session as a new one. A failed call (or rejection) never arms anything: the tool says so briefly and carries on. |
| Text stream | `lk.transcription` | Built-in agent captions, streamed in step with the audio. The browser shows the sentence being spoken. |
| Participant attribute | `lk.agent.state` | Built-in: `initializing`, `listening`, `thinking`, `speaking`. |
| Participant attribute | `tutor.mode` | `talking` \| `quiet` \| `resource` \| `ending`. Quiet means the child is working; the avatar waits. |

## Board items

```ts
type BoardItem =
  | { id: string; kind: "page"; title: string; body: string }              // one Smart Screen page; the body only
  | { id: string; kind: "image"; title?: string; url: string; alt: string }
  | { id: string; kind: "pending"; title: string; height?: number }        // "Ritar…" placeholder; kept, nothing produces one now
  | { id: string; kind: "resource"; title: string; url: string; embedUrl?: string; source?: string; prompt?: string }
  | { id: string; kind: "homework"; title: string; images?: string[]; text?: string }; // browser-created only

type Note = { at: string; topic: string; clicked?: string; tricky?: string; next?: string };
```

The board has one screen mode (2026-11-18). The `text`, `steps`, `mindmap`, `svg`, `html` and
`material` kinds are gone: the Smart Screen renders pages in its own shell, so nothing
produced them any more and both sides reject them now.

A page body travels alone; the web app holds the shell (`screen/shell/`, bundled as text) and
composes the frame itself, because LiveKit RPC payloads are limited to about 15 kB. The frame
is `<iframe sandbox="allow-scripts">` with the shell's CSP and no access to the page, learner
storage or credentials. A page with an answer box or a hidden answer keeps what the child
typed across pages, because an earlier page's frame stays mounted when the book turns.
Links in resources open in a new tab.

## Pages and changes

The tutor never draws. It asks the Screen for a page or a change; the Screen writes it in the
background and the worker delivers the result through the RPCs above. A finished page appears
on the screen by itself (`ask_screen(show="hold")` keeps it hidden until `show_page`), and a
change to the visible page is applied with `board.patch`. `board.loading` dims the old page
while the next one is prepared. Nothing is shown while it is being written, and a page that
fails to render is never sent.
