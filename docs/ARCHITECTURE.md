# Architecture

FastAPI serves player/board/admin pages and a SQLite game store. A strict JSON contract wraps a local vLLM LoRA classifier. Abuse limits, per-device/global quotas, consented lead exports and password-protected admin controls support booth operation.

## Implemented endpoints inspected from source

| Method | Route | Source |
| --- | --- | --- |
| GET | `/admin` | `server/admin.py` |
| POST | `/api/admin/login` | `server/admin.py` |
| POST | `/api/admin/logout` | `server/admin.py` |
| GET | `/api/admin/overview` | `server/admin.py` |
| POST | `/api/admin/test-verdict` | `server/admin.py` |
| POST | `/api/admin/restart-model` | `server/admin.py` |
| POST | `/api/admin/preflight` | `server/admin.py` |
| POST | `/api/admin/rehearsal/arm` | `server/admin.py` |
| GET | `/api/admin/rehearsal` | `server/admin.py` |
| POST | `/api/admin/kiosk` | `server/admin.py` |
| POST | `/api/admin/demo-mode` | `server/admin.py` |
| POST | `/api/admin/reset-board` | `server/admin.py` |
| POST | `/api/admin/archive-wipe` | `server/admin.py` |
| GET | `/api/admin/leaderboard` | `server/admin.py` |
| POST | `/api/admin/players/{pid}/hidden` | `server/admin.py` |
| GET | `/api/admin/gaps` | `server/admin.py` |
| POST | `/api/admin/gaps/{aid}/reviewed` | `server/admin.py` |
| GET | `/api/admin/export/report.pdf` | `server/admin.py` |
| GET | `/api/admin/export.zip` | `server/admin.py` |
| GET | `/api/admin/usb` | `server/admin.py` |
| POST | `/api/admin/usb-export` | `server/admin.py` |
| GET | `/` | `server/main.py` |
| GET | `/play` | `server/main.py` |
| GET | `/board` | `server/main.py` |
| POST | `/api/players` | `server/main.py` |
| POST | `/api/players/{pid}/interest` | `server/main.py` |
| GET | `/api/kiosk` | `server/main.py` |
| GET | `/api/missions` | `server/main.py` |
| POST | `/api/games` | `server/main.py` |
| POST | `/api/games/{gid}/attempts` | `server/main.py` |
| POST | `/api/games/{gid}/finish` | `server/main.py` |
| GET | `/api/board` | `server/main.py` |
| GET | `/api/links` | `server/main.py` |
| GET | `/api/qr.svg` | `server/main.py` |
| GET | `/api/health` | `server/main.py` |

These routes establish implementation shape. They do not establish successful provider integration or model quality. Generated state and data stores are excluded from the repository.
