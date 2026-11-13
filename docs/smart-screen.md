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
  5. for a new page, makes at most one optional check or correction within the timing budget
     below, then keeps the usable page if optional work fails;
  6. saves source, screenshot, the ask and timings under the session's log folder (`pages/`);
  7. hands the result to the tutor.
- One job at a time; a second ask while one runs is queued (latest wins). 20 s limit per job.
  A failure is told to the tutor quietly ("explain in words").

### Page timing budget (2026-11-13)

- The default job limit is 20 s. Generation leaves two seconds for the first render. A
  generation timeout reports failure to the tutor so it can explain in words.
- Clean pages get a look only when it can fit the 12 s soft target, including a final-render
  reserve. The look sees the source, screenshot, ask and pane, with short readability and
  answer-leak criteria. Each optional call is capped at 6 s. `SCREEN_LOOK=0` disables it;
  `SCREEN_LOOK=always` allows inspection up to the hard limit for diagnostics.
- Actionable lint goes directly to one source-and-lint correction instead of a visual look
  first. `SCREEN_LINT_RETRY=0` disables that. There is no look-plus-retry chain. Advisory
  loading and credit issues stay in the log.
- Failed or late optional work keeps the already rendered page. Remaining lint and skipped
  work are saved in `meta.json` (`residual_lint`, `repair`) and logged. Patches get no retry.
- Quality tradeoff: a clean page can be delivered without semantic inspection. Lint cannot
  catch an answer given away in a diagram or explanation. The reference still tells the
  writer to hide answers, but a clean lint result is not a teaching-quality guarantee.

Five measured jobs before this policy took 18.9–29.3 s, all with a look answering `OK`.
Five after it took 13.6–17.9 s with no failures and no look calls. These are separate batches,
so provider variation prevents a clean speedup claim. The under-12 s target is not met on
this route: generation alone took 12.4–16.5 s in the second batch. Sources, timing data,
screenshots and rerun commands are in `screen/review/2026-11-13-page-budget/`.

### Page-writer model comparison controls (2026-11-13)

Prepared on `feat/screen-model-controls`, without live inference calls. Setting
`SCREEN_MODEL=gemini-4-hydrogen` selects Google's OpenAI-compatible endpoint and
`GEMINI_API_KEY`; `SCREEN_REASONING=low` (default) or `medium` selects thinking depth.
Other models keep the Go route. There is no fallback between providers.
`SCREEN_THINKING=disabled` on a DeepSeek chat model sends
`thinking: {type: disabled}` and omits `reasoning_effort`; empty keeps today's low
reasoning request. Invalid combinations fail explicitly. Page/patch `meta.json`
records the effective model, API, reasoning and any explicit thinking toggle.

The controls follow [Google's compatibility API](https://ai.google.dev/gemini-api/docs/openai)
and [DeepSeek's thinking toggle](https://api-docs.deepseek.com/guides/thinking_mode/).
HTTP request tests use the real SDK with a local recorded-response transport;
provider acceptance, speed and page quality remain untested. Go probes and new
Go helpers are paused pending Johan's billing decision. The lead owns live comparisons.

Ready commands, run from the repo root **only when the lead elects to compare**:

```sh
# Hydrogen low; change only low → medium for the second batch, using a fresh --out.
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env env \
  SCREEN_MODEL=gemini-4-hydrogen SCREEN_API=chat SCREEN_REASONING=low SCREEN_THINKING= \
  uv run --project server python screen/tools/bench_page_budget.py --count 5 --out /tmp/hydrogen-low

# After Go billing is settled: change only the thinking toggle against a low baseline.
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env env \
  SCREEN_MODEL=deepseek-v4.1-flash SCREEN_API=chat SCREEN_REASONING=low SCREEN_THINKING=disabled \
  uv run --project server python screen/tools/bench_page_budget.py --count 5 --out /tmp/deepseek-thinking-disabled
```

Use the ordinary benchmark mode, not `--profile-only` (that older diagnostic pins
the Go endpoint). Keep pane, ask and look settings equal between batches and judge
the generated page and patch at phone and wide sizes before selecting a model.

### Tutor tools (replace `commission_board` and `edit_board` in smart mode)

Growable visual fit correction (2026-11-13, `fix/screen-growable-fit`): old drawing
coordinates were counted as page overflow while choosing a new font size. A six-node
mind map consequently fell to 11 px plus scaling, despite empty space. During
measurement only, generated visual layers, chart canvases and image views are excluded;
their em-sized host boxes still participate, and components redraw at the chosen size.
The synthetic reproduction changes from 10.09 effective px to 20.5 px at 603×743.
The reported session page was checked locally: 19 px, no lint after the fix; no session
content is committed. A fresh Hydrogen low page took 9.19 s, with clean lint at 603×743
and 1000×700; its longer text still gives an honest 15.75 px `dense` warning at 370×610.
Evidence and repeatable checks covering ten visual kinds and resizing are in
`screen/review/2026-11-13-growable-fit/` and `screen/tools/check_fit.py`.

Patch preview correction (2026-11-13, `fix/screen-patch-history`): the request already
carried the original page and applied changes, but the renderer forgot that history.
An id inserted by one patch then appeared missing to the next preview. Preview now
replays earlier patch batches in order before the candidate, including completed
removals. Only the latest patch is sent to the child. A genuine `patch` error rejects
the whole candidate before RPC, saves `delivered: false` and notifies the tutor through
`on_failure`; there is no automatic model retry. Static preview uses reduced motion
and completes finite animations, replacing the old one-second wait. The child's
animations are unchanged. Synthetic browser evidence at both pane sizes is in
`screen/review/2026-11-13-patch-history/`; no family session content is copied there.

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
- Images are resolved on the server, not in the page (2026-11-13): a `query` searches
  Commons, a supplied `src` is re-looked-up, the bitmap is downloaded bounded (2 MiB,
  JPEG/PNG/WebP from Wikimedia hosts only) and the page writer judges the actual
  picture with the full lesson context before it is shown. Only a reviewed image ships,
  with its canonical Commons URL and author/licence credit; anything else becomes a
  text fallback. Image work stops inside the 12 s soft target; pages without images
  pay nothing. Live Hydrogen-low evidence (accepted Colosseum/Forum Romanum photos,
  a flower-lesson rejection, patch-image load fix) is in
  `screen/review/2026-11-13-screen-images/`.

### Filler sounds (2026-11-13)

A short sound from the fox while the reply is still on its way, so the wait does
not read as "nobody heard me". Off by default; `TUTOR_FILLERS=1` turns it on and
`TUTOR_FILLER_AFTER_S` (default 0.7) sets how long the reply may be silent first.
Made by a Muse worker in `feat/fox-fillers`; the code is `server/open_tutor/fillers.py`
and the details are in `server/README.md` ("Filler sounds").

- Played through LiveKit's `BackgroundAudioPlayer`, which publishes its own track:
  nothing reaches the chat context, the transcript, the caption or the debug
  `chat_item` records. No TTS call at that moment either: the clips are made once
  with the session's voice and cached per provider+model+voice.
- One filler per child turn at most, none for the greeting or any other session
  event, none in quiet-work or resource mode, none while the child speaks, and it
  stops at once when the child speaks or the reply audio starts.
- The web app now gives a second agent audio track its own `<audio>` element; one
  element per stream was enough before only because the agent had one track.

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

### The greeting, the session's voice, and a shorter leash (2026-11-13)

A real test with a child exposed the worst wait so far: the provider was slow, the
first LLM call timed out three times at 10 s each, and the child waited about 50 s for
a greeting. There was one provider per session and no backup. Three changes, all on
the worker (`feat/session-voice`, branch `feat/session-voice`):

- **The greeting is fixed text through TTS.** Four variants in
  `prompt.GREETING_VARIANTS`, the child's name, two sentences: who it is, that it helps
  with homework and schoolwork, and what they are working on today. `session.say`
  speaks it about a second after the session is ready, whatever the provider does, and
  the line is in the chat history as the assistant's turn. What
  `greeting_instruction` carried (do not greet again; for a returning learner, refer to
  last time) moved into `prompt.greeting_note`, in the instructions. Interruptible as
  before; a message typed before it plays replaces it (`TypedChat.start` got a
  `greet_instruction` override for that one reply).
- **The session's voice is chosen by a warm-up.** `TUTOR_LLM` stays the preferred
  route; `TUTOR_LLM_FALLBACK` adds an optional second one. While the greeting plays,
  both answer a short warm-up request (real system prompt and tools, one word to say,
  aborted at the first token) and the faster one serves the whole session, with the
  preferred route favoured inside `TUTOR_LLM_PREFER_WITHIN_S` (1.5 s) and 5 s cap. The
  choice never changes per turn: Gemini rejects history with function calls it did not
  sign. `llm_chosen` records the route and both timings; the report summary shows them.
- **A shorter leash.** `TUTOR_LLM_TIMEOUT_S` (5 s) per attempt with one retry, instead
  of the framework's 10 s with three. A route that fails before saying anything fails
  over to the other candidate when that one does not need thought signatures, for the
  rest of the session (`llm_failover`); otherwise the existing spoken apology applies.

Design note: `AgentSession` takes its LLM at construction and `Agent.update_options`
only swaps for the next turn, so `session_llm.SessionLLM` is a thin `llm.LLM` wrapper
that delegates `chat()` to the chosen route, waits for the decision if a first turn
arrives early, and owns the single failover. LiveKit's `FallbackAdapter` was rejected:
it is per-request failover, i.e. the per-turn switch thought signatures forbid.

Measured on dell5500 with my own instance (`gemini` preferred, `go-deepseek`
fallback, `TUTOR_SCREEN=smart`, real providers and voices), three passing e2e runs:

- The greeting audio started **0.83-0.92 s** after the session began (greeting event at
  0.38-0.43 s, TTS first audio 0.45 s later). It played even while the preferred route
  was pointed at a provider that never answers.
- The race chose gemini twice (warm-up 2.59/–, 1.72/4.46 s) and go-deepseek once
  (gemini did not answer, 4.83 s), and `llm_node_ttft` was 1.8-14.9 s: the providers were
  slow while several test sessions ran on the machine.
- Two of the three runs also hit one failover each (`gemini` -> `go-deepseek`) after gemini
  timed out twice at 5 s. The child still got an answer.
- Two earlier attempts failed: both providers exceeded the 5 s wall on the same turn
  (two attempts on one, one on the other, 15 s in total), and the existing apology ended
  the session. With these providers `TUTOR_LLM_TIMEOUT_S=8` is the safer setting; 5 s fits
  a warm prompt (2-3 s) but not a screenshot turn or a loaded provider.
`server/scripts/smart_screen_e2e.py --first-message-delay 8` sends its first typed message
only after the greeting, so a run measures the greeting path; the default sends at once
and the worker then answers with the greeting folded into that reply.

- A deliberately silent preferred route (a local socket that accepts and never answers)
  showed both recovery paths: the greeting at 0.83 s, `llm_chosen` keeping the preferred
  route because neither answered, then `llm_failover` to go-deepseek on the first turn.
  When go-deepseek later failed, the failover back to gemini was refused
  (`llm_failover_skipped`: it needs thought signatures) and the apology path took over.

### What Johan's test calls settled (2026-11-13)

Three real calls on the dev setup (Johan alone, with Lucas, and alone again). Decisions:

- **Filler sounds: off.** They played on every turn, because a reply never starts within
  0.7 s, and "only hurt the experience". `TUTOR_FILLERS` stays unset; the code is dormant.
- **Background voice cancellation: on** (`TUTOR_NOISE_CANCELLATION=bvc`) **and 2 s before
  sound may interrupt the fox** (`TUTOR_INTERRUPT_MIN_S=2.0`). Johan: before, he had to
  tense up to be understood and stay silent while the fox spoke; with both on he "could
  be relaxed". Keep both when this goes to production. Not yet tried with the children
  alone or with a quiet, distant voice.
- **The greeting is fixed text and cannot be interrupted.** Room sound in the first second
  had cancelled it before any audio in two calls.
- **Fox and page writer: Gemini 4 Hydrogen, thinking low**, DeepSeek V4.1 Flash as the
  fox's backup. Pages arrived in 6-10 s in the calls.
- **The mic button is the backstop** for talk that is not meant for the fox; its state is
  logged from the start of the session.
- Dev settings live in `~/.config/open-tutor-smart-dev/env` on dell5500, not in the repo.

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
`crowded` issue. Phones keep today's key under the map and still need less page content.
Evidence, screenshots and `screen/tools/check_map_key.py` are in
`screen/review/2026-11-13-map-key/`. `screen/REFERENCE.md` no longer says the key is
under the map, since the shell decides where it goes.

Phone regions map, 2026-11-13 (follow-up on `t3/phone-regions-map`, after PR #41): the
län map is now two boxes in normal flow — a drawing box and the key, never an overlay —
and the map is fitted to Sweden's 21 region polygons instead of the broad `sverige` view
that kept Norway, Finland and the Baltic in frame. On the same real pages, 370×610: the
country goes from 45×104 px inside a 327×217 px box with the key over it, to 85×192 px in
a 330×211 px drawing box with the key in its own strip below (codes on the map 12 → 20 of
21; the last stays dimmed in the key). 1000×700: 136×309 px in a 682×340 drawing box and
21 codes, no `crowded` issue, with the key as a 251 px column beside it. On a phone the
region map also takes a taller share of the page (`min-height: 16em` below 600 px), which
costs about 1 px of text on long pages: the shell reports `dense` rather than hiding it.
A phone drawing box stays landscape; a portrait one would need 12–13 px text on a
610-tall pane, so less page content is the cure. Evidence, screenshots, the measured
table and the same checks failing on the PR #41 shell are in
`screen/review/2026-11-13-map-phone/`.

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
