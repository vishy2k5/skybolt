#!/bin/sh
# Pull the latest code from GitHub (main) and restart Skybolt. From another computer on Tailscale:
#   ssh <user>@<pi> '<path to skybolt>/deploy/update.sh'
set -eu
cd "$(dirname "$0")/.."
PATH="$HOME/.local/bin:$PATH"

git pull --ff-only
uv sync --frozen --no-dev
sudo systemctl restart skybolt
systemctl --user try-restart skybolt-kiosk.service 2>/dev/null || true  # reload the screen
echo "Skybolt updated to $(git log -1 --format='%h %s')"
