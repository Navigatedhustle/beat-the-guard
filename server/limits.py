"""
Per-device abuse limits for /play (device = client IP on the booth Wi-Fi).

Sized so real play never touches them: a game allows 3 attempts in 90 s and
each verdict takes ~2-3 s to finish, so a fast player replaying back to back
makes at most ~12 attempts a minute (fast human, measured). One verdict in
flight per device also caps flooding at ~24/min regardless (each takes ~2.5 s).
"""

import threading
import time
from collections import defaultdict, deque

ATTEMPTS_PER_MIN = 20
PLAYERS_PER_MIN = 6
GAMES_PER_MIN = 10
INFLIGHT_PER_DEVICE = 1
INFLIGHT_TOTAL = 8          # matches vLLM --max-num-seqs

_lock = threading.Lock()
_events = defaultdict(deque)          # (kind, ip) -> timestamps
_inflight = defaultdict(int)          # ip -> running verdicts
_inflight_total = 0


class Limited(Exception):
    def __init__(self, message, retry_after):
        super().__init__(message)
        self.retry_after = retry_after


def _window(kind, ip, per_min):
    now = time.monotonic()
    q = _events[(kind, ip)]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= per_min:
        wait = int(60 - (now - q[0])) + 1
        raise Limited(f"Whoa, fast fingers. Give the guard {wait} seconds, "
                      "then try again.", wait)
    q.append(now)


def check_player(ip):
    with _lock:
        _window("player", ip, PLAYERS_PER_MIN)


def check_game(ip):
    with _lock:
        _window("game", ip, GAMES_PER_MIN)


def acquire_verdict(ip):
    """Call before reserving an attempt; pair with release_verdict(ip)."""
    global _inflight_total
    with _lock:
        if _inflight[ip] >= INFLIGHT_PER_DEVICE:
            raise Limited("Your last request is still being judged. One "
                          "moment.", 3)
        if _inflight_total >= INFLIGHT_TOTAL:
            raise Limited("The guard is busy with other players. Try again "
                          "in a few seconds.", 5)
        _window("attempt", ip, ATTEMPTS_PER_MIN)
        _inflight[ip] += 1
        _inflight_total += 1


def release_verdict(ip):
    global _inflight_total
    with _lock:
        if _inflight[ip] > 0:
            _inflight[ip] -= 1
            _inflight_total -= 1
        if not _inflight[ip]:
            _inflight.pop(ip, None)
