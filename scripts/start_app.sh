#!/usr/bin/env bash
# Beat the Guard web app. Listens on all interfaces; server/main.py rejects
# any client outside loopback, private LAN ranges, and Tailscale.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
umask 077   # database, archives and exports hold lead contact details
if [[ -f config/booth.env ]]; then set -a; source config/booth.env; set +a; fi
exec .venv/bin/uvicorn server.main:app --host 0.0.0.0 --port "${BTG_PORT:-8080}" \
  --workers 1 --no-server-header --log-level info
