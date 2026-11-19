# Hosting one family's instance

The web service and the voice worker run as **user** services (no root). Browser audio goes directly to LiveKit Cloud; only the page and `/api/session` need HTTPS.

1. Clone the repository to `~/code/open-tutor` and write `~/.config/open-tutor/env` (mode 600) with the variables in [server/README.md](../server/README.md). For a public instance, `TUTOR_ALLOWED_COUNTRIES=SE` admits Swedish visitors without a code; there is no code gate any more.
2. Optional: `~/.config/open-tutor/bind.env` with `TUTOR_BIND=<address>` if the HTTPS proxy runs on another machine (for example a tailnet address).
3. `deploy/install.sh` builds the page, installs `open-tutor-web` and `open-tutor-agent`, and checks `/api/health`. User services keep running after logout only with lingering enabled (`loginctl show-user $USER -p Linger`).
4. Route an HTTPS hostname to the web service (Johan's instance: a Cloudflare tunnel on the Mini, see the home-lab ops handbook). Microphones only work on HTTPS pages.

Share the page as `https://<host>`. `TUTOR_MAX_SESSIONS_PER_HOUR` caps new sessions for the whole instance.

Reach the web service only through the Cloudflare tunnel (step 4): a client that can reach the origin directly can forge the `CF-IPCountry` header the Sweden check trusts, so the check only holds behind the tunnel. Bind a private address (`TUTOR_BIND`, e.g. a tailnet address) and let the tunnel be the only public path.

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
funnel events (`page_opened`, `session_started`, …).
Person profiles are identified only (`device id + learner name`); conversation
text, typed text, homework content and images never leave the session, and
session outcomes are fixed categories (error events carry only the exception
class name, never its message). With no
key, `/api/config` returns `{"posthog": null}` and every analytics helper is
a no-op.

