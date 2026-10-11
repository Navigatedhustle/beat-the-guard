#!/usr/bin/env bash

DIR="$(cd "$(dirname "$0")" && pwd)"

# Always keep the Nano in normal desktop mode
"$DIR/kiosk_mode.sh" maintenance >/dev/null 2>&1

URL="http://127.0.0.1/board"

# Wait for Beat The Guard web app
until curl -sf "http://127.0.0.1/api/board" >/dev/null; do
    sleep 2
done

# Open BTG like a normal application instead of taking over Ubuntu
/snap/bin/chromium \
    --new-window \
    --no-first-run \
    --no-default-browser-check \
    "$URL" >/dev/null 2>&1 &
