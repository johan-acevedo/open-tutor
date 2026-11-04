# From the founding brief to the first homework session

Status: technical recommendation for Johan's review, 2026-11-03. No application, provider experiment, or deployment has been built in this phase.

Read the [PRD](PRD.md) for the intended behaviour, the [style guide](design/STYLE-GUIDE.md) for presentation, and the [technical evidence](docs/technical-evidence.md) for source checks. The [review presentation](review/board-meeting.html) explains the recommendation without requiring technical knowledge.

## Recommendation

Build a small application around LiveKit. Reuse selected voice and visual-stage patterns from Johan's MIT-licensed `t3-call` project. Use the public tutor repositories as references rather than adopting their whole applications.

The first child opens an HTTPS URL in Chrome or Edge on Windows, chooses a local profile, and talks to the tutor. The computer needs no developer tools, provider accounts, or installation. Check the same experience on a school Chromebook, including its microphone and network restrictions.

## Proposed stack

| Responsibility | Choice | Why it fits this first version |
|---|---|---|
| Browser page | React, TypeScript, Vite, ordinary CSS | Build the approved layout and fixed controls without adding server-rendering or account infrastructure. |
| Call transport | LiveKit Cloud, browser SDK and React components | Managed browser audio, connection state, captions, and data exchange. Keep room hosting separate from AI-provider billing. |
| Tutor runtime | Python, LiveKit Agents | Reuse familiar speech integrations and asynchronous stage work from `t3-call`. Call providers directly, without launching a coding harness for each turn. |
| Small web service | FastAPI | Serve the built page, issue room tokens, receive homework, and start the agent. Run it alongside the worker as persistent user services. |
| Teaching board | HTML, SVG, KaTeX, and isolated generated HTML/JS panels | The tutor owns the board initially. Render equations and diagrams precisely, while allowing richer illustrations and animations. |
| Homework | PDF.js, image previews, pasted text and screenshots | Start with PDF, PNG and JPEG. Preserve page images and page numbers for the tutor. Other office formats can follow actual demand. |
| Learner continuity | IndexedDB in the browser | Store names, school years and short learning notes. Start with an empty board on the next visit. No central learner database initially. |
| Initial hosting | ThinkCentre for the web service and worker; existing Mini/Cloudflare tunnel for HTTPS | Use existing CPU machines and internet routing. Cloud providers perform inference; no GPU requirement. Confirm host availability before deployment. |

These are recommendations, not installed dependencies. Pin versions during implementation using the then-current SDK examples. [Vite](https://vite.dev/guide/), [FastAPI static files](https://fastapi.tiangolo.com/tutorial/static-files/), [PDF.js](https://mozilla.github.io/pdf.js/), and [KaTeX](https://katex.org/docs/browser.html) support the proposed roles.

## Reuse useful work without inheriting an entire product

`t3-call` is the best source for selected Python speech integration, call-state handling, asynchronous visual work, and latency instrumentation. Its T3 thread access, task approvals, coding harness, and saved-call product are unrelated to this tutor and should stay out. Preserve notices when copying MIT code.

`zicojiao/ai-math-tutor` has concrete LiveKit-to-board messages, homework-image context, and turn-state handling worth learning from. Its editable tldraw canvas and maths-specific workflow differ from this product. `Abem-S/tablo-ai` offers useful memory and multimodal ideas, but its AGPL code and larger retrieval stack would shape the project more than needed.

Choose our own tutor-controlled board. A full canvas editor adds interaction work we have deliberately deferred. The tldraw SDK also requires a production licence key, including discretionary hobby licences. This is a dependency choice, not a judgement about either project's educational quality. [tldraw licensing](https://tldraw.dev/community/license)

## Provider proposal and the LLM route

Start the integration experiment with Soniox streaming transcription and ElevenLabs streaming speech. Both have key names present in `homelab` development and existing integrations in `t3-call`. Swedish support is documented for Soniox. Choose the actual voice and model configurations by listening and testing; their quality and latency here are not yet established. Cartesia and other already available providers remain alternatives if the first combination disappoints. [Soniox languages](https://docs.soniox.com/stt/concepts/supported-languages), [LiveKit Soniox integration](https://docs.livekit.io/agents/models/stt/soniox/), [ElevenLabs integration](https://docs.livekit.io/agents/models/tts/elevenlabs/)

Johan chose Muse Spark 1.3 Contributor through his OpenCode Go subscription as the tutor model (decision of 2026-11-04, replacing the metered OpenRouter route). The app identifies itself truthfully to Go (`User-Agent: open-tutor/…`, one `x-opencode-session` per room). Go's documentation lists training use and regional limits for Contributor models; see [server/README.md](server/README.md#the-opencode-go-route). [OpenCode Go](https://opencode.ai/docs/go/)

Wire compatibility was tested: Go's Responses endpoint works over HTTP streaming with structured function calls and image input, and its Responses WebSocket answers 404, so the worker uses LiveKit's Responses plugin with `use_websocket=False` and a small usage-field fix. Native image understanding works, so no separate vision helper is needed. [LiveKit LLM integration](https://docs.livekit.io/agents/models/llm/openai/)

Use Exa for the initial resource-search tool. Give the tutor returned links and metadata to choose from, with no resource approval system. Existing `t3-call` search code is a reference. Generated images use the available cloud providers asynchronously when useful; select exact media models when implementing that tool.

## How a session fits together

1. The browser loads a local learner profile and requests a short-lived call token from our service.
2. LiveKit connects the child's microphone to the tutor worker and carries the tutor's audio back. The worker calls speech and LLM APIs using backend credentials.
3. The browser shares only the homework or text the child supplies. The worker keeps the original pages available for follow-up questions.
4. Tutor tools publish board updates and resource cards to the browser. A browser acknowledgement tells the tutor when a visual is ready to discuss. Slow media work runs separately from the immediate reply.
5. The tutor periodically sends a small learning note back to the browser, and updates it on session end. Earlier notes survive closing the tab; an abrupt close may lose the latest unsent note.

LiveKit provides data, RPC, agent states and background tool work for these responsibilities. Generated board content runs separately from the fixed page controls and has no access to provider credentials or learner storage. The tutor receives explicit board context rather than general screen surveillance. [Media and data](https://docs.livekit.io/frontends/build/media-data/), [background tools](https://docs.livekit.io/agents/logic/tools/)

Use clear conversation states: talking together, quiet work, viewing a resource, and ending. These guide the tutor's initiative and interruptions. A quiet interval keeps the call available. A video must not become a new conversation participant. For an external resource tab, offer a clear return/resume action because we cannot reliably observe its playback.

Use speech-provider endpointing and voice-activity detection as the initial Swedish turn-taking approach. Do not assume LiveKit's multilingual semantic detector covers Swedish; the current documented language lists omit it. Tune on pauses, corrections, and thinking aloud in the next experiment. [Turn detection](https://docs.livekit.io/agents/logic/turns/turn-detector/)

## Hosting and credentials

Propose `tutor.labtopia.dev` as the first URL, subject to a DNS check during deployment. The existing Mini tunnel can route HTTPS to the service on ThinkCentre over the tailnet. Browser audio goes directly through LiveKit, rather than through that HTTP tunnel. ThinkCentre's inventory records always-on intent, but we have not probed its current state or deployed anything.

Inject credentials from Infisical into the backend processes. The inspected `homelab` development environment contains speech, search, vision and image-provider key names. Their validity, balances and API access were not tested. No `LIVEKIT_*` or OpenCode key names appeared in that inspected environment (rechecked on 2026-11-04 across all `homelab` environments and folders: still no OpenCode key); the deployment's private env file holds them. Do not expose keys to the browser or commit environment exports.

Hosting one family's sessions and opening a demo to the public are separate operational steps. Start with family use. Before opening it more broadly, set an owner-controlled spending and concurrency limit. That need not add learner accounts. Track actual usage before estimating a per-session cost; this phase makes no cost or latency promise.

## What happens after this review

| Milestone | Concrete result | What we learn |
|---|---|---|
| A. Integration experiment | Swedish voice, one real homework page, interruption, quiet work, and a board update in one session | Whether the chosen provider route and coordination work. Fictional material only. |
| B. Complete workspace | Approved character poses, local profiles, homework intake, visual teaching, links and saved notes | Whether all parts work as one experience rather than isolated demonstrations. |
| C. Browser-ready hosting | HTTPS URL, persistent services, reconnect/error handling, Windows and Chromebook checks | Whether the child can arrive and use it without technical help. |
| D. First weekday session | The child brings actual schoolwork; Johan observes | What helps learning and which friction to fix next. |

This phase delivers the foundation and technical proposal only. The next step is milestone A, followed by a complete workspace. No dates are promised before the integration uncertainties are resolved.

## Decisions for review

The recommended direction is a new small app, selective MIT reuse, a tutor-controlled web board, Python voice worker, and existing home-lab hosting with managed LiveKit transport. The LLM route is Muse Spark on OpenCode Go (see above). Exact Swedish voice choice belongs to the integration experiment.

An MIT project licence is a reasonable proposal for easy reuse, but remains unselected here. No licence was added and no AGPL source was copied. The PRD and visual direction can be reviewed independently of these technical recommendations.
