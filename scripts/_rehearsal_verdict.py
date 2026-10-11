"""Rehearsal helper: one real verdict through the guard; exit 0 if < 2 s."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import guard, missions as M  # noqa: E402
m = next(iter(M.load().values()))
out = list(guard.stream(m["question"], M.evidence_records(m, "rehearsal check")))
ms = next(e for e in out if e[0] == "verdict")[2]
sys.exit(0 if ms < 2000 else 1)
