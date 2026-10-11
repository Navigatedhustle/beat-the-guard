"""Local SQLite store for players, games, attempts. WAL mode, one connection per call."""

import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("BTG_DB", ROOT / "data/btg.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id          INTEGER PRIMARY KEY,
    initials    TEXT NOT NULL,
    name        TEXT,
    email       TEXT,
    institution TEXT,
    role        TEXT,
    consent     INTEGER NOT NULL DEFAULT 0,
    consent_at  REAL,
    interests   TEXT NOT NULL DEFAULT '[]',
    hidden      INTEGER NOT NULL DEFAULT 0,
    demo        INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS games (
    id            TEXT PRIMARY KEY,
    player_id     INTEGER NOT NULL REFERENCES players(id),
    mission_id    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active',
    started_at    REAL NOT NULL,
    ended_at      REAL,
    attempts_used INTEGER NOT NULL DEFAULT 0,
    score         INTEGER NOT NULL DEFAULT 0,
    creative      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS attempts (
    id            INTEGER PRIMARY KEY,
    game_id       TEXT NOT NULL REFERENCES games(id),
    player_id     INTEGER NOT NULL,
    mission_id    TEXT NOT NULL,
    n             INTEGER NOT NULL,
    text          TEXT NOT NULL,
    decision      TEXT,
    citations     TEXT,
    conditions    TEXT,
    rationale     TEXT,
    raw           TEXT,
    parse_ok      INTEGER,
    t_decision_ms INTEGER,
    t_total_ms    INTEGER,
    is_gap        INTEGER NOT NULL DEFAULT 0,
    reviewed      INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_game ON attempts(game_id);
CREATE INDEX IF NOT EXISTS games_status ON games(status);
"""


class GameStateError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init():
    c = connect()
    c.executescript(SCHEMA)
    # attempts left pending by a crash or restart were never decided
    c.execute("DELETE FROM attempts WHERE decision IS NULL")
    c.close()


def q(sql, args=(), one=False):
    c = connect()
    try:
        rows = [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()
    return (rows[0] if rows else None) if one else rows


def ex(sql, args=()):
    c = connect()
    try:
        return c.execute(sql, args).lastrowid
    finally:
        c.close()


# players ------------------------------------------------------------------

def create_player(initials, name, email, institution, role, consent, now,
                  demo=False):
    return ex(
        "INSERT INTO players(initials,name,email,institution,role,consent,"
        "consent_at,demo,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (initials, name, email, institution, role, int(consent),
         now if consent else None, int(demo), now))


def add_interest(pid, offer, name, email, institution, now):
    p = q("SELECT * FROM players WHERE id=?", (pid,), one=True)
    if not p:
        raise GameStateError("unknown player", 404)
    interests = json.loads(p["interests"])
    if offer not in interests:
        interests.append(offer)
    ex("UPDATE players SET interests=?, consent=1, consent_at=COALESCE("
       "consent_at,?), name=COALESCE(?,name), email=COALESCE(?,email), "
       "institution=COALESCE(?,institution) WHERE id=?",
       (json.dumps(interests), now, name, email, institution, pid))
    return q("SELECT * FROM players WHERE id=?", (pid,), one=True)


# games --------------------------------------------------------------------

def create_game(gid, pid, mission_id, now):
    ex("INSERT INTO games(id,player_id,mission_id,started_at) VALUES(?,?,?,?)",
       (gid, pid, mission_id, now))


def get_game(gid):
    return q("SELECT * FROM games WHERE id=?", (gid,), one=True)


def reserve_attempt(gid, text, now, limit_s, max_attempts):
    """Atomically check game state and insert a pending attempt."""
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        g = c.execute("SELECT * FROM games WHERE id=?", (gid,)).fetchone()
        if not g:
            raise GameStateError("unknown game", 404)
        if g["status"] != "active":
            raise GameStateError("game is over")
        if now > g["started_at"] + limit_s:
            raise GameStateError("time is up")
        pending = c.execute(
            "SELECT COUNT(*) FROM attempts WHERE game_id=? AND decision IS NULL",
            (gid,)).fetchone()[0]
        if pending:
            raise GameStateError("previous attempt still being judged")
        n = c.execute("SELECT COUNT(*) FROM attempts WHERE game_id=?",
                      (gid,)).fetchone()[0]
        if n >= max_attempts:
            raise GameStateError("no attempts left")
        aid = c.execute(
            "INSERT INTO attempts(game_id,player_id,mission_id,n,text,"
            "created_at) VALUES(?,?,?,?,?,?)",
            (gid, g["player_id"], g["mission_id"], n + 1, text, now)).lastrowid
        c.execute("COMMIT")
        return aid, n + 1, dict(g)
    except BaseException:
        if c.in_transaction:
            c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def cancel_attempt(aid):
    ex("DELETE FROM attempts WHERE id=? AND decision IS NULL", (aid,))


def complete_attempt(aid, decision, parsed, raw, t_dec, t_all, is_gap):
    ex("UPDATE attempts SET decision=?, citations=?, conditions=?, "
       "rationale=?, raw=?, parse_ok=?, t_decision_ms=?, t_total_ms=?, "
       "is_gap=? WHERE id=?",
       (decision,
        json.dumps(parsed["citations"]) if parsed else "[]",
        json.dumps(parsed["conditions"]) if parsed else "[]",
        parsed["rationale"] if parsed else None,
        raw, int(parsed is not None), t_dec, t_all, int(is_gap), aid))


def game_attempts(gid):
    return q("SELECT * FROM attempts WHERE game_id=? AND decision IS NOT NULL "
             "ORDER BY n", (gid,))


def prior_gap_texts(mission_id, exclude_gid):
    return [r["text"] for r in q(
        "SELECT text FROM attempts WHERE mission_id=? AND is_gap=1 "
        "AND game_id!=?", (mission_id, exclude_gid))]


def end_game(gid, status, now, attempts_used, score, creative):
    """Ends an active game once. Returns False if it was already over."""
    c = connect()
    try:
        cur = c.execute(
            "UPDATE games SET status=?, ended_at=?, attempts_used=?, score=?, "
            "creative=? WHERE id=? AND status='active'",
            (status, now, attempts_used, score, int(creative), gid))
        return cur.rowcount == 1
    finally:
        c.close()


def rank_of(score):
    epoch = board_epoch()
    above = q("SELECT COUNT(*) AS n FROM games g JOIN players p ON "
              "p.id=g.player_id WHERE g.status!='active' AND p.demo=0 "
              "AND g.started_at>=? AND g.score>?", (epoch, score), one=True)["n"]
    total = q("SELECT COUNT(*) AS n FROM games g JOIN players p ON "
              "p.id=g.player_id WHERE g.status!='active' AND p.demo=0 "
              "AND g.started_at>=?", (epoch,), one=True)["n"]
    return above + 1, total


# board --------------------------------------------------------------------

def get_setting(key, default=None):
    r = q("SELECT value FROM settings WHERE key=?", (key,), one=True)
    return r["value"] if r else default


def set_setting(key, value):
    ex("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) "
       "DO UPDATE SET value=excluded.value", (key, str(value)))


def board_epoch():
    return float(get_setting("board_epoch", "0"))


def board_stats():
    epoch = board_epoch()
    s = q("SELECT COUNT(*) AS attempts, "
          "SUM(CASE WHEN a.decision!='YES' THEN 1 ELSE 0 END) AS blocked, "
          "AVG(a.t_decision_ms) AS avg_ms, SUM(a.is_gap) AS gaps "
          "FROM attempts a JOIN players p ON p.id=a.player_id "
          "WHERE a.decision IS NOT NULL AND p.demo=0 AND a.created_at>=?",
          (epoch,), one=True)
    players = q("SELECT COUNT(*) AS n FROM players WHERE demo=0 "
                "AND created_at>=?", (epoch,), one=True)["n"]
    return {
        "attempts": s["attempts"] or 0,
        "blocked_pct": round(100 * (s["blocked"] or 0) / s["attempts"], 1)
        if s["attempts"] else None,
        "avg_decision_ms": round(s["avg_ms"]) if s["avg_ms"] else None,
        "gaps": s["gaps"] or 0,
        "players": players,
    }


def leaderboard(limit=10):
    # best finished game per visible, non-demo player
    return q(
        "SELECT p.id AS player_id, p.initials, g.score, g.mission_id, "
        "g.status, g.attempts_used "
        "FROM games g JOIN players p ON p.id=g.player_id "
        "WHERE g.status!='active' AND p.hidden=0 AND p.demo=0 "
        "AND g.started_at>=:epoch AND g.id=("
        "  SELECT g2.id FROM games g2 WHERE g2.player_id=g.player_id "
        "  AND g2.status!='active' AND g2.started_at>=:epoch "
        "  ORDER BY g2.score DESC, g2.ended_at ASC LIMIT 1) "
        "ORDER BY g.score DESC, g.ended_at ASC LIMIT :limit",
        {"epoch": board_epoch(), "limit": limit})


# admin --------------------------------------------------------------------

def gaps(limit=200):
    return q("SELECT a.id, a.created_at, a.mission_id, a.text, a.citations, "
             "a.conditions, a.t_decision_ms, a.reviewed, p.initials, p.demo "
             "FROM attempts a JOIN players p ON p.id=a.player_id "
             "WHERE a.is_gap=1 ORDER BY a.created_at DESC LIMIT ?", (limit,))


def set_reviewed(aid, reviewed):
    ex("UPDATE attempts SET reviewed=? WHERE id=? AND is_gap=1",
       (int(reviewed), aid))


def set_hidden(pid, hidden):
    ex("UPDATE players SET hidden=? WHERE id=?", (int(hidden), pid))


def export_leads(since=0.0):
    """Consented players; `since` (epoch) limits to players created after it."""
    return q("SELECT id AS player_id, datetime(created_at,'unixepoch',"
             "'localtime') AS created_local, initials, name, email, "
             "institution, role, interests, datetime(consent_at,'unixepoch',"
             "'localtime') AS consent_local, demo FROM players WHERE "
             "consent=1 AND (created_at>=? OR consent_at>=?) "
             "ORDER BY created_at", (since, since))


def export_attempts(since=0.0):
    return q("SELECT a.id AS attempt_id, datetime(a.created_at,'unixepoch',"
             "'localtime') AS created_local, p.initials, p.role, p.demo, "
             "a.mission_id, a.game_id, a.n AS attempt_no, a.decision, "
             "a.is_gap, a.reviewed, a.t_decision_ms, a.t_total_ms, "
             "a.citations, a.conditions, a.rationale, a.parse_ok, a.text "
             "FROM attempts a JOIN players p ON p.id=a.player_id "
             "WHERE a.decision IS NOT NULL AND a.created_at>=? "
             "ORDER BY a.created_at", (since,))


def counts():
    return q("SELECT (SELECT COUNT(*) FROM players) AS players, "
             "(SELECT COUNT(*) FROM players WHERE consent=1) AS leads, "
             "(SELECT COUNT(*) FROM games) AS games, "
             "(SELECT COUNT(*) FROM attempts WHERE decision IS NOT NULL) "
             "AS attempts, (SELECT COUNT(*) FROM attempts WHERE is_gap=1) "
             "AS gaps, (SELECT COUNT(*) FROM attempts WHERE is_gap=1 AND "
             "reviewed=0) AS gaps_unreviewed", one=True)


def recent_latency(n=20):
    rows = q("SELECT t_decision_ms FROM attempts WHERE t_decision_ms IS NOT "
             "NULL ORDER BY created_at DESC LIMIT ?", (n,))
    ms = sorted(r["t_decision_ms"] for r in rows)
    if not ms:
        return None
    return {"n": len(ms), "median": ms[len(ms) // 2], "max": ms[-1]}


def archive_and_wipe(archive_dir, stamp):
    """Copies the full database to archive_dir, then clears play data."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / f"btg-{stamp}.db"
    c = connect()
    try:
        c.execute("VACUUM INTO ?", (str(dest),))
        dest.chmod(0o600)
        c.executescript("DELETE FROM attempts; DELETE FROM games; "
                        "DELETE FROM players; DELETE FROM settings "
                        "WHERE key='board_epoch';")
    finally:
        c.close()
    return dest
