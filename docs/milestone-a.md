# Milestone A: what actually ran

Recorded 2026-11-04 against LiveKit Cloud (Germany region), with **fictional material only**. The first runs used a worker and web service on dell5500. The same browser test then passed against the family deployment described below.

## Model route used for these runs

The intended tutor model is Muse Spark 1.3 through an ordinary metered API (`TUTOR_LLM=spark`: `meta/muse-spark-1.3` on OpenRouter, not the Contributor or OpenCode Go coding route). The `homelab` OpenRouter key is valid but the account has never bought credits, so every Spark request returned HTTP 402. To exercise the pipeline, these runs used the explicit development route `TUTOR_LLM=gemini-dev` (Gemini 3.5 Flash Lite, July 2026, through Google's OpenAI-compatible endpoint), paid from the authorised Google credit. The route is chosen by configuration and has no silent fallback. **Spark streaming, tool calling and image input through this code path are not yet verified.** A direct probe without credit could not reach the model.

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
- The deployment runs `TUTOR_LLM=gemini-dev`, so it is **for fictional material until the Spark route has credit**.

## Not yet verified

- Spark as the tutor model (see above). Listening quality of the Swedish voice. The runs used the ElevenLabs default voice with `eleven_flash_v2_5`; Johan should choose from the recorded samples.
- Real microphone, echo, and children's speech, pauses and thinking aloud. Turn-taking tuning needs real sessions.
- Windows and Chromebook hardware, school network restrictions, the HTTPS URL and reconnect behaviour (milestone C).
- Generated images (`pending` → `image`) are in the protocol but have no tool yet.
- Character poses are cut from the mockup PNGs pending a proper asset pass.
