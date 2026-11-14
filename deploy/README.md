# Hosting one family's instance

The web service and the voice worker run as **user** services (no root). Browser audio goes directly to LiveKit Cloud; only the page and `/api/session` need HTTPS.

1. Clone the repository to `~/code/open-tutor` and write `~/.config/open-tutor/env` (mode 600) with the variables in [server/README.md](../server/README.md). Set `TUTOR_ACCESS_CODE` for anything reachable from the internet.
2. Optional: `~/.config/open-tutor/bind.env` with `TUTOR_BIND=<address>` if the HTTPS proxy runs on another machine (for example a tailnet address).
3. `deploy/install.sh` builds the page, installs `open-tutor-web` and `open-tutor-agent`, and checks `/api/health`. User services keep running after logout only with lingering enabled (`loginctl show-user $USER -p Linger`).
4. Route an HTTPS hostname to the web service (Johan's instance: a Cloudflare tunnel on the Mini, see the home-lab ops handbook). Microphones only work on HTTPS pages.

Share the page as `https://<host>/?kod=<family code>`. The browser remembers the code. `TUTOR_MAX_SESSIONS_PER_HOUR` caps new sessions for the whole instance.

Only one worker should register as `open-tutor` per LiveKit project. A second (for example a developer's `dev` worker) would take some of the sessions.

## Product analytics (PostHog, EU cloud)

Off until configured: without a key the page loads no analytics SDK and the
worker sends nothing. To enable, add to `~/.config/open-tutor/env` (same file
as the other secrets) and restart both services:

```bash
TUTOR_POSTHOG_KEY=phc_…
# TUTOR_POSTHOG_HOST=https://eu.i.posthog.com   # default, normally unset
systemctl --user restart open-tutor-web open-tutor-agent
```

What is counted: one `tutor_session_started` and one `tutor_session_ended`
event per session (room, grade, turns, tool and error counts), plus page-side
funnel events (`page_opened`, `access_code_result`, `session_started`, …).
Person profiles are identified only (`device id + learner name`); conversation
text, typed text, homework content and images never leave the session, and
session outcomes are fixed categories (error events carry only the exception
class name, never its message). With no
key, `/api/config` returns `{"posthog": null}` and every analytics helper is
a no-op.

## Isolated material-library preview

`deploy/materials-preview.sh` installs separate user services and a separate HTTPS port on the current machine. It requires a private `~/.config/open-tutor-materials/env` file (0600) with the existing provider credentials and `TUTOR_AGENT_NAME=open-tutor-materials-preview`; it refuses the normal family dispatch name. The launcher builds this checkout, synchronizes a separate ML-enabled virtualenv, downloads speech/VAD assets, and restarts only `open-tutor-materials-web` and `open-tutor-materials-agent`.

The preview web process listens on 127.0.0.1:8720 with one worker. Tailscale Serve exposes HTTPS port9443 without replacing existing routes. The elitebook instance is https://elitebook.tail2e1c4e.ts.net:9443/. The credentials and index live outside Git. Configure `TUTOR_MATERIAL_INDEX` explicitly; the initial preview uses the evaluation subset until the full library index is reviewed. Service updates require a restart; changing code in the checkout alone does not update a running process.

Inspect services with `systemctl --user status open-tutor-materials-web open-tutor-materials-agent`. Stop them with `systemctl --user stop open-tutor-materials-web open-tutor-materials-agent`; remove only this Serve port with `tailscale serve --https=9443 off`.
