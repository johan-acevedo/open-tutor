# Milestone A: what actually ran

Recorded 2026-11-04 against LiveKit Cloud (Germany region), with **fictional material only**. The first runs used a worker and web service on dell5500. The same browser test then passed against the family deployment described below.

## Model route

**Current (from 2026-11-04 afternoon): Muse Spark 1.3 Contributor on Johan's OpenCode Go subscription** (`TUTOR_LLM=go`, `muse-spark-1.3-contributor`, Responses API at `https://opencode.ai/inference/go/openai/v1`, HTTP streaming, reasoning `minimal`). What was tested, and the route's limits, are in [server/README.md](../server/README.md#the-opencode-go-route). In short: streaming, structured tool calls, tool results and image input work. The Responses WebSocket does not (404). Go's documentation says Contributor prompts and completions are used to train Meta models.

The runs in the two tables below were made earlier the same day on the development route `TUTOR_LLM=gemini-dev` (Gemini 3.5 Flash Lite through Google's OpenAI-compatible endpoint). No OpenRouter route or credit is needed any more; that route has been removed.

## Headless learner probe (`server/scripts/live_probe.py`)

A scripted learner joins a real room. It speaks recorded Swedish clips generated with Gemini TTS, shares a generated worksheet image, and answers board RPCs.

| Check | Result (run 2) |
|---|---|
| Tutor speaks first | Greeting audio 5.6 s after joining (cold worker process) |
| Homework image understood | "Jag ser tre uppgifter om ekvationer här. Vill vi börja med uppgift 3?" |
| Board before speech | `board.show` (steps) at 53.4 s and `board.focus` at 54.6 s were acknowledged before speaking started at 56.0 s |
| Interruption | Tutor left the speaking state 1.84 s after the interrupting clip began. That includes the clip's leading silence and endpointing |
| 30 s quiet work | 0.0 s of tutor speech after one encouraging sentence; `tutor.mode` = `quiet` |
| Mumbling during quiet work | 0.0 s of tutor speech (model called `stay_quiet`) |
| End of session | Note saved (topic, what clicked, what is tricky, next step), then a one-sentence goodbye |

## Real browser (Playwright Chromium, fake microphone)

The built page was served by the FastAPI service. Checked at 1366×768 and 900×700:

- New profile → Starta → greeting with word-synchronised caption and the "Pratar" pill.
- Worksheet upload → paper card on the board → tutor describes it.
- Typed request → steps item with KaTeX, op chips and highlighted row, layout switched to 74/26.
- Quiet work → "Jag väntar", waiting pose, no bars.
- Avsluta → goodbye, end card, note persisted in IndexedDB.
- Returning learner → "Förra gången: Ekvationer" chip; spoken greeting referred to last session.
- Two-page PDF rendered with PDF.js and both pages understood; pasted text acknowledged; resource request → Exa search → YouTube embed, "Väntar medan du tittar", "Klar – prata vidare" → follow-up question.
- Microphone denied → amber banner, typing works.

## Family deployment

- `https://tutor.labtopia.dev`: a proxied CNAME and an ingress rule on the Mini's `labtopia-mini` Cloudflare tunnel, routed to the web service on ThinkCentre at its tailnet address, port 8710.
- ThinkCentre runs `open-tutor-web` and `open-tutor-agent` as user services (`deploy/install.sh`, lingering on, no root). Secrets are in `~/.config/open-tutor/env` (mode 600).
- `TUTOR_ACCESS_CODE` is set. Without it `/api/session` returns 401. Share the page as `https://tutor.labtopia.dev/?kod=<code>`. Johan's copy of the code is in `$HOMELAB_SECRETS/open-tutor-family-code.txt` on dell5500. The cap is 12 sessions per hour.
- After the change, labtopia.dev, farm and art still answered 200, 200 and 401. Rollback: the tunnel backup path that `cf tunnel-put` printed (20261104-095418), and delete the `tutor` CNAME.
- The deployment runs `TUTOR_LLM=go` (checked in the running worker's environment, and per session in its log: `tutor LLM route go model muse-spark-1.3-contributor api responses`). The Go key is in the private env file, not in Infisical: no OpenCode key exists in the `homelab` project.

## Second-session bug: tool calls in the voice, blank board (fixed)

Johan's second family session spoke tool-call text and showed nothing on the board. The first had worked.

**Cause.** The deployed Gemini route often returned no structured function call. Instead it wrote the call, or the board content, into its reply. Real examples with fictional prompts: ``*(Anropar `show_steps` för att visa ekvationen och dess steg.)*``, ``*(Note: … Let's use `show_steps`.)*``, a LaTeX `aligned` block, or "jag skriver upp den på tavlan" with no call. Without a call there is no `board.show` RPC, and the production log for that session has none, not even a failure. The worker passed every reply word to the voice, the caption and the stored chat history. It was random per turn: on a first board request Gemini called the tool in 11 of 18 tries at best and 1 of 6 at worst. A good first session followed by a bad second one is chance, not leftover state. Nothing carries between sessions except the saved note: each session is a new room, worker process, model client and set of board ids.

**Fix.**
1. Model route: Muse Spark on Go. Its calls arrive as structured `function_call` items. On first board requests it called the board tool 24 of 24 times.
2. Adapter: Go omits `usage.cache_write_tokens`, which made LiveKit 1.8.10 fail at the end of every turn. That field is now filled in.
3. Speech boundary: narrated calls, code, JSON, call syntax and bracket notes are removed before the voice and the caption. The caption is also what LiveKit stores as history, so a narrated call can no longer teach the model to narrate again. LaTeX environments are said as maths. Short answers such as "Ja." and ordinary words pass unchanged.
4. Prompt: the board changes only through a tool call, and tool calls are never narrated.
5. Logs: tool names and board acknowledgements are logged, never arguments.

**Evidence (fictional material, typed requests, no microphone speech).**

- Unit tests replay a recorded Go stream through the adapter, use the real narrated-call replies, and check board RPC dispatch, acknowledgement and fresh-session state.
- `server/scripts/two_session_probe.py` ran against a test worker on Go under a separate dispatch name, in two runs. In each session, `board.show` and `board.focus` were acknowledged before the tutor talked about the board, no caption contained tool text, a note was saved, and the second session's board held only its own equation.
- Real browser (Playwright Chromium, silent fake microphone) through `https://tutor.labtopia.dev`, same profile twice. Session 1: steps for 3x + 5 = 20, focus, goodbye, end card. Session 2: the "Förra gången" note and greeting, a fresh steps card for 2x − 4 = 10 only, focus, end card with the new note. 131 caption updates contained no tool names, JSON or markup. The worker log showed `board rpc board.show b1 acknowledged=True` in both rooms.
- The browser stopped waiting 8 s after Avsluta, which cut the second goodbye off. It now waits up to 25 s; the tutor still ends the room itself.

## Session stall on an empty tool call (fixed, not yet deployed)

During a real family session on 2026-11-06 the tutor stopped responding mid-session and the page sat silent. The next session worked normally.

**Cause.** Go emitted a `show_text` call with empty arguments. The tool runner reads that as `{}` (the model got a useful argument error: `title` and `markdown` required), but the empty string stayed in the retained history. Go rejects every follow-up request carrying it with a 400 for invalid `arguments` (not retryable). Four consecutive rejections (09:29:59-09:30:28) closed the AgentSession, and a later `session.interrupt()` crashed the job with `RuntimeError: AgentSession isn't running`, so the room was never deleted and the browser never left the dead room. First wrong state was the empty upstream call: the plugin passes arguments through verbatim, and there were no interruption or truncation markers in the log.

**Fix.**
1. `tutor_llm.py` heals retained history before each request: empty arguments become `"{}"`, other non-JSON arguments go through the framework's own repair, valid JSON is left byte-identical, and anything even the repair cannot parse is left untouched (still loud, never fabricated). The tool's error output stays, so the model still self-corrects.
2. `agent.py` tolerates `interrupt()` on a closed session, wakes when the session closes unexpectedly, skips the goodbye that could never play, and still deletes the room - so the browser shows its disconnected notice with a restart button instead of silence. No client change was needed.

**Evidence.** Unit tests replay the synthetic failure (empty-arguments call plus its error) through the real adapter and serializer: the wire history carries `"{}"`, the error output is preserved, valid calls are byte-identical, and a streamed `show_steps` call still validates against the board. A minimal live probe with fictional material confirmed the provider behaviour: replaying empty arguments returns the exact 400 from the incident, replaying `"{}"` returns 200. Not verified: a full live family session after the fix (no public sessions were started; the next real session is the proof).

## Not yet verified

- Spark on Go with real speech: the checks above typed their requests. The interruption, quiet-work and mumbling results in the first table are from the Gemini route and have not been re-run on Go. Listening quality of the Swedish voice. The runs used the ElevenLabs default voice with `eleven_flash_v2_5`; Johan should choose from the recorded samples.
- Real microphone, echo, and children's speech, pauses and thinking aloud. Turn-taking tuning needs real sessions.
- Windows and Chromebook hardware, school network restrictions, the HTTPS URL and reconnect behaviour (milestone C).
- Generated images (`pending` → `image`) are in the protocol but have no tool yet.
- Character poses are cut from the mockup PNGs pending a proper asset pass.
