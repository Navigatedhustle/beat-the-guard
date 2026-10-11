"""
Fails if any player name, email or institution from the database appears in
the app log, the model log, or the systemd journal for btg-app / btg-model.

    .venv/bin/python scripts/check_pii_logs.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import db  # noqa: E402

needles = set()
for r in db.q("SELECT name, email, institution FROM players"):
    for v in r.values():
        if v and len(v) >= 4:
            needles.add(v)

sources = {}
for f in (ROOT / "logs").glob("*.log"):
    sources[str(f.relative_to(ROOT))] = f.read_text(errors="replace")
for unit in ("btg-app", "btg-model"):
    out = subprocess.run(["journalctl", "-u", unit, "--no-pager", "-q", "-o", "cat"],
                         capture_output=True, text=True).stdout
    sources[f"journal:{unit}"] = out
out = subprocess.run(["docker", "logs", "btg-sentinel"], capture_output=True, text=True)
sources["docker:btg-sentinel"] = out.stdout + out.stderr

hits = [(src, n) for src, text in sources.items() for n in needles if n in text]
print(f"checked {len(needles)} PII values against {len(sources)} log sources "
      f"({sum(len(t) for t in sources.values()):,} chars)")
for src, n in hits:
    print(f"  LEAK in {src}: {n[:3]}…")
print("PII IN LOGS: NONE" if not hits else "PII IN LOGS: FOUND")
sys.exit(1 if hits else 0)
