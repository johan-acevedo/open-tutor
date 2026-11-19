# Smart Screen: state and decisions

Lead: the thread "state of the project" (Claude, 2026-11-12). The lead keeps this file current.
Workers read it before starting and report against it. Decisions here were agreed with Johan
on 2026-11-12 unless marked open.

## 2026-11-19: first real call on the new build (middle band, 17 min)

One production call on `0bec30e` by a test learner in åk 7, desktop, 1019 s, 35 spoken
turns, 47 tutor replies, 5 screen pages, ended with Avsluta. Counts and timings only.

- **Voice-first naming works:** the name was said, confirmed and saved at 55 s
  (`set_learner_name`, one call); the grade was learned at 106 s.
- **"The voice interrupted itself" (learner's words): found.** Three times an answer
  typed on a page arrived while the tutor was speaking; the page-answer reply
  (`generate_reply`) started at once and cut the sentence off (the cut utterance never
  reached the transcript). Board pages already waited (`_prompt_when_free`); page answers
  did not. Fix: `PageAnswers` now awaits `wait_until_free` before deciding, so an answer
  waits its turn. "Also said aloud" (one reply, not two) now means a spoken turn
  since just before the first send contains the sent value(s); timing alone
  (review rounds on PR #83) mixed up unrelated questions, resends and long turns.
  The words are kept in memory for 2 minutes only, never logged by this class.
  Known limits (accepted): an unrelated question that contains the same value
  ("vad betyder uppgift 16") suppresses the separate feedback reply (the answer is
  still in the history); numbers said as words ("sexton") or with spelled-out units
  get one extra short reply after the tutor finishes.
- Reply speed: median 2.0 s from the end of the child's turn to the tutor's voice, p90
  3.7 s; two turns took ~6 s (slow LLM on both routes, TTFT 6.0 s once).
- Screen: 5 pages, 7.7–9.0 s each, all shown; the look pass timed out twice and was
  skipped once on the page budget. The preferred write route lost the hedge 4 of 5 times.
- 3 Deepgram TTS errors (recoverable), each while a hedged LLM turn was being decided and
  before the tutor spoke; no audible gap found. 2 false interruptions (`resumed`), one
  1 s after unmuting.
- The learner muted the mic 12 times (338 s in all) to talk to a parent. The tutor started
  speaking 7 times while muted, mostly finishing a reply already under way. Open: should
  muting pause proactive prompts (page ready, page answers)?
- The companion changed size and position with caption length and pose (seen by the
  parent); fixed in PR #84 (fixed caption/pill space, one character height per band).
  Deployed the same evening: Cloudflare (max-age 4 h) and browsers kept serving the old
  pose files, and the tunnel's API token cannot purge the cache, so pose URLs now carry
  `?v=POSE_VERSION` (`web/src/bands.ts`); bump it whenever the pose files change.

## 2026-11-19: ready for more languages (catalogues, no second language)

Swedish copy is no longer scattered through the code. One catalogue per surface,
all defaulting to Swedish, no behaviour or wording change:

- Web app: `web/src/locales/sv.ts` is the only place user-visible Swedish lives.
  Components look strings up with a tiny `t('key', {name})` helper (no i18next:
  one language, ~120 keys, compile-time `SvKey` so a missing key is a type
  error). Band copy (companion names, welcome bubbles,
  start buttons with `{name}` interpolation, switch labels) lives there too;
  `web/src/bands.ts` references the catalogue and carries no Swedish. The page
  `lang` follows the active locale (`htmlLang`, currently `sv`).
- Board shell: `screen/shell/locales/sv.json` holds the shell's visible labels
  (send/sent, answer/gap defaults, `Laddar {topic} …`, era suffixes, historical
  map credit). Both composers inject it — `web/src/shell.ts composePage` and
  `screen/tools/screenkit.py compose` (new `locale` param, default `sv`) — via
  `#ot-strings` JSON plus `{{LANG}}`; `shell.js` reads the injection and falls
  back to its one Swedish defaults object. No other Swedish literals in the
  shell's visible paths; region-matching keys (`lan`, `Skane`, ...) stay because
  they match Swedish page content, not UI chrome.
- Tutor: `server/open_tutor/locales/sv.py` holds the fixed spoken lines (greeting
  variants incl. nameless, provider-failure apology, default note topic,
  loading template). `prompt.greeting_line` and the worker pick the
  session locale via `learner["locale"]` (default `sv`, plumbed from the page
  through `POST /api/session`); the system prompt itself stays English and keeps
  telling the model to speak the session's language.

Rules for later work (also in AGENTS.md): no text baked into images (companions,
icons, generated art); every new visible string goes into the catalogue;
image-generation prompts must say "no text, no letters". A CI-friendly web test
(`web/src/locales/guard.test.ts`) fails on any Swedish-looking literal in
string literals outside `locales/` and `*.test.*` files.

Verified: web suite (175 tests incl. the new guard) and typecheck pass; server
suite (572 tests) passes; browser/server frame compose agree per band (theme +
`data-band`, `lang="sv"`, injected shell strings). Behaviour and every visible
string unchanged by construction (same literals, moved). Not run here: a live
voice call (provider cost) and real-call screenshots — the lead tries those on
dev before deploy.

## 2026-11-19: voice-first start (B's bubble, C's start button)

Johan's selected landing direction, implemented (`t3/voice-first-start-page`, PR #78's
pre-call name field removed). First visit: brand top-left, menu top-right, band companion
centred, a static welcome bubble ("Hej! Ska vi prata?") and one button
("Prata med Räven / Lodjuret / Björnen"). No name field, no profile grid, no speaking
animation before the call. Returning visit: "Hej {name}! Ska vi köra?", the same button
and an "Inte {name}? Byt" link; the menu's switch entry and that link both return to the
nameless first visit. The menu also holds "Om tjänsten" and "Integritet" notes.

The call starts with no name (`POST /api/session` accepts `name: ""`). The fixed greeting
greets without one and asks for it; the tutor repeats it back to confirm and saves it via
the new `set_learner_name` tool → `learner.setName` RPC (modelled on the grade path:
acknowledged, stale targets rejected, the call updates only on ack). The browser creates the
local profile then — an aborted nameless call leaves nothing behind — or attaches to an
existing local profile with the same name (its grade and recent notes are adopted and the
worker refreshes its instructions with them, as on a returning start), and remembers it
as the assumed student. A correction later is the same tool call again: correcting a name
learned in the call renames the profile in place (grade and notes kept); only a corrected
name matching a different stored profile attaches there instead (its notes and grade win,
the temporary profile is dropped). Names that are not names (digits, markup, more than
three words) are rejected by the tool and the browser before anything is stored, and a
name RPC from an ended session writes nothing. A typed name in the call (the text route
works with the microphone blocked) recovers from mishearing. Notes bind to the session
profile and follow the naming, resolving the target inside the write queue. `switch_student`
is unchanged and now lands on the nameless start page, or the returning page when the
target profile is known. Grade learning is unchanged. Band copy lives in `web/src/bands.ts`;
the protocol in `docs/protocol.md`; the start states have web tests (first, returning, Byt,
switch prefill) and the name tool/RPC has server and browser tests.

Not tested: the real voice name capture (no paid live call ran here) — Johan tries it on
dev. Verification screenshots (built app, first + returning × 3 bands × desktop + phone)
are in `design/bands/verification/`. No public deploy or live-service restart is part of
this work.

## 2026-11-18: age-band design decisions

Johan's corrected ranges: `tutor.labtopia.dev` serves åk 1–6 with the current fox and style;
`tutor2.labtopia.dev` serves åk 7–9, ages 13–15; `tutor3.labtopia.dev` serves gymnasiet and
adults together, åk 10+. The address fixes the band for the visit. The voice stays the same.

G1 Lodjuret is locked as the tutor2 companion. Expressive hands are a requirement for
teaching gestures. Johan selected V3 Björnen for tutor3, gymnasiet and adults together. The design record and exact generation prompts are in
[`design/bands/`](../design/bands/README.md); the corrected mapping and selections are in
[`decisions.json`](../design/bands/decisions.json).

The design integration builds on PR #78. All seven poses use transparent WebP under
`web/public/character/middle/` and `upper/`. The per-band `theme.css` under `design/bands/`
is shared by the app and teaching frame, including server previews. The fox assets and
primary theme stay unchanged. Fixed greetings and tutor self-introductions use the selected
companion name on the new bands, with the same TTS voice. On 2026-11-19 Johan selected B's speech bubble with C's single start button: no
name field before the call, the tutor asks by voice after starting, typed recovery inside
the call if needed. Refined mock images and the implementation handoff are in
`design/bands/landing-exploration/README.md`; the voice-first flow is not implemented yet.
Verification and exact export commands live in the design record. No public
deploy or live-service restart is part of this work.

## 2026-11-18: age bands, name-only start, no access code

Johan's evolution of the PRD (this PR, `t3/age-bands`; voice/LLM call not re-tested):

- **Bands by address (ranges corrected 2026-11-18).** `tutor.*` = åk 1–6 (primary, today's
fox and style), `tutor2.*` = åk 7–9 (middle, högstadiet), `tutor3.*` = gymnasiet + adults
(upper). One codebase; the host picks the band (per page load, never mid-session), and the
band decides the look (companion, theme, copy: `web/src/bands.ts`, `[data-band]` CSS).
Unknown hosts default to primary; `?band=` or server `TUTOR_BAND` override for testing.
Companions and themes: Räven (primary), Lodjuret (middle), Björnen (upper), PR #79.
- **Voice-first start (PR #80, replaces the name-only start).** One button, no name field;
the tutor asks the name in the call and saves it. Next visit assumes the same student
("Hej <name>! Ska vi köra?"); "Inte <name>? Byt" and "Byt elev" in the menu.
- **The tutor learns the grade** (`learner.setGrade` RPC → serialized browser queue →
stored profile; stale targets rejected, failed calls change nothing) and **switches
student in-call as end-and-prefill** (`learner.switch` RPC resolves/creates the profile
and acks with its id; the worker then ends this lesson exactly like Avsluta and the
browser shows the start page prefilled for B — no automatic reconnect, no continuation
session; failed calls never arm anything and keep A. B counts as a new session under
the hourly cap. B is remembered as active only when B's session starts). On band 3 the tutor
finds out naturally whether the learner is a gymnasiet student (which year) or an adult;
only adults skip the grade. Unknown grades default to the band in the tutor and screen prompts.
- **No access code.** The gate is gone from page and server (incl. `?kod=` links and
probe headers); Sweden-only check (`cf-ipcountry`) and `TUTOR_MAX_SESSIONS_PER_HOUR` stay.
The header is forgeable by direct-origin callers, so the web service must only be reachable
through the Cloudflare tunnel (production binds a tailnet address) — no ingress auth is
built; see `server/README.md` and `deploy/README.md`. Same voice on all bands.
- Docs: PRD (bands, onboarding, grade learning, switching, adults + companions in
scope), AGENTS.md users line, README, `docs/protocol.md`, `server/README.md` settings.

## 2026-11-18: the Smart Screen is the only mode, and the legacy board is deleted

Johan's decision. Production and dev already ran with `TUTOR_SCREEN=smart`; the code default
was still the retired card board, and the textbook materials library had never been tried in
a call. One PR removed both. Read the rest of this file as history: phrases like "behind
`TUTOR_SCREEN=smart`", `commission_board`, `edit_board`, `search_materials` and
`show_material` describe what no longer exists.

Removed:

- **The `TUTOR_SCREEN` switch.** The worker always builds the Screen and `SmartTutor`. An env
  file that still sets `TUTOR_SCREEN=smart` keeps working unchanged; any other value is
  logged as ignored at session start. Prod and dev env files were not edited.
- **The board model.** `board_model.py`, `board_budget.js`, the `commission_board`,
  `edit_board` and the drawing tools with their placeholders, and `BOARD_MODEL`,
  `BOARD_THINKING`, `BOARD_MAX_TOKENS`. `test_board_render.py`, `test_board_budget.py` and
  `web/e2e/board_render_check.py` went with them.
- **Board item kinds with no producer:** `text`, `steps`, `mindmap`, `svg`, `html` and their
  web renderers, KaTeX-in-the-page markdown, the SVG sanitiser, and the focus-by-step state.
  Kept: `page` (the Smart Screen), `resource`, `homework`, `image` and `pending`. `pending`
  has no producer either; it stays because it is the client's arrival state and still
  validates on both sides.
- **The materials library, entirely:** `server/open_tutor/materials/`, the `/api/materials`
  and `/materials/...` routes, the `search_materials`/`show_material` tools and their
  `material` board kind, the `ml` dependency group (EmbeddingGemma/torch), `TUTOR_MATERIAL_INDEX`
  and the other `TUTOR_MATERIAL*` variables, `server/scripts` that only served it, its tests,
  `docs/material-library/`, `deploy/materials-preview.sh`, the `material-tools` CI job,
  `tools/skolverket`, `tools/siyavula` (and the in-repo `skolverket` skill that pointed at
  them), and the MaterialSection card.
- **The single prompt.** `prompt.smart_instructions()` is folded into `BASE`: the removed
  board-commissioning and school-book sections are replaced by the screen guidance that the
  live worker used. `instructions()` is the only prompt.

Kept on purpose: `fillers.py` and `noise.py` with their flags, Playwright/Chromium (the
Screen renders pages with it), the `screen/review/` evidence, and the screen's own review and
benchmark tools.

Not done in that PR: no deploy and no service restart; prod and dev still run the previous
build until the lead deploys. Things outside this repository that now have no consumer are
listed in the PR description (the materials preview services on elitebook, its env file, the
served corpora and cached indexes).

## Where things run

- Trunk: `main`. The Smart Screen branch was merged on 2026-11-13 (PR #51); branch from `main`.
- Production: ThinkCentre (https://tutor.labtopia.dev), `main`, Smart Screen on since
  2026-11-13 (the only mode since PR #73). Last deploy 2026-11-19 evening: `f4356d8` (#83 page answers wait, #84 steady companion), before that 2026-11-19: `0bec30e` (PRs #77–#81:
  bands on tutor/tutor2/tutor3, companions, voice-first start, catalogues).
  `TUTOR_ACCESS_CODE` removed from the env file: access is Sweden-only
  (`TUTOR_ALLOWED_COUNTRIES=SE`) with `TUTOR_MAX_SESSIONS_PER_HOUR=12` as the only cost cap.
  Rollback commit `9063c47`, env backup `env.bak-20261119-predeploy`. The restart cut
  one lesson that started 13 s after the idle check (LiveKit re-dispatched it to the new
  worker): check for a live call in the same command as the restart. It is a public test: deploy only with Johan's go, and never
  restart during a call. `deploy/install.sh` over ssh reports a failed health check because
  it probes 127.0.0.1 while the service binds the tailnet address; check that address instead.
- Development: dell5500, services `open-tutor-smart-dev-agent` and `-web`, run from a checkout
  of `main`. Changes are tried here first.
- New to the repository: start with `AGENTS.md`.
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
  diagrams — including graph side/segment labels that cross straight outlines or each other, placed from the polygon
  winding with measured clearance and flagged when the layout remains tight, and polygon side lengths that disagree
  with their labels on to-scale figures; arbitrary text/curves are not checked)
  for the Screen agent's bounded correction step. Graph and length warnings update on patches/reveals; patch previews
  use final lint so repaired warnings clear. Evidence: `screen/review/2026-11-13-graph-labels/` and
  `screen/review/2026-11-13-lengths/`.
- **Components**: `ot-steps`, `ot-written` (computed uppställning incl. liggande stolen), `ot-clock`, `ot-fraction`,
  `ot-numberline`, `ot-balance`, `ot-graph` (JSXGraph), `ot-chart` (Chart.js from a `<table>`), `ot-map` (d3-geo with
  Natural Earth and historical borders, plus Sweden's 21 län with letter codes and a key; replaces Leaflet),
  `ot-image` (Wikimedia Commons), `ot-timeline`, `ot-cycle`,
  `ot-mindmap`. The model writes no JavaScript. Five graph reference lines document the two-curve circle
  recipe and centred `ot-text`; exact English Hydrogen-low pages were inspected at phone/wide sizes.
  Text annotations currently have no visible pointing feedback (documented). Evidence:
  `screen/review/2026-11-13-circle-text/`.
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
Other models keep the Go route. Since 2026-11-14 there is one fallback between
providers: `SCREEN_FALLBACK=cc` retries a failed screen call on the same Muse model
on Command Code (see the bake-off and backup sections above).
`SCREEN_THINKING=disabled` on a DeepSeek chat model sends
`thinking: {type: disabled}` and omits `reasoning_effort`; empty keeps today's low
reasoning request. Invalid combinations fail explicitly. Page/patch `meta.json`
records the effective model, API, reasoning and any explicit thinking toggle.

The controls follow [Google's compatibility API](https://ai.google.dev/gemini-api/docs/openai)
and [DeepSeek's thinking toggle](https://api-docs.deepseek.com/guides/thinking_mode/).
HTTP request tests use the real SDK with a local recorded-response transport;
Hydrogen low subsequently passed the lead's five-job comparison (8.7–11.8 s total,
clean lint) and live lessons, and is now the dev page writer. Johan approved Go balance
billing for Muse Spark and DeepSeek, so their probes and helpers may run again. The
DeepSeek thinking-disabled comparison remains unrun; the lead owns model selection.

Ready commands, run from the repo root **only when the lead elects to compare**:

```sh
# Hydrogen low; change only low → medium for the second batch, using a fresh --out.
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env env \
  SCREEN_MODEL=gemini-4-hydrogen SCREEN_API=chat SCREEN_REASONING=low SCREEN_THINKING= \
  uv run --project server python screen/tools/bench_page_budget.py --count 5 --out /tmp/hydrogen-low

# Optional DeepSeek comparison: change only the thinking toggle against a low baseline.
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
| `ask_screen(ask, show="auto")` | asks for a new page or a change to the visible one; returns at once | page 5–15 s, change 1–7 s |
| `show_page(page_id)` | puts a held page (`show="hold"`) in front of the child | instant |
| `reveal(part_id)` | uncovers a hidden answer or a `later` part on the visible page | instant |
| `point(part_id)` | highlights one part of the visible page | instant |
| `screen_loading(topic)` | dims the visible page and shows "Laddar <topic>…" at once; empty clears | instant |
| `screen_status()` | one cheap line on what the screen is doing (writing / pictures / ready / shown) | instant |

- **A finished page appears on the screen by itself as soon as it is ready** (2026-11-16;
  `show="hold"` keeps the old invisible behaviour). When it is shown the tutor's
  chat context gets the screenshot, the page source (so it knows the ids) and a line saying the
  page is on screen. If the tutor is silent and the child is not speaking, the
  worker prompts it once; if it is speaking, the prompt waits until it has finished.
  A failed auto-show falls back to the invisible path with a note.
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

**Muse at its default temperature (2026-11-14).** The `go` route sent `temperature=0.6`
since milestone A, with no recorded reason. Meta's Muse Spark docs say the model is tuned
for the default (1.0) and to leave sampling unset. Bench: the production tutor prompt and
tools on a fictional replay of a unit-circle session, Go, reasoning `minimal`, 8 runs per
row, interleaved; seconds to first speech, median / max.

| Variant | A "håller du med?" | B "rita igen" |
|---|---|---|
| temperature 0.6 (old) | 2.18 / 3.03 | 0.96 / 1.61 |
| no temperature (now) | 1.35 / 2.51 | 0.88 / 1.34 |
| `parallel_tool_calls: false` | 1.92 / 3.05 | 1.11 / 2.13 |
| `prompt_cache_key` + `prompt_cache_retention: "24h"` | 2.23 / 4.62 | 1.36 / 1.99 |

No errors or silent turns; tool choice was unchanged (B drew in 8/8 for every variant).
One sitting, so part of the gap may be noise; spoken quality was not judged, which a real
session has to settle. Kept parallel tool calls on (the default; Muse made no premature
double call here). The cache options gave nothing: Go already caches the static prompt per
`x-opencode-session` (about 3 300 of 3 340 tokens cached from the second call). Go accepts
`include: ["reasoning.encrypted_content"]` and a replayed reasoning item, but LiveKit drops
reasoning items between turns; replaying them is an open experiment. The chat routes
(DeepSeek, Gemini) still send 0.6, unmeasured.

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

### Background voice cancellation: on, and what it does not fix (2026-11-13)

A parent and a 13-year-old at one phone: room sound was taken for the child, cancelled the
greeting, cut the fox off mid-sentence and made it answer talk that was not meant for it. The
owner's decision was LiveKit's background voice cancellation. It is now a setting,
`TUTOR_NOISE_CANCELLATION` = `off` (default) | `nc` | `bvc`, applied server-side to the child's
inbound audio before the VAD and the recogniser (`server/open_tutor/noise.py`). `off` behaves
exactly as before and does not even import the plugin. Details, docs links and cost are in
`server/README.md` ("Noise and background voice cancellation"). PRs: #47 (the switch) and the
follow-up that moved the import to prewarm.

**Measured on dell5500 with my own worker and web service** (`open-tutor-nc-dev`, own ports, own
debug dir; the shared dev services were not touched), real providers (Soniox, Deepgram Flux,
Gemini 4 Hydrogen), `TUTOR_INTERRUPT_MIN_S=0.4` as in production. The child's microphone was a
prepared 24 kHz WAV published into a real room: no recordings of real people, everything
synthesized with the session's own voice, the "other person in the room" being that voice slowed
and pitched down 18 %.

One session per row. "Turn" = the tutor started thinking or speaking; "interrupted" = the fox
was mid-answer when the clip played and stopped before its sentence ended.

| Mode | Clip | Turn | Transcript the STT produced | Fox interrupted |
|---|---|---|---|---|
| off | background only (4.8 s of other talk) | yes | the whole other voice, verbatim ("Ja, alltså, jag tänkte att vi kan ta det där i morgon…") | yes, 1.89 s in |
| bvc | background only, run 1 | yes | the same sentence verbatim | yes, 1.95 s in |
| bvc | background only, run 2 | yes | the same sentence verbatim | yes, 1.93 s in |
| bvc | background only, run 3 | yes | the same sentence verbatim | yes, 1.94 s in |
| nc | background only | yes | the same sentence verbatim | yes, 1.45 s in |
| off | clear child sentence | yes (7.09 s) | "Hej Räven, jag behöver hjälp med matte-lexan…" | yes, 1.92 s in (the child was speaking) |
| bvc | clear child sentence | yes (7.17 s) | the same sentence | yes, 1.97 s in |
| off | child + other talk 14 dB down | yes (7.08 s) | only the child's sentence | yes, 1.88 s in |
| bvc | child + other talk 14 dB down | yes (7.20 s) | only the child's sentence | yes, 1.91 s in |
| off | child + other talk 4 dB down (×2) | yes (7.10, 7.16 s) | only the child's sentence | yes, 1.88 / 1.96 s in |
| bvc | child + other talk 4 dB down (×2) | yes (7.09, 7.20 s) | only the child's sentence | yes, 1.92 / 2.01 s in |

The filter itself, measured by subscribing to the same published track twice in one room, once
through the filter and once plain, and comparing levels (`noise_cancellation_bench.py`):

| Clip | Model | Speech level change | Overall level | Peak |
|---|---|---|---|---|
| noise bed (no speech) | bvc | −6.5 dB | −25.0 → −45.4 dBFS | 12,319 → 5,273 |
| noise bed (no speech) | nc | −13.8 dB | −20.4 → −58.3 dBFS | 11,783 → 1,257 |
| other talk only | bvc / nc | −0.3 / −0.2 dB | unchanged | unchanged |
| child sentence | bvc / nc | −0.7 / −0.3 dB | −22.2 → −23.0 / −22.5 | nearly unchanged |
| child + talk 14 dB down | bvc / nc | +0.1 / −0.1 dB | −21.8 → −23.1 / −23.2 | unchanged |
| child + talk 4 dB down | bvc / nc | −2.5 / −0.8 dB | −20.8 → −25.1 / −22.9 | 29,429 → 22,899 / 25,049 |

What that says:

- The filter works and costs nothing measurable per turn: non-speech noise is removed hard, and
turn detection latency was 7.08-7.37 s in every mode (dominated by STT endpointing, no
systematic difference). Worker CPU was 0.8-1.3 s per ~65 s session in both modes, i.e. noise.
- **BVC did not stop the failure that hurt most.** Other talk while the child is silent was still
transcribed as the child and still cut the fox off at about 1.9 s. That is what the model is: NC
keeps all speech, and BVC removes *non-primary* voices — when the child is not speaking, the
room's voice is the primary one, so it passes. Voice isolation cannot know whose voice is the
child's without being told.
- It did not damage the real child turn either (case b and c: transcript unchanged, interruption
  unchanged — and in b and c the interruption was correct, the child really was talking).

What this rig does **not** let me conclude:

- Nothing about a real parent at a distance. My "other voice" is the same synthesized voice,
pitched down, at the child's own loudness and without room reverberation; a voice across a room
differs in level, timbre and echo, which is exactly what BVC could key on. The honest next test
is the owner's phone, by ear, with `TUTOR_NOISE_CANCELLATION=bvc`.
- Nothing about the softer BVC gains: the level meter says the louder mixed case loses 2.5 dB of
speech energy, which is consistent with the second voice being partly removed, but I could not
turn that into a transcript difference with this material.
- Whether BVC is billed. The pricing page names Krisp NC under background noise suppression and
Krisp VIVA under voice isolation; BVC is in neither row.

Latency note for the next person: the plugin's first import blocked the event loop for about a
second inside a session on the dev setup, and the greeting moved from 0.3 s to 1.3 s. It is now
imported at prewarm (`noise.warm_up`); with `bvc` the greeting lands at 0.48-0.86 s in the "one
process per job" dev mode, where prewarm runs at job start, against 0.22-0.29 s with `off`.

What is left for the lead or a later change: if the fox still answers the television, that is a
turn-taking problem, not a filter problem — a level or distance gate on the child's track, or a
longer `TUTOR_INTERRUPT_MIN_S`, is where it would be solved. Changing interruption thresholds was
explicitly out of scope here.

### What a public test call showed (2026-11-16)

Two production calls by one test learner (upper secondary), 3 and 4.5 minutes, both ended by
the learner, no tool or provider errors. Tutor first audio: median 1.4-1.5 s, slowest 2.8 s.
Johan sat beside the learner. Findings and decisions:

- **Interruption threshold 2.0 s -> 1.6 s** (`TUTOR_INTERRUPT_MIN_S`), on dev and production
  the same day. 2.0 s felt too long: the fox kept talking over the learner.
- **Portraits failed to load.** A history page asked twice for a portrait of a Swedish king.
  First call: the image step had about 1 s left of the 12 s page target and timed out.
  Second call: Commons found three Nationalmuseum portraits, all stored as TIFF, and all were
  rejected as `image/tiff`. Commons serves those as JPEG thumbnails, but we never requested
  `thumbmime`, so the original's type decided. Fixed by requesting it (checked against the live
  API: the portraits now download as JPEG). Many museum scans on Commons are TIFF.
- **Stale screen after a subject change.** When the learner moved from maths to history, the
  old maths page stayed up while the fox spoke about history: 27 s, 21 s and 15 s. In each
  case the new page was ready for part of that time (18 s, 11 s, 6 s) but stayed hidden
  until the fox's next turn called `show_page`. Fixed 2026-11-16 (see below): show-when-ready
  is the default, the fox can dim the old page at once, and the 12 s target no longer cuts
  image reviews off.
- **Open: the 12 s page target squeezes images.** Images are fetched only after the page is
  written, from what is left of the target. Johan: a longer wait is fine as long as the fox
  keeps talking about the material and can check progress. Fixed 2026-11-16 (see below):
  image work starts while the page is still being written and may run to the job limit.

### Reveal mode, loading state, progress, longer images (2026-11-16)

Branch `t3/screen-ready-image-progress`. The 16 Nov stale-screen and image-timeout
findings above, plus the follow-up that image work should start while the page is
still being written. Server, shell, web and prompt; tests on all four.

**Reveal mode.** `ask_screen` takes `show="auto"` (default), `"show"` or `"hold"`.
A finished page appears on the screen by itself as soon as it is ready; the ready
callback delivers it through the same path as the `show_page` tool (and falls back
to the old invisible-plus-prompt path when auto-show fails), so a new subject no
longer waits behind the old page for the fox's next turn. `show="hold"` keeps
the old behaviour for pages that must not give away an answer before the child
tries. Owner decision to confirm: show-when-ready as the default (Johan's steer
was "probably show-when-ready for a new topic"; `auto` is exactly that today,
with no topic detection -- the fox picks `hold` when it matters).

**Loading state.** `screen_loading(topic)` dims the visible page and shows
"Laddar <topic>…" at once (`board.loading` RPC, shell veil with spinner;
empty topic clears). A successful patch clears a stale veil by itself, and a
failed job clears it best-effort, so no "Laddar …" survives. Screenshots (real
shell, phone + wide): `screen/review/2026-11-16-loading/`. The prompt tells the
fox to dim first when it moves to a new subject, and never to teach from, point
at or describe a page about another subject than the one discussed.

**Progress.** `screen_status` reports one cheap line (writing / pictures /
rendering / checking / ready / shown, plus elapsed and whether pictures are
still arriving). The Screen tracks a phase per job; the fox is told to say one
short Swedish sentence and keep teaching.

**Longer images.** The image deadline is the job limit (about 17 s of a 20 s job)
minus render reserves, not the 12 s soft page target minus reserves; the voice
turn stays non-blocking as before, and images that cannot finish in budget still
fall back to text instead of failing the page. On top of that, image work now
starts while the page is still being written: the write call's streamed text is
scanned for complete `<ot-image>` slots (attrs plus child labels, which the
vision review judges) and each slot's search + download + review starts at once,
so slots resolve concurrently with the writing -- and every slot is resolved to
reviewed image HTML or a text fallback before the page is shown. Nothing
unresolved, no query and no model-supplied URL ever ships; a slot the writer
changes or drops resolves from the final body like any other slot. Hedged/raced
attempts share prefetch tasks by full slot key (no double vision reviews); the
loser's unique prefetches are cancelled at the decision, the rest at job end,
bounded like the other loser cleanup. Synthetic timing with identical 0.6 s
write + 0.6 s review sleeps: 1.21 s sequential vs 0.61 s with prefetch; on live
jobs the overlapped review is the whole multi-second image step.

**Not tested.** No live provider calls and no real session: prefetch against real
Commons + a real review model, and one full live lesson, are still open.
Malformed streamed HTML (a slot that never closes) resolves inline at prepare,
as before.

Review follow-ups, same PR (reviewer-reproduced, each with a
regression test in the real call order):

- **Prefetches share verdicts, never HTML.** Slot keys are the full slot
  (every attribute plus child labels); the pool returns only the review
  verdict and every path renders from the served page's own slot, so a loser
  can no longer reveal a hidden slot or lend its labels. An already-rendered
  body still re-prepares without re-review via the `rendered` exact-slot index.
- **The image deadline is the job limit minus reserves** (about 17 s),
  computed at job start -- no 6 s clamp that expired mid-write.
- **`aclose` drops the prefetch pool** through the reaper bound: no
  `screen-prefetch-*` task survives shutdown.
- **The veil clears at terminal states.** A held page ready clears the old
  page's veil (the fox reveals when it wants); auto-show clears the replaced
  frame's veil; failures already cleared.
Fourth review, same PR: show-first-then-fill is dropped, for kept. Four rounds
of races -- a loser deciding a hidden slot, corrections overwritten by late
fills, a page switch mid-render, a parent replacement keeping the id,
unreviewed model `src` and nested `<ot-image>` reaching the browser verbatim --
showed the handoff cannot be made simply safe: every fix moved the race
instead of removing it. Images resolve before the page is shown again, as on
`main`: every `<ot-image>` is replaced by reviewed image HTML or the text
fallback before delivery, and nothing unresolved, no query and no
model-supplied URL ever reaches the browser. Kept from the rounds: the
streaming prefetch (full-slot keys, loser cancellation, shutdown reaping,
rendered exact-slot reuse), concurrent slots, the job-limit image deadline
(~17 s), reveal modes, the `screen_loading` veil, `screen_status` (so the fox
can talk and give an update while images take longer), the held-veil fix, and
the serialized delivery path (`_board_lock` now also guards `share_resource`
and every other board RPC). A later take that wants deferred images must
answer: full-slot identity end to end, a single delivery critical section with
the final check adjacent to the send, and no verbatim model markup on the
wire at any point.

### Parallel Image Search, second image source (2026-11-18)

`SCREEN_IMAGES` picks the source a page job searches: `commons` (default,
today's Wikimedia-only behaviour), `commons+parallel` (both at once via the
Parallel Images API in fast mode; the review judges Commons candidates first
and takes the first candidate it accepts), or `parallel`. The vision review of
the actual picture stays the gate; Parallel results carry no licence data, so
Johan's call is a plain site credit, `Källa: <domain>`, rendered like the
Commons credit. Set on dev (`~/.config/open-tutor-smart-dev/env`) the same day;
it takes effect when the code deploys there.

- **Server-resolved, like Commons.** The search answers titles, direct image
  URLs and source page URLs. Downloads stay bounded (2 MiB, JPEG/PNG/WebP
  sniffed, short timeout) but accept any public `https` host: every hop's
  hostname is resolved and refused unless all its addresses are public (no
  private, loopback, link-local, CGN/tailnet, multicast or reserved space),
  re-checked on each of at most 3 redirect hops, which are followed manually.
  Each hop then connects only to its validated addresses (pinned: no second
  DNS lookup at connect time, proxies off) while TLS still verifies the
  hostname. Plain-`http` file URLs, which Parallel returns often, are offered
  over TLS and refused when the host does not serve valid `https`.
- **Approved bytes are served by us, never the remote URL.** A Parallel
  approval stores the reviewed bytes under the session (`<session>/images/`)
  and the page ships `/api/images/<sha256>.<ext>` from our own web app
  (correct Content-Type, year-long immutable cache, nosniff): the original
  URL could later redirect to unreviewed content. The site-relative URL
  inherits the page's own origin, so the frame CSP (`img-src data: https:`)
  needs no widening, and the 15 kB RPC limit still holds (no data URIs).
  Commons keeps its canonical remote URLs. Only reviewed bytes are ever
  stored; unknown hashes answer 404.
- **Graceful failure.** No key, auth/credit/quota failures (401/402/403/429 or
  quota words in the body) and rate limits cool Parallel down for 10 min;
  timeouts, 5xx, any transport error and broken payloads for 1 min. Commons
  candidates are reviewed as soon as the Commons search returns; Parallel is
  awaited only when Commons yields no accepted image, within the remaining
  image deadline, and its still-running search is then cancelled and drained.
  Each source's failure becomes a rejection, never a page failure: while
  cooling down the job silently falls back to Commons-only (or a text
  fallback in `parallel` mode). Nothing Parallel does can fail a page or
  block the tutor.
- **Records.** Every image event carries `image_source` (commons/parallel),
  `query` and search `latency_s` with the verdict and reason; Parallel
  acceptances also carry `served_as` (our `/api/images/…` URL). Page/patch
  `meta.json` gains an `images` section (strategy, Parallel cool-down state,
  reviews) next to the existing `image_reviews`.
- **Live comparison** (`screen/review/2026-11-18-parallel-images/`, six asks,
  scripted body, streaming writer so prefetch runs as in production): both
  king portraits, the Colosseum and the Roman map accept the same Commons
  picture first in both modes (Parallel costs ~1 overlapped search, no download
  or review); the water cycle accepts a Swedish USGS illustration from
  Parallel where Commons had nothing; the flower correctly rejects bad Commons
  pictures on both modes and falls back to text. Caveat: a slot gets ~17 s of
  search + review, so six sequential vision reviews do not fit when both
  sources return full lists and the provider is slow -- review concurrency is
  the follow-up if real lessons hit this (done the same day, below). No
  cool-down triggered; error paths
  are unit-tested with recorded responses, including private-IP and
  redirect-to-private refusals.
- **Security review (GPT-6.1 Sol, 2026-11-18, all five reproduced and fixed
  on `t3/parallel-image-search`).** DNS rebinding between validation and
  connect (now pinned per hop, proxies off); the shipped remote URL able to
  redirect elsewhere after review (now our own content-addressed bytes);
  a slow Parallel search eating the Commons review budget (now Commons-first
  with the remaining deadline); transport errors escaping the Parallel
  boundary and orphaning the sibling (now all `HTTPError` cool down
  briefly, per-source isolation, cancel and drain); malformed 2xx JSON never
  cooling down (now a transient failure; a legitimate empty `results: []`
  stays a normal empty result).

### Concurrent candidate reviews (2026-11-18)

Branch `t3/concurrent-image-reviews`. The follow-up the parallel-image caveat above
asked for: candidates for one `<ot-image>` slot were downloaded and vision-reviewed
one after another, so ~17 s of image budget fitted about four reviews, and when the
first candidates were bad (a flag-silhouette map, the wrong flowers) the good one was
never judged and the page fell back to text. Now the top of the list is judged at
once; nothing else about the image step changes (search, gates, store, delivery).

- **How many at once.** `SCREEN_IMAGE_REVIEWS` (default 3, max 6): the candidates
  admitted in rank order, further ones admitted as reviews settle. Three is a search
  list, so a whole Commons list is judged while the first answer is still on its way;
  `1` restores the sequential behaviour exactly. The prefetch pool resolves several
  slots concurrently, so the same number is a per-page gate on reviews in flight: two
  slots do not double what the screen model route is asked to serve. `commons+parallel`
  keeps its phase order, so Commons candidates are all judged before any Parallel one.
- **The ordering rule** (also in `page_images.py`): walk the candidates in preference
  order (Commons by search rank, then Parallel by search rank). A finished rejection or
  failure is stepped over; a review still in flight blocks, because a better-ranked
  candidate may yet be accepted. So the winner is *the best-ranked acceptance whose
  better-ranked reviews have all finished* -- a faster lower-ranked acceptance never
  pre-empts a better-ranked review that is still being judged -- and once the deadline
  hits, the best-ranked acceptance among the reviews that did finish. The reviews stop
  0.25 s before the absolute image deadline so that decision, and the drain below, run
  on our own clock instead of the caller's outer timeout.
- **Nothing is left running, nothing unreviewed ships.** Once a winner is chosen or the
  deadline hits, every other download and review is cancelled and drained -- within the
  time left before the image deadline (1 s at most), and a caller cancellation that lands
  during that drain is re-raised instead of swallowed, so the page falls back to text
  rather than shipping a picture after its own deadline; a
  still-running candidate is recorded as rejected (`cancelled: a better-ranked
  candidate was accepted`, or `image review cancelled or budget exhausted`), and a
  review that was accepted but outranked says so. Only the winner reaches
  `_keep_approved_bytes`, so Parallel bytes are stored (and served as
  `/api/images/<sha256>.<ext>`) only for the picture that actually ships: a lost
  acceptance leaves neither an event that claims a served image nor a file behind.
  The text fallback for the slot comes from the best-ranked rejection that offered one,
  instead of from whichever review happened to finish last.
- **Provider calls do not multiply.** A hedged review can start the same review on the
  backup provider, so hedging all N would spend up to 2N calls per list. Only the first
  review a slot actually admits keeps the hedge/failover, whichever source serves it
  (with `SCREEN_IMAGES=parallel`, or a Commons list that came back empty, that first
  review is a Parallel one and it still gets its failover); the rest are single attempts
  (`_call_model(hedge=False)`, recorded as `single_attempt` in the call stats when a
  backup was armed). A slot therefore costs at most N+1 calls per source list, and the
  concurrency is itself the redundancy a hedge would have bought.
- **Records.** Each candidate's `image_reviews`/`images.reviews` entry keeps today's
  keys and gains `rank`, `start_s`, `download_s`, `review_s`, `finished_s`; entries stay
  in rank order regardless of completion order, and `images` gains
  `review_concurrency`. Charge for the change: a slot now judges up to N candidates
  even when the first is accepted (≈0.5 extra vision call per slot in the run below).
- **Tests.** The ranking rule (a slower better-ranked acceptance still wins; quick
  lower-ranked acceptances wait for their betters), the deadline (a hung better-ranked
  review costs nothing: the best finished acceptance is taken), cancellation and drain
  (losers cancelled, no `page-image-review-*` task left), isolation (one failing review
  rejects only its candidate), concurrency (three at once, `1` sequential), the per-page
  gate, only the first review hedging, and only the winning Parallel bytes
  reaching the review store. Server side: `_call_model(hedge=False)` makes exactly one
  call with a backup armed, and `SCREEN_IMAGE_REVIEWS` parsing. The three review fixes
  have their own regressions (they fail on the branch as first pushed): a cancellation
  that lands in the drain, the gate counting reaped provider work through the real
  `Screen` wrapper and its reaper with a fake provider seam, and a `SCREEN_IMAGES=parallel`
  slot failing over to a healthy backup.
- **Review fixes (GPT-6.1 Sol cross-family review, 2026-11-18; all three reproduced,
  tests added).** (1) The drain of the losers caught `CancelledError` and carried on to
  storage and rendering, so a caller cancellation landing there (a loser's HTTP response
  or client close being slow) let an outer `wait_for`/`timeout_at` see a normal return
  and the page render after its deadline; the drain is now bounded and re-raises the
  caller's cancellation, while our own cancels of the losers still only raise inside
  them. (2) The per-page review gate was released when the review callback returned,
  but the cancelled provider request lives on in the reaper (cancel plus stream close),
  so a page could run 5 provider requests across 2 gate slots with a concurrency of 3;
  an image review now waits, bounded (1 s), for the request it gave up on to finish
  before releasing its slot, tracked per owning task. (3) Every Parallel review was
  called with `hedge=False`, so with `SCREEN_IMAGES=parallel` (or an empty Commons list)
  a slot's first and only review had no failover and a failing primary meant text; the
  hedge now belongs to the slot's first actual review, not to the Commons path.
- **Live comparison** (`screen/review/2026-11-18-concurrent-reviews/`, `origin/main` vs
  this branch, eight fictional asks, two runs each, real providers): acceptance 11/16 →
  12/16, median image slot 4.74 s → 4.86 s, runs the budget cut 5 → 1, completed vision
  reviews 22 → 34. The acceptance gained is the Swedish Empire map that timed out on
  `main`; the dandelion ask now judges all five candidates in ~12 s instead of two to
  four in 15.3 s, and correctly rejects all of them. Preference order held everywhere
  (identical accepted file as `main` whenever Commons ranked a good picture first). The
  Parallel water-cycle diagrams are rejected as cropped/grey in both checkouts, so that
  is the source's content, not this change. Not tested live: a real lesson, and a
  multi-slot page (the gate is unit-tested only).

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
  fox's backup. Pages arrived in 6-10 s in the calls. (Superseded 2026-11-14: the
  model bake-off below moved both to Muse Spark on Go, with Command Code as backup.)
- **The mic button is the backstop** for talk that is not meant for the fox; its state is
  logged from the start of the session.
- Dev settings live in `~/.config/open-tutor-smart-dev/env` on dell5500, not in the repo.

### Model bake-off (2026-11-14)

Nine models, two reasoning levels each ("lo" = lowest accepted, "hi" = one step up),
three runs each: 54 pages, blind-judged by GPT-6.1 Sol on the rendered images only.
The ask was the tutor's first real `ask_screen` (tutor-written, no child words); the
learner is fictional ("Testbarn"). Every job ran the production Screen pipeline (write,
render, lint, look, retry); the job timeout was raised from 20 s to 90 s so slow pages
were still judged, and `total_s` above 20 means production would have failed the job.
The tutor bench replayed a fictional unit-circle lesson (paraphrased lines, same turn
structure) through the real prompt and tools, 5 runs per case, measuring to first speech.
Scripts: `server/scripts/bench_tutor_speed.py`, `screen/tools/bench_screen_models.py`.

Screen: quality is the blind judge's mean overall /10 (lo-hi over 3 runs); page-ready is
the median full job time (write + render + look/retry); within-20 counts jobs production
would have kept. Sorted by quality, then speed.

| Page writer | Quality /10 | Page-ready med s | Within 20 s |
|---|---|---|---|
| Gemini 4 Hydrogen · low | 9.0 (9-9) | 9.0 | 2/3 |
| Gemini 4 Hydrogen · medium | 8.7 (8-10) | 13.3 | 3/3 |
| Muse Spark 1.3 C · Go · low | 8.0 (8-8) | 8.7 | 3/3 |
| Muse Ember · CC · medium | 7.3 (7-8) | 8.2 | 3/3 |
| Muse Ember · CC · low | 7.0 (4-9) | 7.7 | 3/3 |
| Muse Spark 1.3 C · Go · minimal | 7.0 (6-8) | 9.0 | 3/3 |
| DeepSeek V4.1 Flash Fast · CC · low | 7.0 (7-7) | 15.0 | 3/3 |
| DeepSeek V4.1 Flash Ultrafast · CC · low | 6.7 (4-8) | 6.4 | 3/3 |
| DeepSeek V4.1 Flash Ultrafast · CC · off | 6.0 (4-8) | 4.3 | 3/3 |
| DeepSeek V4.1 Flash · Go · thinking off | 6.0 (2-8) | 9.0 | 3/3 |
| GLM 5.3 Flash · Go · minimal | 6.0 (4-8) | 10.8 | 3/3 |
| GLM 5.3 Flash · CC · low | 5.7 (3-8) | 13.0 | 3/3 |
| GLM 5.3 Flash · CC · medium | 5.7 (5-6) | 14.0 | 3/3 |
| DeepSeek V4.1 Flash · Go · low | 5.7 (4-7) | 22.2 | 1/3 |
| DeepSeek V4.1 Flash · CC · off | 5.3 (2-8) | 9.0 | 3/3 |
| DeepSeek V4.1 Flash · CC · low | 5.3 (1-8) | 18.0 | 3/3 |
| DeepSeek V4.1 Flash Fast · CC · off | 5.0 (1-7) | 6.0 | 3/3 |
| GLM 5.3 Flash · Go · none | 5.0 (4-6) | 12.7 | 3/3 |

Tutor (first speech, median of 5 runs; A = agree/correct case, B = draw-again case):

| Tutor route | A med s | B med s |
|---|---|---|
| Muse Spark 1.3 C · Go · minimal | 1.9 | 1.0 |
| GLM 5.3 Flash · Go · none | 1.2 | 4.0 |
| GLM 5.3 Flash · CC · low | 1.5 | 3.9 |
| Muse Ember · CC · low | 1.7 | 2.2 |
| DeepSeek V4.1 Flash Ultrafast · CC | 1.9 | 3.3 |
| DeepSeek V4.1 Flash Fast · CC | 3.0 | 3.9 |
| DeepSeek V4.1 Flash · Go | 3.8 | 4.2 |
| DeepSeek V4.1 Flash · CC | 4.1 | 6.5 |
| Gemini 4 Hydrogen · low | 5.4 | 4.8 (2 of 5 runs errored) |

What the numbers say: Gemini low still judges best on the page (9.0), but its tutor
turns were the slowest measured (5.4/4.8 s medians, B max 12.3 s with 2 errors) and one
of its three pages missed the 20 s budget. Muse Spark on Go judges 8.0 at low and 7.0
at minimal, delivers in 8-9 s, and answers as tutor in about 1-2 s with no errors --
the only setup that is fast and steady on both sides. The spread inside most configs
(e.g. Ember low 4-9, DeepSeek CC low 1-8) is larger than the gaps between their means:
three runs judge stability, not a winner.

**The automatic checks passed a page with an empty diagram.** Two pages judged 1/10
have an empty main panel -- only a coordinate statement, no visual explanation -- yet
shipped with clean lint (`issues: []`, no residual): P17 (DeepSeek Fast CC off, run 2,
6.2 s) and P31 (DeepSeek CC low, run 2, 14.1 s). A missing picture is not a lint kind
the shell reports, so the look pass had nothing to repair. Lint-clean is still not a
teaching guarantee; image-presence belongs on the checklist the next time the look
prompt or the shell issues change.

Decision (owner, 2026-11-14): **tutor Muse Spark minimal, page writer Muse Spark low,
both on Go; Command Code as backup for both (same model, different provider).** The
backup was verified separately with the real tutor prompt and tools (~1.7 s median to
first output, correct tool calls); the screen side relies on the same model answering
the same prompt, plus the failover smoke test in the PR. `TUTOR_LLM=cc` selects the
backup as the tutor route; `SCREEN_FALLBACK=cc` arms the screen backup (details below).
The Gemini page writer and the DeepSeek fox backup are retired by this decision.

### Command Code backup: tutor route `cc` and screen failover (2026-11-14)

Production runs one model family (Muse Spark 1.3 Contributor) on two providers: Go
primary, Command Code backup. Command Code serves the same Responses API
(`https://api.commandcode.ai/provider/v1`, key `COMMAND_CODE_API_KEY`, model
`meta/muse-spark-1.3-contributor`, `reasoning: {effort: minimal|low}`) and tolerates
Go's `x-opencode-session` header.

- **Tutor:** `cc` is a fourth `TUTOR_LLM`/`TUTOR_LLM_FALLBACK` route (see
  `server/README.md`). It reuses the Responses client; the warm-up race and the
  signature-safe failover in `session_llm.py` treat it like any other route.
- **Screen:** `SCREEN_FALLBACK=cc` (empty = off, today's behaviour) hedges a slow or
  failing primary with Command Code -- page, look and retry calls stream, and the
  first side to produce output text serves the whole call while the other is
  cancelled and its stream closed. The hedge fires at `SCREEN_HEDGE_AFTER_S`
  (default 5 s), capped so both attempts fit inside the calling step's own budget
  (a look/retry step's ~6 s deadline starts the hedge at ~3 s); no hedge starts
  with under 2 s left, and the 20 s job limit always holds. Empty
  `SCREEN_HEDGE_AFTER_S` keeps the older flat-timeout failover
  (`SCREEN_PRIMARY_TIMEOUT_S`). Only `cc` for Muse models is supported; anything
  else fails the job loudly at once, while a missing backup key disables the
  fallback with one warning and the primary serves alone.
- **Recorded per job:** `provider` (`go`/`google`/`cc` -- who wrote the delivered page
  or patch), `failover: true` with the `primary_error` class when a primary error
  fell over, plus `hedged` and the write call's `ttft_s`, in the page/patch
  `meta.json` and in the `screen_page`/`screen_patch` debug events (plus a
  `screen_failover` event when the backup serves after a primary error and a
  `screen_hedge` event for every raced call). Never a key.

### Hedged LLM requests, first-text measurement and warm connections (2026-11-14)

Providers sometimes spike mid-session: a request that normally starts in ~2 s can
take 25 s. The warm-up race only picks the session's starting route, so a later
spike hit every turn, and the flat screen failover only reacted after a 10 s timeout.
This change hedges both (PR: hedged tutor turns, hedged screen calls) with these rules:

- **Tutor:** each turn starts on the primary; past `TUTOR_LLM_HEDGE_AFTER_S`
  (default 2.5 s, `0`/empty off) the identical request races on the other route.
  First chunk wins, nothing is forwarded before the winner is decided, attempts
  stay within today's worst case, and hedging never touches thought-signature
  routes. A secondary that wins twice running becomes the primary (sticky,
  symmetric, logged as `llm_sticky_switch`); only a winner that serves its turn
  to the end counts, a failure or cancel resets the streak, and the loser's
  cancel/close runs in an owned reaper, without awaiting it on the winner's
  path. `aclose()` starts every remaining close together, including an active
  winner, and waits against one 2 s deadline. Survivors are cancelled and
  logged once per cleanup, with strong references retained until they finish.
  Every turn records `llm_turn`.
- **Screen:** page, look and retry calls stream (Responses and Chat both support
  `stream=True`), so the first output text is observable; the hedge above replaces
  the flat failover. Provider calls are async and cancellable with an absolute
  deadline. Cancellation requests provider shutdown and starts stream closure
  immediately; the reaper owns teardown that continues after the call ends.
  A provider that trickles bytes forever cannot hold a request thread, because
  screen requests use async streams.
  Optional steps pass their own remaining budget in, so the hedge fires at
  `min(SCREEN_HEDGE_AFTER_S, half the step)` instead of being cut by the outer
  timeout before the backup can start. Every attempt runs under the call's
  original absolute deadline, a caller cancellation always propagates instead of
  starting a backup, an already attempted route is never requested twice in one
  call, and every route's first-text time is measured from the call's start on
  one clock (the backup's time includes the hedge wait). Loser teardown never
  delays a ready page or caller cancellation. Screen shutdown starts every
  request and stream close before waiting on the same total 2 s reaper budget.
- **Measurement:** `tutor_session_ended` gains per-route turn wins with median/max
  ttft, hedge counts and sticky switches, and the same for screen calls; an optional
  per-turn `tutor_llm_turn` event carries only route names, timings and flags.
  Only turns served to completion count as wins: a partial-then-failed
  secondary is an attempt and an error for its route (`turns_errored` globally
  and per route), never a win. Fully off without `TUTOR_POSTHOG_KEY`, as before.
- **Warm connections:** one shared httpx transport per (process, loop, host) with
  ~120 s keep-alive for the tutor and screen clients -- an async transport is
  bound to its loop, so each loop owns its clients and they are closed at
  job/process shutdown (sharing one across loops raised `Event loop is closed`).
  Worker prewarm does a loop-independent sync warm-up per configured provider
  that reads response headers and closes without downloading the body. At the
  absolute ~5 s total deadline, it interrupts active socket I/O, closes the
  response/client and joins the worker within the remaining budget. It never
  fails worker startup; httpx inactivity timeouts alone cannot bound a trickling
  server. This targets the cold start seen 2026-11-14, when Go did not answer
  the 5 s warm-up right after a
  restart and was normal a minute later.

Review follow-up, 2026-11-14 (PR #65): removed sequential cleanup waits and every
unbounded post-cancel await in the hedge helpers. Six regressions retained or
extended from the review probes fail on `0e38597`: loser provider ownership,
active-winner closure, asynchronous cancellation teardown in tutor and screen,
and endless response bodies and headers during prewarm. The header test checks
that no warm-up thread remains when the deadline returns. The earlier
`turns_errored` fix, hedge timing and sticky-switch rules are unchanged.

Live follow-up on ThinkCentre, 2026-11-14, `hedge_smoke.py --parts ab`, one run
with fictional prompts: all three ordinary turns used Go without a hedge;
first-text times were 0.711/1.141/2.107 s and complete-turn walls were
1.5/1.2/2.4 s. With the primary stalled 10 s, Command Code served the turn at
3.801 s first text, including the 2.5 s hedge wait, and 10.1 s wall. That wall
includes the smoke's existing 6 s wait for an unstarted warm-up decision in
`SessionLLM.pick()`, before the provider turn begins; it is not loser cleanup.
These are diagnostic observations, not a provider speed comparison. Final server
verification: `cd server && uv run pytest -q`, 588 passed and 18 skipped. Web:
`cd web && npm test`, 125 passed. No running service was touched. Real screen
calls and a lesson with a child were not run.

Production keeps `SCREEN_FALLBACK` unset until this is proven on the dev setup;
`tutor` hedging only arms with `TUTOR_LLM_FALLBACK` set, as before.

### Race mode: both providers from the first millisecond (2026-11-14)

The 5 s screen trigger fired on every page: Go's first text takes 5.6–6.5 s, so the
backup was already being sent on every page, just 5 s late. Racing (`SCREEN_RACE`,
`TUTOR_LLM_RACE`, both off by default, switched on in production by the lead) sends
both requests from the start instead of waiting out the delay:

- **Tutor:** the secondary starts immediately (hedge delay 0); first chunk (text or
  tool call) still wins and the loser is cancelled exactly as today. Every turn gets
  min-of-two latency instead of paying up to 2.5 s before the backup even starts.
  `TUTOR_LLM_HEDGE_AFTER_S=0`/empty still means off: race needs a hedge target
  (never Gemini/thought-signature routes). The sticky switch-over is unchanged;
  with both sides always starting, two faster secondary turns still promote it,
  symmetrically back again, with no flapping beyond today's rule.
- **Screen:** both providers start at once on every model call kind (write, look,
  retry, image) and the first COMPLETED call wins, not first text. A provider that
  produces early text and then stalls mid-page loses to the one that finishes,
  so a trickling provider cannot hold a page past its budget. One side erroring keeps
  waiting for the other within the call's absolute deadline; both failing raises
  the primary's error, as today. The loser is cancelled and closed through the
  existing reaper path the moment the winner completes.
- **Stats:** `llm_turn` and the screen per-call notes gain `race: true`, the tutor
  records the loser's first-chunk time when it arrived before the cancel (both
  sides where available), the screen records the winner's total time and the
  loser's total/first-text time or error class when known. `tutor_session_ended`
  gains `llm_race_turns`/`screen_race_calls` counts. Counts and timings only, never
  text, so providers can be compared side by side from the same turns.

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

Geometry assessment (2026-11-13, proposal in PR #53): five Hydrogen-low pages and one
cuboid patch confirm existing graphs can draw measured plane figures, a cuboid and a
cylinder. The immediate defect is label placement: fixed offsets ignore text width,
and vertex-mean normals place some concave L labels inside the shape. Parent review
repeated the render measurements and corrected slanted-label clearance calculations.
Proposed order: label placement first, test brief reference guidance, then develop a
qualified plane-length lint; circle and angle primitives need a lead decision. No new
plane-figure component. Defer a solids tag on the two tested types, without ruling out
prism, pyramid, cone, sphere or nets (all untested). No runtime changes were made.
Sources, inspected phone/wide renders, timings and limits:
`screen/review/2026-11-13-geometry/`.

- Which model and reasoning level the screen runs on (measure with the examples in place).
- Image generation: whether, and with what.
- How the tutor is told a page is ready without interrupting its own sentence.

### Materials preview removed from elitebook (2026-11-18)

After PR #73, the materials preview services (`open-tutor-materials-web`/`-agent`), their env
file, the preview and ML virtualenvs, the Siyavula EPUBs and indexes (2.2 GB), the package cache,
and the Tailscale Serve entries (port 9443 and `/open-tutor-materials/`) were removed from elitebook.

### Picture requests go to the screen (2026-11-18)

A production test call showed the tutor answering "find a picture instead of the drawn map"
with `find_resources`/`share_resource` (Exa web search). The prompt (`server/open_tutor/prompt.py`)
and the resource tool descriptions (`agent.py`) now say: picture/photo/painting/real map/
illustration requests go to `ask_screen` with an explicit image ask, which the screen resolves
through Commons + Parallel search with vision review; `find_resources`/`share_resource` stay for
videos and readings. `screen/REFERENCE.md` tells the writer to put a requested real picture on
the page as `<ot-image query="...">` (e.g. `query="Swedish Empire 1658 map"`). Live check on
dell5500 dev (Go, Muse Spark minimal, fictional lesson): 3 picture asks over two runs each all
called `ask_screen`, the video ask called `find_resources` (8/8). One screen job on the same
ask emitted the `Swedish Empire 1658 map` slot and shipped an accepted Commons map
(`Swedish Empire 1658.jpg`, search latency 0.2 s) in 19.5 s. Caveat: three earlier same-budget
runs rejected two Commons flag-silhouette maps and starved the good candidate (Parallel prefetch
timeout, ~12 s image spend) -- more evidence for the review-concurrency follow-up.

### ot-map fits the highlighted marks (2026-11-18)

A production test call showed a realm map fitted to all of Europe: the page had written
an explicit `view="europa"` around an `<ot-area>` plus two `<ot-place>` markers. The shell
(`screen/shell/shell.js`) now widens mark-only fits smaller than 8° lon × 6° lat to that
regional minimum, so a single city gets a regional frame instead of a street-level zoom or
an empty sea; an explicit `view` still wins and the län map keeps its own fitting.
`screen/REFERENCE.md` tells the writer to leave `view` out when highlighting. Fictional
repro (realm + Stockholm + Riga, with/without view, single city) at 370×610 and 840×743
before/after, plus all nine example screens rendered with lint (zero diffs), are in
`screen/review/2026-11-18-map-fit/`. Review follow-up the same day: the padding
collapsed fits across the antimeridian onto Greenwich and capped near-pole fits at
±84°, dropping the marks (`place outside the map`) -- the fit now unwraps the shorter
arc and never cuts the marks themselves; a `later` place also no longer draws before
its reveal. Edge-case renders (date line, both poles, `later`) before/after are in
the same review directory; the nine examples still diff zero.

### Steady companion: the avatar no longer moves while the tutor talks (2026-11-19)

A real lesson on the middle band showed the companion avatar changing size and
position while the tutor talked. Two causes, both fixed on `t3/steady-companion`:

- Caption height varied. The desktop caption reserved only `min-height: 1.5em`
  for up to 2 lines, so a 1-line vs 2-line caption resized the image above it
  (measured: avatar `<img>` box moved up to 27 px between caption lengths at
  1280x800). The caption now keeps exactly 2 lines (`height: 3em`) and the
  state pill lives in an always-rendered `.ot-pill-row` (37 px, 30 px compact),
  so the `.ot-companion` box never depends on text. The phone caption
  (5/3/2 lines by layout state), the fox hero bubble (4 lines) and the strip
  bubble (3 lines) reserve their maxima the same way; empty bubbles stay
  transparent but keep their height.
- Pose canvases differed. Fox poses were 386-661 px wide, lynx 674-925,
  bear 708-891, so each pose painted at a different scale inside the same box
  (derived painted-character spread before: up to 114 px desktop, 348 px phone
  hero). `scripts/normalize_companion_poses.py` (Pillow, reproducible) crops
  each band's 7 poses to the character, scales them to the band's median
  character height (the fox's working pose was drawn ~1.6x larger than the
  others; padding alone would have shrunk the fox in six poses), and pads them
  bottom-centre onto one canvas (primary 486x571, middle 776x850, upper
  784x776), WebP quality 85 with alpha kept. Character height varies under 3 %
  within a band. Artwork sources under `design/` untouched.
  `server/tests/test_companion_canvas.py` fails if any pose drifts off its
  band canvas or character height again.
- Banners overlay instead of pushing. `.ot-banner` (desktop and phone) is now
  an absolute overlay stacked upward, so e.g. "Avslutar samtalet…" no longer
  shrinks the avatar column (before: main -52 px, image -37 px). Toasts and the
  sent chip already overlayed.

Measured with a Playwright harness (real stylesheets, real served images,
7 poses x 3 bands x caption lengths 0/1/2/long, pill present, 1280x800 and
390x844): avatar `<img>` box max variation before 27 px desktop / 63 px phone
hero (painted content up to 114/348 px), after 0 px everywhere within one
layout state; banner on/off moves nothing after. Caveat: the harness replays
the layout outside a live session (no LiveKit) with Linux font metrics, and
the painted-content numbers are derived geometrically -- direction and scale
are representative, not device-exact. Not tested: a real lesson with children.
