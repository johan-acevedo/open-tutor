# Hosting one family's instance

The web service and the voice worker run as **user** services (no root). Browser audio goes directly to LiveKit Cloud; only the page and `/api/session` need HTTPS.

1. Clone the repository to `~/code/open-tutor` and write `~/.config/open-tutor/env` (mode 600) with the variables in [server/README.md](../server/README.md). Set `TUTOR_ACCESS_CODE` for anything reachable from the internet.
2. Optional: `~/.config/open-tutor/bind.env` with `TUTOR_BIND=<address>` if the HTTPS proxy runs on another machine (for example a tailnet address).
3. `deploy/install.sh` builds the page, installs `open-tutor-web` and `open-tutor-agent`, and checks `/api/health`. User services keep running after logout only with lingering enabled (`loginctl show-user $USER -p Linger`).
4. Route an HTTPS hostname to the web service (Johan's instance: a Cloudflare tunnel on the Mini, see the home-lab ops handbook). Microphones only work on HTTPS pages.

Share the page as `https://<host>/?kod=<family code>`. The browser remembers the code. `TUTOR_MAX_SESSIONS_PER_HOUR` caps new sessions for the whole instance.

Only one worker should register as `open-tutor` per LiveKit project. A second (for example a developer's `dev` worker) would take some of the sessions.
