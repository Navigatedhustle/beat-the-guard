#!/usr/bin/env bash
# Opens /admin in its own window on the Nano's screen, on top of the board
# kiosk. Close it with Alt+F4 to return to the board. Bound to Ctrl+Alt+A.
exec /snap/bin/chromium --user-data-dir="$HOME/snap/chromium/common/btg-admin" \
  --app=http://127.0.0.1/admin --window-size=1280,900 --no-first-run \
  --password-store=basic --disable-background-networking --disable-sync --disable-component-update --disable-domain-reliability --disable-client-side-phishing-detection --no-default-browser-check --metrics-recording-only
