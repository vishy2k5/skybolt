#!/bin/sh
# Show Skybolt full screen once the backend answers. Uses its own browser profile.
URL="${SKYBOLT_URL:-http://127.0.0.1:8000/}"
PROFILE="${SKYBOLT_KIOSK_PROFILE:-$HOME/.local/share/skybolt/kiosk-profile}"

tries=0
until curl -fsS -o /dev/null "${URL%/}/api/health"; do
    tries=$((tries + 1))
    if [ "$tries" -ge 60 ]; then
        echo "backend not answering at $URL" >&2
        exit 1
    fi
    sleep 1
done

exec chromium "$URL" \
    --kiosk \
    --ozone-platform=wayland \
    --user-data-dir="$PROFILE" \
    --no-first-run \
    --no-default-browser-check \
    --noerrdialogs \
    --disable-infobars \
    --hide-crash-restore-bubble \
    --password-store=basic \
    --disable-features=Translate \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --disk-cache-size=52428800
