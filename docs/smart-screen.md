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

## Work packages

1. **Example screens, shell and components.** Owner: a separate Opus 5.5 thread. Status: started
   2026-11-12. Output is reviewed by the lead and Johan before anything else builds on it.
2. **The Screen agent on the server.** Owner: lead. Status: waits for 1. Follows the lesson,
   writes page bodies, checks its render, never blocks the tutor.
3. **One-page view, reveal and answer box in the web app.** Owner: lead, with workers. Waits for 1.
4. **First session with a child.** The test that counts.

## Open

- Which model and reasoning level the screen runs on (measure with the examples in place).
- Image generation: whether, and with what.
- How the tutor is told a page is ready without interrupting its own sentence.
