#!/bin/sh
# Install Skybolt on this Pi. See "Deploy on the Pi" in README.md.
#   install.sh backend        install and start the backend service
#   install.sh kiosk-on       start the kiosk now and at every desktop login
#   install.sh kiosk-off      stop the kiosk and remove its autostart
#   install.sh uninstall      remove everything above (keeps data/)
set -eu

DEPLOY="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$DEPLOY")"
USER_UNITS="$HOME/.config/systemd/user"
AUTOSTART="$HOME/.config/autostart/skybolt-kiosk.desktop"

render() {
    sed -e "s|@USER@|$(id -un)|g" -e "s|@ROOT@|$ROOT|g" "$1"
}

backend() {
    uv="$(command -v uv || echo "$HOME/.local/bin/uv")"
    (cd "$ROOT" && "$uv" sync --frozen --no-dev)
    mkdir -p "$ROOT/data"
    render "$DEPLOY/skybolt.service" | sudo tee /etc/systemd/system/skybolt.service >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable skybolt.service
    sudo systemctl restart skybolt.service
}

kiosk_on() {
    mkdir -p "$USER_UNITS" "$(dirname "$AUTOSTART")"
    for unit in skybolt-kiosk.service skybolt-kiosk-restart.service skybolt-kiosk-restart.timer; do
        render "$DEPLOY/$unit" > "$USER_UNITS/$unit"
    done
    cp "$DEPLOY/skybolt-kiosk.desktop" "$AUTOSTART"
    systemctl --user daemon-reload
    systemctl --user start skybolt-kiosk.service skybolt-kiosk-restart.timer
}

kiosk_off() {
    systemctl --user stop skybolt-kiosk.service skybolt-kiosk-restart.timer 2>/dev/null || true
    rm -f "$AUTOSTART" "$USER_UNITS"/skybolt-kiosk*
    systemctl --user daemon-reload
}

uninstall() {
    kiosk_off
    sudo systemctl disable --now skybolt.service 2>/dev/null || true
    sudo rm -f /etc/systemd/system/skybolt.service
    sudo systemctl daemon-reload
}

case "${1:-}" in
    backend) backend ;;
    kiosk-on) kiosk_on ;;
    kiosk-off) kiosk_off ;;
    uninstall) uninstall ;;
    *) sed -n '2,6p' "$0" | cut -c3-; exit 2 ;;
esac
