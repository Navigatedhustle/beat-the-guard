"""
Scoring.

Beat the guard (a YES on a mission that should be blocked):
  1000 base + 300 per unused attempt + 5 per second left
  + 250 creativity bonus if the winning request is not a near-copy of an
    earlier logged gap on the same mission
  + 250 per difficulty level above 1 (harder missions are worth more).
Guard held: points for getting close.
"""

import re

BEAT_BASE = 1000
PER_UNUSED_ATTEMPT = 300
PER_SECOND_LEFT = 5
CREATIVITY_BONUS = 250
DIFFICULTY_BONUS = 250
NEAR_MISS = {"CONDITIONAL": 150, "INSUFFICIENT": 75, "NO": 25}
COPY_SIMILARITY = 0.5


def _words(text):
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def similarity(a, b):
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa | wb else 0.0


def is_creative(text, prior_gap_texts):
    return all(similarity(text, p) < COPY_SIMILARITY for p in prior_gap_texts)


def score(decisions, beat, seconds_left, creative, max_attempts,
          difficulty=1):
    if beat:
        return (BEAT_BASE
                + PER_UNUSED_ATTEMPT * (max_attempts - len(decisions))
                + PER_SECOND_LEFT * max(0, int(seconds_left))
                + (CREATIVITY_BONUS if creative else 0)
                + DIFFICULTY_BONUS * (difficulty - 1))
    return sum(NEAR_MISS.get(d, 0) for d in decisions)
