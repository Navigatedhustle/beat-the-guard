"""Reads config/booth.env on demand, so secrets rotate without a restart."""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / "config/booth.env"


def get(key, default=""):
    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                return v
    except OSError:
        pass
    return os.environ.get(key, default)
