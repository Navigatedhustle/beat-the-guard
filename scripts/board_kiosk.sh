#!/usr/bin/env bash
# Full-screen /board on the Nano's own display. Started by the desktop
# autostart entry at login. Locks the desktop (kiosk_mode.sh), waits for the
# app, then relaunches Chromium if it exits. While staff maintenance mode is
# on (admin page), the board stays closed until the kiosk is relocked.
DIR="$(cd "$(dirname "$0")" && pwd)"
# BTG_KIOSK_MODE in config/booth.env: station = the game on this screen
# (attract loop to the board when idle); board = the board (tablets play).
MODE=$(grep -E '^BTG_KIOSK_MODE=' "$DIR/../config/booth.env" 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '"'"'"' ')
if [[ "$MODE" == station ]]; then
  URL="${BTG_BOARD_URL:-http://127.0.0.1/play?station=1}"
else
  URL="${BTG_BOARD_URL:-http://127.0.0.1/board}"
fi
FLAG="$HOME/.cache/btg-maintenance"

[[ -f "$FLAG" ]] || "$DIR/kiosk_mode.sh" lock

# Cold-boot rehearsal armed from admin: time every check from boot, unattended
if [[ -f "$HOME/.cache/btg-rehearsal-armed" ]]; then
  rm -f "$HOME/.cache/btg-rehearsal-armed"
  mkdir -p "$DIR/../logs"
  "$DIR/rehearsal_check.sh" > "$DIR/../logs/rehearsal-$(date +%Y%m%d-%H%M%S).txt" 2>&1 &
fi

# Ctrl+Alt+A opens /admin in a window over the board (appends, never replaces,
# any existing custom shortcuts)
KB=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/btg-admin/
list=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null)
if [[ -n "$list" && "$list" != *btg-admin* ]]; then
  if [[ "$list" == "@as []" || "$list" == "[]" ]]; then new="['$KB']"; else new="${list%]}, '$KB']"; fi
  gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$new"
fi
S="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$KB"
gsettings set "$S" name 'Guard Admin' 2>/dev/null || true
gsettings set "$S" command "$DIR/admin_window.sh" 2>/dev/null || true
gsettings set "$S" binding '<Control><Alt>a' 2>/dev/null || true

until curl -sf "http://127.0.0.1/api/board" >/dev/null; do sleep 2; done
# Relaunch Chromium if it exits. Watchdog: if it keeps running but no board
# or admin window is visible for ~15 s (crashed tab, window destroyed), kill
# it so the loop brings the board back.
visible() {
  command -v xdotool >/dev/null || return 0
  # headless (no monitor on HDMI/USB-C): mutter can't place windows; nothing to fix
  xrandr 2>/dev/null | grep -q " connected" || return 0
  for w in $(xdotool search --onlyvisible --name 'Beat the Guard|Guard Admin' 2>/dev/null); do
    return 0
  done
  # minimized or unmapped: try to bring it back before restarting Chromium
  for w in $(xdotool search --name 'Beat the Guard|Guard Admin' 2>/dev/null); do
    wmctrl -i -a "$w" 2>/dev/null; xdotool windowmap "$w" 2>/dev/null
  done
  sleep 1
  [[ -n "$(xdotool search --onlyvisible --name 'Beat the Guard|Guard Admin' 2>/dev/null)" ]]
}
while true; do
  while [[ -f "$FLAG" ]]; do sleep 2; done
  /snap/bin/chromium --kiosk --noerrdialogs --disable-infobars --incognito \
    --no-first-run --disable-translate --password-store=basic \
    --disable-pinch --overscroll-history-navigation=0 \
    --disable-background-networking --disable-sync --disable-component-update --disable-domain-reliability --disable-client-side-phishing-detection --no-default-browser-check --metrics-recording-only \
    --check-for-update-interval=31536000 "$URL" &
  pid=$!
  sleep 20                                   # startup grace
  misses=0
  while kill -0 "$pid" 2>/dev/null; do
    [[ -f "$FLAG" ]] && { kill "$pid" 2>/dev/null; break; }
    if visible; then misses=0; else misses=$((misses + 1)); fi
    if (( misses >= 3 )); then kill "$pid" 2>/dev/null; sleep 2; kill -9 "$pid" 2>/dev/null; break; fi
    sleep 5
  done
  wait "$pid" 2>/dev/null
  sleep 3
done
