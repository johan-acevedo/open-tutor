# Technical evidence for the first build recommendation

Checked 2026-11-03. This is a source and implementation inspection, not an end-to-end test. No live inference, machine deployment, DNS change, provider setting change or spend measurement took place.

## Repository inspection

| Repository and revision | What was inspected | What it supports |
|---|---|---|
| [`johan-acevedo/t3-call` at `1cf96de`](https://github.com/johan-acevedo/t3-call/tree/1cf96de26b3c18e8e69697f9d31e061d72bdd4c4) | `LICENSE`, `README.md`, `pyproject.toml`, `src/t3_call/llm.py`, `stage_site.py`, `stage_renderer.py`, `speech_clock.py` | MIT code; Python LiveKit speech plugins; configurable LLM endpoint; isolated visual-stage work; real acoustic timing infrastructure. Does not prove tutoring or Swedish quality. |
| [`zicojiao/ai-math-tutor` at `2d87f0c`](https://github.com/zicojiao/ai-math-tutor/tree/2d87f0cd30dec5e2c552aafccb121161906bea8c) | `LICENSE`, `apps/agent/src/pipeline.ts`, `apps/web/lib/math-tutor/canvas-protocol.ts`, repository structure | MIT code; concrete voice pipeline and board action schemas, homework context and turn states. Defaults include an English TTS configuration; it is not a verified Swedish implementation. |
| [`Abem-S/tablo-ai` at `e82a566`](https://github.com/Abem-S/tablo-ai/tree/e82a566cc7279141d552c223921f0647edbbafd4) | `LICENSE`, `backend/requirements.txt`, backend file inventory and agent/integration references | AGPL-3.0; Python LiveKit/Gemini components alongside retrieval, memory and vector-store infrastructure. More code exists than its README alone establishes, but no runtime verification was performed. |

The two external repositories were cloned into temporary research directories. Their code was not copied into this project. `t3-call` already existed locally and was read without modification.

## Current primary documentation

- [LiveKit voice-agent quickstart](https://docs.livekit.io/agents/start/voice-ai/): supports the proposed framework role. This phase did not start an agent.
- [LiveKit media and data](https://docs.livekit.io/frontends/build/media-data/): audio, text/byte streams, RPC and state exchange can connect speech and board actions.
- [LiveKit tools](https://docs.livekit.io/agents/logic/tools/): tools may do background work while conversation continues.
- [LiveKit OpenAI-compatible integration](https://docs.livekit.io/agents/models/llm/openai/): configurable model endpoints, with a WebSocket default for Responses mode. An HTTP endpoint does not by itself verify that mode.
- [LiveKit turn detector](https://docs.livekit.io/agents/logic/turns/turn-detector/): Swedish is absent from the current documented semantic-detector language lists.
- [Soniox languages](https://docs.soniox.com/stt/concepts/supported-languages): Swedish is listed for streaming and recorded transcription.
- [LiveKit Soniox](https://docs.livekit.io/agents/models/stt/soniox/) and [ElevenLabs](https://docs.livekit.io/agents/models/tts/elevenlabs/): plugins exist. This is integration availability, not a voice-quality ranking.
- [OpenCode Go](https://opencode.ai/v2/docs/console/go/): current intended traffic is coding-agent requests; Muse Spark Contributor is listed with training use and regional conditions. Tutoring use has not been confirmed. This changes the confidence of the original subscription assumption, without requiring a different product design.
- [tldraw licensing](https://tldraw.dev/community/license): production requires an active trial, commercial or discretionary hobby licence key. The MIT status of a template does not establish that its SDK is MIT.
- [Vite](https://vite.dev/guide/), [FastAPI static files](https://fastapi.tiangolo.com/tutorial/static-files/), [PDF.js](https://mozilla.github.io/pdf.js/), [KaTeX](https://katex.org/docs/browser.html): official references for the proposed browser build, static serving, PDFs and equation rendering.

No current per-minute price or measured latency is asserted. Select exact media models and verify their release dates when building the integration, rather than freezing an untested choice in the founding documents.

## Environment checks

The Infisical CLI successfully listed the `homelab` project. A subprocess retrieved development secrets in memory and printed only names, never values. Relevant names include `SONIOX_API_KEY`, `ELEVENLABS_API_KEY`, `CARTESIA_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `EXA_API_KEY` and `FAL_KEY`. These names establish provisioning candidates only. Balances, key validity and provider quotas remain unchecked.

No `LIVEKIT_*` or OpenCode key names appeared in that inspected development environment. This does not establish that they are absent from other environments or existing service configuration. Do not publish the full secret inventory or environment identifiers.

The home-lab inventory describes ThinkCentre as a CPU host with always-on intent. The operations handbook documents the Mini's Cloudflare tunnel and tailnet service routing. Neither current host availability nor a proposed tutor hostname was tested in this phase.

## Scope of the review package

The package preserves the agreed PRD, style guide and selected second-pass PNGs. Some intermediate renders and the original greeting remain as reference inputs for the saved generation prompts. The larger first-pass gallery, competitor report and coaching report remain local working material.

Presentation verification covers actual rendering, navigation, linked images and printable pages. It must not be mistaken for proof that the tutor application works: there is no application implementation yet.
