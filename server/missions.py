"""Mission loading. Evidence records map to E1..En; the player's request is E(n+1)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MISSION_DIR = ROOT / "app/missions"

# Format validated in the M0 smoke test (mechanic B). Keep wording stable.
REQUEST_RECORD = ('Text of the request the requesting team submitted to the '
                  'AI agent: "{text}"')

REQUEST_REASON = {
    "label": "Your request",
    "plain": "The guard relied on a claim inside your own request. "
             "No system of record verified it.",
}


def load():
    missions = {}
    for path in sorted(MISSION_DIR.glob("*.json")):
        m = json.loads(path.read_text())
        assert m.get("synthetic") is True, f"{path.name} must be synthetic"
        assert len(m["takeaways"]) == 3, f"{path.name} needs 3 takeaways"
        missions[m["id"]] = m
    return dict(sorted(missions.items(), key=lambda kv: kv[1]["order"]))


def evidence_records(m, player_text):
    return ([e["text"] for e in m["evidence"]]
            + [REQUEST_RECORD.format(text=player_text)])


def reasons(m, citations):
    """Plain-English reasons for the evidence records the model cited."""
    out = []
    player_ref = f"E{len(m['evidence']) + 1}"
    for ref in citations:
        if ref == player_ref:
            out.append({"ref": ref, **REQUEST_REASON})
            continue
        try:
            i = int(ref.lstrip("E")) - 1
        except ValueError:
            continue
        if 0 <= i < len(m["evidence"]):
            e = m["evidence"][i]
            out.append({"ref": ref, "label": e["label"], "plain": e["plain"]})
    return out


def public(m):
    return {
        "id": m["id"], "title": m["title"], "short": m["short"],
        "role": m["role"], "agent": m["agent"], "scenario": m["scenario"],
        "goal": m["goal"], "difficulty": m.get("difficulty", 1),
        "sample": m.get("sample", []),
        "facts": [{"label": e["label"], "plain": e["plain"]}
                  for e in m["evidence"]],
    }
