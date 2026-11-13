# Smart Screen: state and decisions

Lead: the thread "state of the project" (Claude, 2026-11-12). The lead keeps this file current.
Workers read it before starting and report against it. Decisions here were agreed with Johan
on 2026-11-12 unless marked open.

## Where things run

- Branch: `feat/smart-screen`, from `origin/main@97428a7`. Nothing is deployed from it.
- Production: ThinkCentre, `main`. Do not touch it.
- Reference only: `feat/browser-screen-agent` (draft PR #25). Do not build on it. Worth lifting
  as ideas: one page at a time, hidden answer with tutor-controlled reveal, the child's answer box.

## Why this exists

The board next to Räven (the fox tutor) must help the tutor's words land. Two things went wrong:

1. **Waiting.** Until 10 Nov the tutor wrote boards itself: 115 boards, each visible in about
   0.1 s, and the long sessions (25–40 min) happened then. On 11 Nov a separate board model
   started writing a full HTML document per request: 25 requests, median wait 89 s, 7 hit the
   150 s timeout. The child waits in silence because the tutor's tool call blocks.
2. **Blind drawing.** The board model receives two short fields written by the tutor. It does
   not see the conversation, the homework or the board already on screen.

Johan's idea (11 Nov): make the screen its own thinking agent. The fox is a fast model that
leads the conversation; the screen can be a heavier model with time to think. The screen gets
all the lesson data (uploads, transcript, the tutor's answers), keeps its own log, and renders.
The fox looks at what was actually rendered and teaches from it.

## Agreed design

**The tutor is never blocked.** Asking the screen for something returns at once. The tutor keeps
the conversation alive while the screen works, and picks the page up when it suits the lesson.
This is the rule to protect above the others.

**The screen follows the lesson.** It hears the whole conversation and sees the homework as it
happens, so that when asked it only has to write. It runs on the server next to the fox for the
prototype. Moving it into the learner's browser is a later step, once the idea is proven.

**A page is an HTML body inside our own shell.** The screen model writes only the page body.
The shell supplies theme, fitting to the pane, maths, hidden answers, the answer box and
pointing. Components are custom HTML tags, so a common teaching aid costs one line. HTML stays
because of its flexibility; components exist because an unsupported small model is slow and its
quality is low.

**Prefer tools the model already knows.** Every tag we invent must be taught through examples.
Use proven libraries rather than re-inventing them.

**One page at a time.** Pages like a book, with back and forward. No scrolling feed. Earlier
pages keep what the child typed.

**The screen is calm.**
- A page appears finished. It is not shown while it is being written.
- A visible page changes only when the tutor's teaching moves on. The screen never swaps in a
  better version of its own work.
- Anything prepared ahead stays invisible until the tutor brings it in.
- Edits are small patches to the part that changed, with a soft fade and a brief highlight. No
  flicker, no full redraw.

**Draft, look, fix, then show.** The screen sees its own render before the child does and
repairs mistakes. Since the tutor never waits, there is time for this.

**Answers.** A page may hide an answer; the tutor decides when to reveal it. A page may hold an
answer box; what the child submits reaches the tutor.

**Examples teach the screen model.** A strong model makes example screens and iterates until
they are excellent. They are the main quality lever for the small live model. An always-on set
comes first in the prompt (it stays cached); a few more are chosen per session by subject and
school year.

**Every page shown is saved** with its source and screenshot, for us to review. The AI does not
reuse saved pages, for now.

## Decided against, for now

- The agent living in the browser (later; it was bundled into PR #25 and cost most of its size).
- Showing a page while it is being written (the tutor keeps the conversation; it could distract).
- Two speeds, where a quick page is later replaced by a richer one (flicker).
- A fixed list of card types as the only format (loses HTML's flexibility).
- Stroke-by-stroke whiteboard drawing (models place things poorly by coordinates).

## Measurements (2026-11-12, one run each, quality not judged)

Same fractions request, OpenCode Go subscription:

| Model and setting | Output | Finished page |
|---|---|---|
| Muse Spark 1.3 Contributor, minimal reasoning | page body only | 8 s (first text 2 s) |
| Muse Spark 1.3 Contributor, minimal reasoning | full HTML document | 14 s |
| DeepSeek V4.1 Flash, low reasoning | page body only | 15 s |
| DeepSeek V4.1 Flash, default reasoning | page body only | 68 s |
| DeepSeek V4.1 Flash, default reasoning | full HTML document | over 150 s |

Prompt caching works for both models (a 20,000-token static prefix came back as cached on the
second call) but did not shorten time to first text. So a large static context of component
notes and examples is affordable; the wait is in reasoning and output length.

Calling the models: base URL `https://opencode.ai/inference/go/openai/v1`, key
`OPENCODE_GO_API_KEY`, headers `User-Agent: open-tutor/…` and `x-opencode-session: <id>`. Muse
is served on the Responses API (`reasoning: {effort: "minimal"}`); DeepSeek on Chat Completions
(`reasoning_effort: "low"`). On this machine the key comes from
`OPEN_TUTOR_ENV=~/.config/open-tutor-screen-dev/env server/bin/with-env <command>`. Never print it.

## Capabilities the example screens must cover

The subject of an example is only a carrier; we will never cover the curriculum. Together the
examples must show every tool used well. Candidates are starting points, to be confirmed or
replaced while making the examples.

| Capability | What it shows | Candidate |
|---|---|---|
| Text and layout | headings, columns, cards, emphasis | shell styles |
| Maths notation | equations, fractions, worked steps, written methods (uppställning) | KaTeX plus a steps component |
| Coordinate system | function graphs, points, lines, geometry | JSXGraph |
| Teaching aids | number line, fraction bars, clock, balance | small custom tags (vector graphics) |
| Charts | bar, line, pie | Chart.js |
| Maps | places, borders, how far an empire reached | Leaflet with border data |
| Images | a found photo or illustration with its source | Wikimedia search; generation undecided |
| Timeline | events in order | custom tag |
| Diagrams | mind map, cycle, labelled parts | open |
| Language practice | phrases, word pairs, fill in the gap | custom tags |
| Interaction | answer box, hidden answer, multiple choice | shell |
| Pointing | the tutor highlights one part | shell |

Later: 3D shapes, chemistry structures, video.

What the children actually worked on (from session notes, åk 1 to gymnasiet): the clock,
written division with decimals, weight units and price per kilo, decimals, the equation
3x + 5 = 20, linear equations, Pythagoras, the map of Europe and France's borders, the Roman
Empire, and a large share of English phrase and reading practice in åk 5.

## Example screens (work package 1, 2026-11-12)

Everything is in `screen/` on branch `feat/screen-examples`; start with `screen/NOTES.md` (choices, what was tried
and rejected, CSP) and `screen/REFERENCE.md` (what the screen model reads). Gallery with live pages and
screenshots: http://dell5500.tail2e1c4e.ts.net:8790/ (user service `open-tutor-screen-gallery` on dell5500).

- **Shell** (`screen/shell/`, about 54 kB gzipped, inlined into the frame's `srcdoc`; 16 kB of that is the 21 län
  polygons from `shell/data/`, see `screen/shell/data/README.md`): dark theme, Lexend, KaTeX,
  fitting by root font size so the page fills the pane without scrolling at any size, hidden until finished,
  `ot-hidden` and `later` for answers the tutor reveals, `ot-answer` / `ot-choice` / `ot-gap` that post the child's
  answer to the parent, pointing (`{ot:'point', id}`), and patches written as `<ot-patch target do>` HTML that fade in
  with a soft highlight. On `ready` the shell reports lint issues (KaTeX errors, unknown tags, overflow, crowded
  diagrams …) for the Screen agent's look-and-fix step.
- **Components**: `ot-steps`, `ot-written` (computed uppställning incl. liggande stolen), `ot-clock`, `ot-fraction`,
  `ot-numberline`, `ot-balance`, `ot-graph` (JSXGraph), `ot-chart` (Chart.js from a `<table>`), `ot-map` (d3-geo with
  Natural Earth and historical borders, plus Sweden's 21 län with letter codes and a key; replaces Leaflet),
  `ot-image` (Wikimedia Commons), `ot-timeline`, `ot-cycle`,
  `ot-mindmap`. The model writes no JavaScript.
- **Examples**: nine pages with one patch each (klockan, bråk, pris per kilo, ekvation, räta linjen, Romarriket,
  engelska på kafé, vattnets kretslopp, Sveriges län) covering every row of the capability table; the static prompt
  (role + reference + examples) is about 4 600 tokens (`screen/tools/prompt.py`).
- **Small-model test** (five requests the examples do not cover, `screen/smalltest/`): both models wrote valid pages
  and minimal, correct patches on every request. With the final reference, page totals were 5–10 s for Muse Spark 1.3
  Contributor (minimal reasoning) and 5–8 s for DeepSeek V4.1 Flash (low); patches 1–7 s. A rule in the reference
  ("about 60 words, one main picture") was needed: before it, DeepSeek's pages fitted only at 11–15 px on a phone.
- **CSP change for page frames**: add `connect-src https://cdn.jsdelivr.net https://commons.wikimedia.org` (map data,
  image search). Nothing else changes; the frame stays `sandbox="allow-scripts"`.
- **Open from this package**: image search should move to the Screen agent on the server (no content filter on
  Commons results); the liggande stolen layout needs a teacher's check; not yet tried on a real iPhone or in WebKit.

## Live slice: the contract (2026-11-12)

Johan's call: no replay simulations; the interaction between tutor, child and screen is the
critical part, so build it live on the dev setup (dell5500) and iterate there. What we have in
production is weak, so speed matters more than hardening. Everything is behind
`TUTOR_SCREEN=smart` on the worker; without it the worker behaves as on `main`.

### Server: `server/open_tutor/screen.py`

One `Screen` per session, owned by the worker next to the `Tutor`.

- **It follows the lesson.** It records every conversation turn (child and tutor), shared
  homework (images and text), the child's answers from pages, and what is on screen.
- **`ask(text) -> job id` returns at once.** A background task then:
  1. builds the request: static prefix from `screen/tools/prompt.py` (role, reference,
     examples; identical every call so it stays cached), then the learner, the pane size
     (`Pane: 370×610 px, narrow. Write one reading column, a short title …` below 600 px wide),
     the homework, the conversation so far, the source of the visible page with its patches,
     and the tutor's ask;
  2. calls the screen model (default Muse Spark 1.3 Contributor on the Responses API, minimal
     reasoning; `SCREEN_MODEL` and `SCREEN_REASONING` override; DeepSeek uses Chat Completions);
  3. reads the answer as either `<ot-patch>` elements (a change to the visible page) or a new
     page body;
  4. renders it with `screen/tools/screenkit.py` at the child's pane size and collects the
     shell's issues and a screenshot;
  5. for a new page, **looks once** (`SCREEN_LOOK=1`, default on): the model gets its own
     screenshot, the page source, the pane and the issues, and answers `OK` or a corrected
     body, which is rendered again (see below);
  6. saves source, screenshot, the ask and timings under the session's log folder (`pages/`);
  7. hands the result to the tutor.
- One job at a time; a second ask while one runs is queued (latest wins). 45 s limit per job.
  A failure is told to the tutor quietly ("explain in words").

### The look pass and one bounded lint retry (page jobs)

- **The look pass sees what it repairs:** the screenshot, the page body it wrote, the ask, the
  pane and the shell's exact issue lines. It checks readability at that pane size, whether the
  page does what the tutor asked, and whether it gives the answer away. For the last one it
  names the question the page actually asks and checks every visible number, mark, label and
  picture step against it: a solved step, the result marked, or 6/8 printed under "Hur många
  åttondelar är 3/4?" is a leak even when lint reports nothing. Lint only sees layout, tags,
  maths and ids; it cannot see teaching leakage in words or pictures, and neither the prompt nor
  the log claims it can.
- **One retry, only for actionable lint.** If issues a body can fix remain after the look
  (and the final render), the model gets exactly one more call with the ask, the pane, the
  source of the page it is correcting and the exact lint text (e.g. `dense: text is only
  14.75px on this screen (minimum 16px)…`, `heading: title takes more than two lines…`).
  `SCREEN_LINT_RETRY=0` turns it off. Advisory issues never buy a retry: `slow` loading,
  `load` failures and `image` credits stay in the log.
- **Delivery wins over repair.** Optional steps start only while a final render still fits the
  job's 45 s limit, and the look and retry calls are bounded by the time that is left. A
  correction that fails, times out or comes back with more actionable lint than before is
  dropped and the page in hand is delivered. Whatever actionable lint remains is written to the
  job's `meta.json` (`residual_lint`, `repair`) and logged as `delivered with residual lint`;
  a usable page is never dropped to avoid showing one. No model fallback, and patches are not
  retried.

### Tutor tools (replace `commission_board` and `edit_board` in smart mode)

| Tool | Does | Speed |
|---|---|---|
| `ask_screen(ask)` | asks for a new page or a change to the visible one; returns at once | page 5–15 s, change 1–7 s |
| `show_page(page_id)` | puts a finished page in front of the child | instant |
| `reveal(part_id)` | uncovers a hidden answer or a `later` part on the visible page | instant |
| `point(part_id)` | highlights one part of the visible page | instant |

- **A new page stays invisible until the tutor calls `show_page`.** When it is ready the tutor's
  chat context gets the screenshot, the page source (so it knows the ids) and a line saying the
  page is ready but not visible. If the tutor is silent and the child is not speaking, the
  worker prompts it once; if it is speaking, the prompt waits until it has finished.
- **A change (patch) is applied as soon as it is ready**, since the tutor asked for it. The tutor
  gets the patch source and a fresh screenshot in its context, without a prompt.
- **A child's answer** from `ot-answer`, `ot-choice` or `ot-gap` reaches the tutor as a session
  event with page id, part id and value, and prompts a reply. The Screen records it too.

### Web app

- A new board item kind **`page`**: `{kind: "page", id, title, body}`. The web app holds the
  shell (`screen/shell/` bundled as text) and composes the frame itself; only the body travels,
  because LiveKit RPC payloads are limited to about 15 kB.
- **One item at a time on every device**, with back and forward. No scrolling feed. Homework,
  resources and pages are all leaves of the same book. Frames of earlier pages stay mounted so
  what the child typed survives.
- RPC from worker to browser, all acknowledged with `{ok}`:
  - `board.show` with a `page` item: add it and turn to it.
  - `board.focus` `{id}`: turn to an existing item (already exists).
  - `board.patch` `{id, patch}`: pass `patch` (the `<ot-patch>` HTML) to that page's shell.
  - `board.reveal` `{id, part}` and `board.point` `{id, part}`: pass to the shell.
- From browser to worker on the `session-event` text stream:
  `{type: "page-answer", page, part, value, kind}` when the shell reports a submitted answer.
- Frame policy: `sandbox="allow-scripts"` and the content security policy from
  `screenkit.py` (`CSP`). Messages from a frame are accepted only when
  `event.source === iframe.contentWindow`.

### Status of the live slice (2026-11-12, evening)

Built and merged into `feat/smart-screen` (PRs #30 server, #31 web, #32 shell fixes from a
DeepSeek review). Runs on dell5500 at https://dell5500.tail2e1c4e.ts.net:9444/ as the user
services `open-tutor-smart-dev-agent` and `open-tutor-smart-dev-web`, environment file
`~/.config/open-tutor-smart-dev/env`, session logs and saved pages under
`~/.local/state/open-tutor-smart-dev/sessions/`. After server changes restart the agent service;
after web or shell changes run `npm run build` in `web/`.

`server/scripts/smart_screen_e2e.py` plays a fictional typed lesson through the real app in
headless Chromium. It passed three times: ask, page ready, shown, reveal, patch, answer box,
answer to tutor, point. Measured: new page 9–12 s (model 4–5 s, render 1 s, look 4–6 s), patch
3–8 s. Not yet tried with a voice or a child.

Known and open:
- The look pass is about half of a page's time; decide after real sessions whether it earns it.
- A page can still give the answer away in a picture (seen: the sum marked on a number line);
  the look pass now checks exactly that, but it is a model judgement, not lint.
- The tutor says "jag fixar en sida" before carrying on; acceptable or not is Johan's call.
- Page and patch HTML enters through an inert template and a shared sanitizer. Native
  `setHTML` is used when available, with DOMPurify for other browsers. Model scripts,
  event handlers and styles are removed before insertion; the shell's own code still runs.
- Image search still runs in the page (unfiltered Commons result).

### Tutor model routes (2026-11-13)

`gemini` joins `go`/`go-deepseek`: Gemini 4 Hydrogen with thinking level `low` on
Google's OpenAI-compatible Chat Completions. A live session first exposed two
provider-specific failures; both are fixed in our code.

- Gemini 4 sends every function call with `index: null`. LiveKit tells parallel calls
  apart by that index, so the second call overwrote the first and only the last
  (unsigned) call survived; the next request failed with `400 Function call is missing
  a thought_signature`. `tutor_llm.GeminiChatLLM` numbers the calls, keeping all of them
  and the signature on the first.
- The greeting turn called `save_note` when the child's typed message raced it. The
  memory instructions and the tool description now say not to save a note at the
  greeting; five pure and five racing greeting runs called no `save_note`.

Provider-independent: a non-retryable LLM error is recorded as `provider_error` with the
provider's own message, and the worker says one short apology through TTS (no LLM) and
ends the session instead of leaving the child in silence.

### A typed message must never vanish (2026-11-13)

A message the child typed while the tutor was still working on its greeting was
sometimes lost: no answer and no `chat_item` in the log. Reproduced deterministically
and traced to two silent holes in how the message travelled:

- **The room had nobody to deliver to.** LiveKit drops a data message published while
the agent participant is not yet in the room; the browser's `sendText` still resolves
(`remoteParticipants` empty, send confirmed, nothing in the worker).
- **The room had no handler.** A stream that arrives before the topic's handler is
registered is disposed by the RTC layer, with only an INFO line on the `livekit`
logger (silenced to WARN in our worker). RoomIO registers `lk.chat` inside
`AgentSession.start()`, which is after the participant wait, TTS/STT construction and
the debug log — a window of a few hundred ms in a fast start, seconds under load.

The worker now owns `lk.chat` from the moment the room connects (`text_input.py`,
`text_input=False` in `RoomOptions`): every message is recorded as `chat_typed` on
arrival, messages that arrive before the session can answer are queued and answered
afterwards (one reply that greets too, since the greeting has not been heard), and a
message that cannot be handled is recorded as `chat_typed_failed` instead of
disappearing. Handling still interrupts the current speech and generates a reply; it
tolerates uninterruptible speech and a stalled stream read (15 s). The page holds
everything it sends to the tutor until the agent participant is in the room
(`web/src/agentGate.ts`), which closes the first hole for our app.

`server/tests/test_typed_chat.py` pins the queueing, the greeting merge, the
interrupt, the failure records and the 15 s read timeout;
`server/scripts/typed_chat_probe.py` sends typed messages at chosen moments against a
deliberately slow stub provider and reports what the worker's log recorded.

## Work packages

Toolbox follow-up, 2026-11-13: narrow-page layout and readability lint are in
review on `fix/screen-toolbox-layout`. This uses real DeepSeek V4.1 Flash low
output at 370×610, 370×558 and 1000×700. Evidence and remaining density/answer-leak
problems are in `screen/review/2026-11-13-readability/`. Map layout, safe page
composition, and the server's bounded lint correction are separate changes.
The lead deploys after review and merge. No dev services were restarted.

Map key layout, 2026-11-13 (separate change on `fix/map-side-key`): `regions="län"`
now measures its key and keeps whichever layout draws Sweden bigger — a column (or
two) beside the map on a wide pane, a strip under it on a phone — and the strip sits
below the fitted map instead of over it. Same real page, 1000×700 pane: the country
grows from 97×220 to 128×292 px and the 21 codes from 9.4 to 12.3 px, with no
`crowded` issue. The region map is also slid so Sweden is centred in the room it has.
Phones keep today's key under the map and still need less page content. Evidence,
screenshots and `screen/tools/check_map_key.py` are in
`screen/review/2026-11-13-map-key/`. `screen/REFERENCE.md` no longer says the key is
under the map, since the shell decides where it goes.

1. **Example screens, shell and components.** Owner: a separate Opus 5.5 thread. Status: started
   2026-11-12. Draft delivered 2026-11-12 in PR #29 (`feat/screen-examples`); waits for review by the lead and
   Johan before anything else builds on it.
   Merged into `feat/smart-screen` 2026-11-12.
2. **The Screen agent on the server.** Owner: lead, with a Muse worker. Status: started
   2026-11-12 against the contract above.
3. **One-page view, reveal and answer box in the web app.** Owner: lead, with a Muse worker.
   Status: started 2026-11-12 against the contract above.
4. **First session with a child.** The test that counts.

## Open

- Which model and reasoning level the screen runs on (measure with the examples in place).
- Image generation: whether, and with what.
- How the tutor is told a page is ready without interrupting its own sentence.
