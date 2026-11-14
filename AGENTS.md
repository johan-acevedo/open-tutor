# Working in this repository

For any agent (or person) picking up work here. Read this first, then the document for the
area you are touching. Keep this file short: it points to where the detail lives.

## What this is

Open Tutor is a live voice tutor for Swedish school children, used by real children (the
owner's own, aged 9 to 15, and a small public test in Sweden). The child talks with "Räven",
a fox, in the browser. Next to the fox is the Smart Screen: pages the tutor orders from a
second model while it keeps talking. `README.md` holds the founding brief and `PRD.md` the
product requirements.

The product speaks Swedish. Code, comments, docs, commits and PRs are in English.

## Map

| Path | What |
|---|---|
| `web/` | The page: React, TypeScript, Vite, `livekit-client`. Phone and desktop layouts. |
| `server/open_tutor/` | Python. `agent.py` is the LiveKit Agents voice worker (the fox); `web.py` is the FastAPI service that serves the page and `/api/session`. |
| `server/open_tutor/screen.py` | The Smart Screen on the server: page writer, render, checks, bounded retry. |
| `screen/` | The Smart Screen shell (`shell/`), what the page writer reads (`REFERENCE.md`), examples, tools and review evidence. |
| `server/scripts/` | Probes that run real sessions against a running worker. |
| `deploy/` | User services and `install.sh` for a hosted instance. |
| `tools/`, `docs/material-library/` | Curriculum and textbook tools; the material library. |
| `review/`, `design/`, `BUILD-PLAN.md` | Early planning and design records. CI rebuilds `review/`. |

Where the detail lives:

- `docs/smart-screen.md`: the Smart Screen state file. Decisions, measurements, what real
  test calls settled, open questions. The lead keeps it current; read it before screen or
  tutor work and report against it.
- `server/README.md`: running locally, every setting (`TUTOR_*`, `SCREEN_*`), model routes,
  voice, noise filter, the session debug log, tests and probes.
- `screen/README.md`, `screen/NOTES.md`, `screen/REFERENCE.md`: the shell, why it is built
  as it is, and the page writer's reference.
- `docs/protocol.md`: messages between page and worker.
- `deploy/README.md`: hosting an instance.

## How a call works

1. The page asks `/api/session` for a LiveKit room and joins it. Audio goes directly between
   the browser and LiveKit Cloud.
2. The worker joins as the fox: speech recognition, a tutor model, speech synthesis. Each
   provider is a setting; the tutor model is chosen per session by a warm-up, with a fallback.
3. The fox has tools: `ask_screen` (order a page or a change), `show_page`, `reveal`, `point`,
   plus notes and resources. `ask_screen` returns at once; the page arrives later as an event.
4. The page writer writes an HTML body with `ot-*` components. The server renders it in the
   shell, checks it, and sends it to the browser, where it runs in a sandboxed frame.

Rules that the design depends on:

- **The tutor is never blocked.** Nothing the fox calls may make the child wait in silence.
- **The fox teaches from what was actually rendered**, not from what it asked for.
- **Model output is untrusted.** Page bodies and patches go through the shell's sanitizer.
- **Latency is the product.** Measure time to first speech and time to page before and after
  a change that could move them.

## Run and test

```bash
# server
cd server && uv sync --python 3.12
uv run pytest -q                                   # full suite
uv run pytest -q tests/test_screen.py              # one module while iterating
bin/with-env uv run python -m open_tutor.agent dev          # worker
bin/with-env uv run uvicorn open_tutor.web:app --port 8710  # web service

# web
cd web && npm ci
npm run typecheck && npm test && npm run build
```

`bin/with-env` loads the private env file (see `server/README.md`). CI runs the server
suite, the web typecheck, tests and build, the `review/` build, and the material tools on
every pull request.

Unit tests and green CI are supporting evidence. Before saying a change to the call works,
run a real session against a running worker:

```bash
uv run --project server python server/scripts/smart_screen_e2e.py --url <https url> --shots-dir <dir>
```

It drives a typed session in a browser and saves screenshots and a timeline. It does not
cover speech, the microphone, or a real phone; say so when that is what changed. For
screen-only work, `screen/tools/` has render and check tools (see `screen/README.md`).

## Reading what happened in a call

With `TUTOR_DEBUG_LOG=1` the worker writes one private directory per session outside git
(`events.jsonl`, `report.json`; see "Family-testing debug trail" in `server/README.md`).
This is the first place to look for any report of "it was slow" or "it did not answer".

These logs hold what children said. They stay on the machine. Do not copy transcript text
into the repository, PRs, issues or messages to other services; report counts and timings.

## Working rules

- **This repository is public.** No secrets, no private addresses or contact details, no
  real child's words, names or schoolwork. Test learners are fictional ("Testbarn").
- **Secrets** come from the host's private env file or secret store. Never print or log one.
- **`main` is the trunk.** Branch from it, open a pull request, merge when the diff is
  reviewed and CI is green. A reviewer should be a different model family than the author.
- **Hosted instances run from a checkout as user services.** Changing code does not change a
  running service; a restart does. Never restart a service while a call is running, and
  never stop processes by name pattern (`pkill`, `killall`): that has taken the shared
  worker down twice. Use the service's own unit.
- **One worker per agent name.** A second worker registered under a live instance's name
  takes some of its calls. Use your own `TUTOR_AGENT_NAME`, ports and debug directory for
  experiments.
- **The public instance is visible to others.** Deploying to it needs the owner's go each
  time. A development instance is where changes are tried first.
- **Real providers cost money.** Probes that use live models are not part of CI; run the
  narrowest one that proves the change.
- **Record what was learned.** A decision, a measurement or a dead end goes into the state
  file or the area's notes in the same pull request, with the date. Say what was not tested.
- **Things already tried and rejected** are listed in `docs/smart-screen.md` (for example
  filler sounds while the fox thinks). Check before proposing them again.

## Handing off

Name the branch and commit, what is on `main`, where it runs, what you verified on the real
thing, and what you did not.
