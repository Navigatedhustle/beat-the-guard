#!/usr/bin/env bash
# M3 cold-boot rehearsal. Run right after the Nano finishes booting (it
# waits and polls). Prints T+ seconds since kernel boot for each check.
# Pass = every automatic check green by T+180 s.
#   scripts/rehearsal_check.sh
cd "$(dirname "$0")/.."
BASE=http://127.0.0.1
LIMIT=180
set -a; source config/booth.env; set +a
up() { cut -d. -f1 /proc/uptime; }
declare -A done_at
check() { # name, command
  [[ -n "${done_at[$1]}" ]] && return 0
  if eval "$2" >/dev/null 2>&1; then done_at[$1]=$(up); printf '  T+%4ss  PASS  %s\n' "${done_at[$1]}" "$1"; fi
}
echo "Rehearsal check started at T+$(up)s (seconds since kernel boot; add ~15 s firmware POST for true power-on)"
names=("app serving" "model loaded" "board full screen" "network OFFLINE" "verdict under 2 s" "lead saved + read back" "USB export verified")
while :; do
  check "app serving"        "curl -sf $BASE/api/board"
  check "model loaded"       "curl -sf $BASE/api/kiosk | grep -q '\"guard_ready\":true'"
  check "board full screen"  "pgrep -f 'chromium.*--kiosk.*127[.]0[.]0[.]1'"
  check "network OFFLINE"    "curl -sf $BASE/api/board | grep -q '\"offline\":true'"
  [[ -n "${done_at[model loaded]}" ]] && check "verdict under 2 s" ".venv/bin/python scripts/_rehearsal_verdict.py"
  [[ -n "${done_at[app serving]}" ]] && check "lead saved + read back" ".venv/bin/python scripts/_rehearsal_lead.py"
  if [[ -n "${done_at[app serving]}" && -z "${done_at[USB export verified]}" ]]; then
    c=$(mktemp); curl -sf -c "$c" -H 'Content-Type: application/json' -d "{\"password\":\"$BTG_ADMIN_PASSWORD\"}" $BASE/api/admin/login >/dev/null
    drive=$(curl -sf -b "$c" $BASE/api/admin/usb | python3 -c 'import sys,json; d=json.load(sys.stdin)["drives"]; print(d[0]["path"] if d else "")')
    [[ -n "$drive" ]] && check "USB export verified" "curl -sf -b $c -H 'Content-Type: application/json' -d '{\"path\":\"$drive\"}' $BASE/api/admin/usb-export | grep -q '\"ok\":true'"
    rm -f "$c"
  fi
  all=1; for n in "${names[@]}"; do [[ -z "${done_at[$n]}" ]] && all=0; done
  (( all )) && break
  (( $(up) > LIMIT + 120 )) && break
  sleep 2
done
echo; fail=0
for n in "${names[@]}"; do
  t=${done_at[$n]}
  if [[ -z "$t" ]]; then printf '  FAIL  %-26s never passed\n' "$n"; fail=1
  elif (( t > LIMIT )); then printf '  SLOW  %-26s T+%ss (limit %ss)\n' "$n" "$t" "$LIMIT"; fail=1
  else printf '  OK    %-26s T+%ss\n' "$n" "$t"; fi
done
echo; echo "Manual (tick on the runbook sheet): tablet 1 plays a full game · tablet 2 plays at the same time · phone captive portal opens /play"
(( fail )) && echo "REHEARSAL: NOT READY" || echo "REHEARSAL: PASS (all automatic checks inside ${LIMIT}s)"
exit $fail
