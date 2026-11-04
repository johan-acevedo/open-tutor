#!/usr/bin/env bash
# Install or update Open Tutor as user services on this machine (no root).
# Usage: deploy/install.sh [git-ref]   (run from the checkout; default: current branch)
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
cd "$repo"
export PATH="$HOME/.local/bin:$PATH"  # uv and npm for non-interactive (ssh) shells
if [[ -n ${1:-} ]]; then git fetch -q origin && git checkout -q "$1" && git pull -q --ff-only || true; fi
(cd server && ~/.local/bin/uv sync -q --frozen --python 3.12)
(cd web && npm ci --silent && npm run -s build)
[[ -f ~/.config/open-tutor/env ]] || { echo "Missing ~/.config/open-tutor/env (see server/README.md)" >&2; exit 1; }
mkdir -p ~/.config/systemd/user
ln -sf "$repo/deploy/open-tutor-web.service" ~/.config/systemd/user/
ln -sf "$repo/deploy/open-tutor-agent.service" ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable -q --now open-tutor-web.service open-tutor-agent.service
systemctl --user restart open-tutor-web.service open-tutor-agent.service
sleep 4
curl -fsS "http://${TUTOR_BIND:-127.0.0.1}:8710/api/health" && echo
