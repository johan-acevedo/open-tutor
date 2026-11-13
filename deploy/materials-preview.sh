#!/usr/bin/env bash
# Install a separate tailnet-only materials preview; never register as the family worker.
# Credentials/config must already exist in ~/.config/open-tutor-materials/env (0600).
set -euo pipefail
preview_repo=$(cd "$(dirname "$0")/.." && pwd)
preview_env="$HOME/.config/open-tutor-materials/env"
preview_venv="$HOME/.local/share/open-tutor/materials/preview-venv"
[[ -f "$preview_env" ]] || { echo "Missing private preview env file" >&2; exit 1; }
# Prevent a copy of the family's env from taking its normal sessions.
preview_name=$(OPEN_TUTOR_ENV="$preview_env" "$preview_repo/server/bin/with-env" python3 -c 'import os; print(os.getenv("TUTOR_AGENT_NAME", ""))')
[[ "$preview_name" == open-tutor-materials-preview ]] || { echo "Preview requires its separate agent name" >&2; exit 1; }
(cd "$preview_repo/web" && npm ci --no-audit --no-fund && npm run build)
(cd "$preview_repo/server" && UV_PROJECT_ENVIRONMENT="$preview_venv" uv sync --frozen --group ml)
(cd "$preview_repo/server" && OPEN_TUTOR_ENV="$preview_env" "$preview_repo/server/bin/with-env" "$preview_venv/bin/python" -m open_tutor.agent download-files)
mkdir -p "$HOME/.config/systemd/user"
for preview_kind in web agent; do
  if [[ "$preview_kind" == web ]]; then
    preview_command="$preview_venv/bin/uvicorn open_tutor.web:app --host 127.0.0.1 --port 8720 --workers 1 --proxy-headers"
  else
    preview_command="$preview_venv/bin/python -m open_tutor.agent start"
  fi
  cat > "$HOME/.config/systemd/user/open-tutor-materials-$preview_kind.service" <<EOF
[Unit]
Description=Open Tutor materials preview $preview_kind
After=network-online.target
[Service]
WorkingDirectory=$preview_repo/server
Environment=OPEN_TUTOR_ENV=$preview_env
ExecStart=$preview_repo/server/bin/with-env $preview_command
Restart=on-failure
RestartSec=5
[Install]
WantedBy=default.target
EOF
done
systemctl --user daemon-reload
systemctl --user enable open-tutor-materials-web.service open-tutor-materials-agent.service
systemctl --user restart open-tutor-materials-web.service open-tutor-materials-agent.service
# Adds a separate HTTPS port, preserving existing Serve routes.
tailscale serve --bg --https=9443 http://127.0.0.1:8720
