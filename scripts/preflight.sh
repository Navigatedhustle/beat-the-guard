#!/usr/bin/env bash
# Booth preflight: run after power-on. No sudo needed. Exit code 0 = all green.
#   scripts/preflight.sh
BASE="${BTG_URL:-http://127.0.0.1}"
fail=0
ok()  { printf '  OK    %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; fail=1; }
warn(){ printf '  WARN  %s\n' "$*"; }

echo "Beat the Guard preflight $(date '+%a %H:%M')"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if (set -a; source "$ROOT/config/booth.env") 2>/dev/null; then
  ok "config/booth.env loads"
  set -a; source "$ROOT/config/booth.env"; set +a
  n=0; for v in "$BTG_LINK_SPECIALIST_URL" "$BTG_LINK_NANO_URL" "$BTG_LINK_LINKEDIN_URL"; do [[ "$v" == https://* ]] && n=$((n+1)); done
  (( n == 3 )) && ok "end-screen links: 3 of 3 set" || warn "end-screen links: $n of 3 set (placeholders are hidden from players)"
else
  bad "config/booth.env has a syntax error (quote values with spaces)"
fi

for s in btg-model btg-app; do
  if systemctl is-active --quiet "$s"; then ok "service $s running"; else bad "service $s not running (sudo systemctl restart $s)"; fi
done

if curl -sf "$BASE/api/health" | grep -q '"ok":true'; then
  ok "guard model loaded"
else
  bad "guard model not ready (wait ~3 min after boot; then: sudo systemctl restart btg-model)"
fi

v=$(curl -sf "$BASE/api/kiosk" 2>/dev/null)
[[ "$v" == *'"guard_ready":true'* ]] && ok "/play will accept players" || bad "/play is showing 'guard starting up'"

ms=$(cd "$(dirname "$0")/.." && .venv/bin/python - <<'EOF' 2>/dev/null
import sys; sys.path.insert(0, ".")
from server import guard, missions as M
m = next(iter(M.load().values()))
out = list(guard.stream(m["question"], M.evidence_records(m, "preflight check")))
print(next(e for e in out if e[0] == "verdict")[2])
EOF
)
if [[ -n "$ms" && "$ms" -lt 2000 ]]; then ok "test verdict in ${ms} ms"; else bad "test verdict slow or failed (${ms:-no answer})"; fi

net=$(curl -sf "$BASE/api/board" | python3 -c 'import sys,json; n=json.load(sys.stdin)["network"]; print("offline" if n["offline"] else "uplinks=" + ",".join(n["uplinks"]))' 2>/dev/null)
[[ "$net" == offline ]] && ok "network OFFLINE (badge: 0 bytes left the building)" || warn "network not offline: $net (unplug uplinks for show mode)"

if [[ "${BTG_KIOSK_MODE:-board}" == station ]]; then
  ok "station mode: game runs on this screen (no tablets or hotspot needed)"
  pgrep -f 'chromium.*--kiosk.*127[.]0[.]0[.]1' >/dev/null && ok "game on screen (kiosk running)" || warn "kiosk browser not running (desktop shortcut 'Beat the Guard' or reboot)"
elif nmcli -t -f NAME connection show --active 2>/dev/null | grep -qx btg-hotspot; then ok "hotspot up"
else warn "hotspot not active (sudo nmcli connection up btg-hotspot)"; fi

free=$(df --output=avail -BG / | tail -1 | tr -dc 0-9)
[[ "$free" -gt 20 ]] && ok "disk free ${free} GB" || warn "disk free only ${free} GB"

echo
[[ $fail -eq 0 ]] && echo "ALL GREEN" || echo "FIX THE FAIL LINES ABOVE"
exit $fail
