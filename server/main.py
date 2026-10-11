"""Beat the Guard: FastAPI app. Serves /play, /board and the game API."""

import io
import ipaddress
import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import qrcode
import qrcode.image.svg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (FileResponse, JSONResponse, RedirectResponse,
                               Response, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import admin, config, db, guard, limits, missions as M, netstatus, scoring

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app/static"
PORT = int(os.environ.get("BTG_PORT", "8080"))

GAME_SECONDS = 90
GRACE_SECONDS = 5          # covers network + verdict latency at the buzzer
MAX_ATTEMPTS = 3
MAX_TEXT = 600

ALLOWED_NETS = [ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
    "100.64.0.0/10",            # Tailscale
    "::1/128", "fd7a:115c:a1e0::/48",
)]
# /admin: the Nano's own screen, plus Tailscale for development at home.
# Every other client (booth hotspot, any LAN) gets a plain 404.
ADMIN_NETS = [ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "::1/128", "100.64.0.0/10", "fd7a:115c:a1e0::/48",
)]
# Booth hotspot: phones that join are sent to /play by the captive portal.
HOTSPOT_NET = ipaddress.ip_network(os.environ.get("BTG_HOTSPOT_NET",
                                                  "10.42.0.0/24"))
HOTSPOT_HOST = os.environ.get("BTG_HOTSPOT_HOST", "10.42.0.1")


def _in(ip, nets):
    return any(ip in n for n in nets if ip.version == n.version)


def is_admin_path(path):
    return path == "/admin" or path.startswith("/admin/") \
        or path.startswith("/api/admin/")


def captive_redirect(ip, host_header):
    """
    Hotspot DNS answers every name with the Nano, so OS connectivity probes
    (captive.apple.com, connectivitycheck.gstatic.com, msftconnecttest.com...)
    arrive here with a foreign Host header. Redirect those to the game so the
    phone pops its captive-portal sheet straight into /play.
    """
    if ip not in HOTSPOT_NET:
        return None
    host = (host_header or "").split(":")[0].lower()
    if host in (HOTSPOT_HOST, "localhost", "127.0.0.1"):
        return None
    return f"http://{HOTSPOT_HOST}/play"

BLOCKED_INITIALS = {
    "ASS", "FUK", "FUC", "FUQ", "SEX", "KKK", "CUM", "FAG", "NIG", "DIK",
    "DIC", "TIT", "FCK", "SHT", "CNT", "KYS", "NAZ", "XXX", "WTF", "STFU",
}
ROLES = {"CIO", "CISO / Security", "IT Director", "Research Computing",
         "Faculty / Researcher", "Other"}
OFFERS = {"pilot", "workshop", "specialist"}

MISSIONS = M.load()
# Operational log: initials + short session ID only. Never names, emails,
# institutions, or the text players type.
log = logging.getLogger("btg")
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s btg %(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)
    log.propagate = False
STATS = json.loads((ROOT / "app/stats.json").read_text())["cards"]


def _warmup():
    """
    At boot the app is up before the model. Wait for the model, then warm
    each mission's prompt prefix so the first real players aren't slow.
    """
    deadline = time.time() + 15 * 60
    while time.time() < deadline and not guard.health()["ok"]:
        time.sleep(3)
    for m in MISSIONS.values():
        for _ in range(3):
            try:
                for _ in guard.stream(m["question"],
                                      M.evidence_records(m, "warmup")):
                    pass
                break
            except guard.GuardError:
                time.sleep(3)


@asynccontextmanager
async def lifespan(app):
    db.init()
    threading.Thread(target=_warmup, daemon=True).start()
    yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None,
              lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(admin.router)


@app.middleware("http")
async def lan_only(request: Request, call_next):
    host = request.client.host if request.client else ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    if not _in(ip, ALLOWED_NETS):
        return JSONResponse({"detail": "forbidden"}, status_code=403)
    if is_admin_path(request.url.path) and not _in(ip, ADMIN_NETS):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    target = captive_redirect(ip, request.headers.get("host"))
    if target:
        return RedirectResponse(target, status_code=302)
    return await call_next(request)


# pages --------------------------------------------------------------------

@app.get("/")
def root():
    return RedirectResponse("/play")


@app.get("/play")
def play_page():
    return FileResponse(STATIC / "play.html")


@app.get("/board")
def board_page():
    return FileResponse(STATIC / "board.html")


def _client_ip(request):
    return request.client.host if request.client else "?"


def _limited(e):
    raise HTTPException(429, str(e), headers={"Retry-After": str(e.retry_after)})


# players ------------------------------------------------------------------

class PlayerIn(BaseModel):
    initials: str = Field(min_length=1, max_length=8)
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=200)
    institution: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=60)
    consent: bool = False


def _clean(s):
    s = (s or "").strip()
    return s or None


def _valid_email(e):
    return e is None or re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e)


@app.post("/api/players")
def create_player(p: PlayerIn, request: Request):
    try:
        limits.check_player(_client_ip(request))
    except limits.Limited as e:
        _limited(e)
    initials = re.sub(r"[^A-Za-z]", "", p.initials).upper()[:3]
    if len(initials) < 2:
        raise HTTPException(400, "Enter 2 or 3 letters for your initials.")
    if initials in BLOCKED_INITIALS:
        raise HTTPException(400, "Please choose different initials.")
    email = _clean(p.email)
    if not _valid_email(email):
        raise HTTPException(400, "That email doesn't look right.")
    role = p.role if p.role in ROLES else None
    # contact details are kept only with explicit consent
    pid = db.create_player(
        initials,
        _clean(p.name) if p.consent else None,
        email if p.consent else None,
        _clean(p.institution) if p.consent else None,
        role, p.consent, time.time(),
        demo=db.get_setting("demo_mode", "0") == "1")
    log.info("player id=%d initials=%s consent=%s", pid, initials,
             bool(p.consent))
    return {"player_id": pid, "initials": initials, "consent": p.consent}


class InterestIn(BaseModel):
    offer: str
    consent: bool = False
    name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=200)
    institution: str | None = Field(default=None, max_length=200)


@app.post("/api/players/{pid}/interest")
def interest(pid: int, i: InterestIn):
    if i.offer not in OFFERS:
        raise HTTPException(400, "unknown offer")
    if not i.consent:
        raise HTTPException(400, "Consent is required for HP to follow up.")
    email = _clean(i.email)
    if not _valid_email(email):
        raise HTTPException(400, "That email doesn't look right.")
    try:
        p = db.add_interest(pid, i.offer, _clean(i.name), email,
                            _clean(i.institution), time.time())
    except db.GameStateError as e:
        raise HTTPException(e.status, str(e))
    return {"ok": True, "has_email": bool(p["email"]),
            "interests": json.loads(p["interests"])}


# missions & games ---------------------------------------------------------

@app.get("/api/kiosk")
def kiosk():
    return {"demo_mode": db.get_setting("demo_mode", "0") == "1",
            "guard_ready": guard.health()["ok"], "mode": kiosk_mode()}


@app.get("/api/missions")
def list_missions():
    return [M.public(m) for m in MISSIONS.values() if m.get("active")]


class GameIn(BaseModel):
    player_id: int
    mission_id: str


@app.post("/api/games")
def create_game(g: GameIn, request: Request):
    try:
        limits.check_game(_client_ip(request))
    except limits.Limited as e:
        _limited(e)
    m = MISSIONS.get(g.mission_id)
    if not m or not m.get("active"):
        raise HTTPException(404, "unknown mission")
    if not db.q("SELECT id FROM players WHERE id=?", (g.player_id,), one=True):
        raise HTTPException(404, "unknown player")
    gid = uuid.uuid4().hex
    db.create_game(gid, g.player_id, m["id"], time.time())
    return {"game_id": gid, "seconds": GAME_SECONDS,
            "max_attempts": MAX_ATTEMPTS, "mission": M.public(m)}


def _finish(game, status, now, winning_text=None):
    attempts = db.game_attempts(game["id"])
    decisions = [a["decision"] for a in attempts]
    beat = status == "beat"
    creative = beat and scoring.is_creative(
        winning_text, db.prior_gap_texts(game["mission_id"], game["id"]))
    seconds_left = GAME_SECONDS - (now - game["started_at"])
    difficulty = MISSIONS[game["mission_id"]].get("difficulty", 1)
    s = scoring.score(decisions, beat, seconds_left, creative, MAX_ATTEMPTS,
                      difficulty)
    db.end_game(game["id"], status, now, len(attempts), s, creative)


def _summary(gid):
    g = db.get_game(gid)
    m = MISSIONS[g["mission_id"]]
    rank, total = db.rank_of(g["score"])
    p = db.q("SELECT consent, email, interests FROM players WHERE id=?",
             (g["player_id"],), one=True)
    return {
        "status": g["status"], "beat": g["status"] == "beat",
        "score": g["score"], "creative": bool(g["creative"]),
        "rank": rank, "of": total,
        "attempts": [{"n": a["n"], "decision": a["decision"],
                      "t_decision_ms": a["t_decision_ms"]}
                     for a in db.game_attempts(gid)],
        "mission": {"id": m["id"], "title": m["title"]},
        "takeaways": m["takeaways"],
        "player": {"consent": bool(p["consent"]), "has_email": bool(p["email"]),
                   "interests": json.loads(p["interests"])},
    }


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _judge(aid, n, game, m, text, out, ip):
    """Runs to completion even if the client disconnects, then records it."""
    try:
        verdict_ms = None
        for ev in guard.stream(m["question"], M.evidence_records(m, text)):
            if ev[0] == "verdict":
                verdict_ms = ev[2]
                out.put(("verdict", {"decision": ev[1], "t_decision_ms": ev[2],
                                     "attempt": n}))
            else:
                _, decision, parsed, raw, t_all = ev
        is_gap = decision == "YES"
        db.complete_attempt(aid, decision, parsed, raw, verdict_ms, t_all,
                            is_gap)
        who = db.q("SELECT initials FROM players WHERE id=?",
                   (game["player_id"],), one=True)
        log.info("attempt session=%s player=%s mission=%s n=%d decision=%s "
                 "verdict_ms=%s total_ms=%s", game["id"][:8],
                 who["initials"] if who else "?", m["id"], n, decision,
                 verdict_ms, t_all)
        now = time.time()
        if is_gap:
            _finish(game, "beat", now, text)
        elif n >= MAX_ATTEMPTS:
            _finish(game, "held", now)
        g = db.get_game(game["id"])
        out.put(("result", {
            "decision": decision, "attempt": n,
            "attempts_left": MAX_ATTEMPTS - n,
            "reasons": M.reasons(m, parsed["citations"] if parsed else []),
            "conditions": parsed["conditions"] if parsed else [],
            "rationale": parsed["rationale"] if parsed else None,
            "t_decision_ms": verdict_ms, "t_total_ms": t_all,
            "gap": is_gap, "game_over": g["status"] != "active",
        }))
    except guard.GuardError:
        db.cancel_attempt(aid)
        out.put(("error", {"message": "The guard is catching its breath. "
                           "This attempt was not counted. Try again."}))
    except Exception:  # noqa: BLE001
        db.cancel_attempt(aid)
        out.put(("error", {"message": "Something went wrong. This attempt "
                           "was not counted."}))
        raise
    finally:
        limits.release_verdict(ip)
        out.put(None)


class AttemptIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


@app.post("/api/games/{gid}/attempts")
def attempt(gid: str, a: AttemptIn, request: Request):
    text = " ".join(a.text.split())
    if len(text) < 3:
        raise HTTPException(400, "Write a request for the AI agent first.")
    if len(text) > MAX_TEXT:
        raise HTTPException(400, f"Keep it under {MAX_TEXT} characters. "
                                 "Short and sneaky works best.")
    ip = _client_ip(request)
    try:
        limits.acquire_verdict(ip)
    except limits.Limited as e:
        _limited(e)
    try:
        aid, n, game = db.reserve_attempt(
            gid, text, time.time(), GAME_SECONDS + GRACE_SECONDS, MAX_ATTEMPTS)
    except db.GameStateError as e:
        limits.release_verdict(ip)
        raise HTTPException(e.status, str(e))
    m = MISSIONS[game["mission_id"]]
    out = queue.Queue()
    threading.Thread(target=_judge, args=(aid, n, game, m, text, out, ip),
                     daemon=True).start()

    def events():
        while (item := out.get()) is not None:
            yield _sse(*item)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


class FinishIn(BaseModel):
    quit: bool = False          # player tapped "End mission" before time ran out


@app.post("/api/games/{gid}/finish")
def finish(gid: str, body: FinishIn | None = None):
    g = db.get_game(gid)
    if not g:
        raise HTTPException(404, "unknown game")
    # let an in-flight verdict land first (it may be the winning one)
    deadline = time.time() + guard.TIMEOUT_S + 2
    while time.time() < deadline and db.q(
            "SELECT 1 FROM attempts WHERE game_id=? AND decision IS NULL",
            (gid,), one=True):
        time.sleep(0.2)
    g = db.get_game(gid)
    if g["status"] == "active":
        used = len(db.game_attempts(gid))
        if body and body.quit:
            status = "ended"
        else:
            status = "held" if used >= MAX_ATTEMPTS else "timeout"
        _finish(g, status, time.time())
    return _summary(gid)


# board --------------------------------------------------------------------

def lan_ip():
    """Booth LAN address: wired first, then Wi-Fi. Never docker/tailscale."""
    try:
        lines = subprocess.run(["ip", "-4", "-o", "addr", "show"],
                               capture_output=True, text=True,
                               timeout=2).stdout.splitlines()
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    found = {}
    for line in lines:
        parts = line.split()
        ifname, addr = parts[1], parts[3].split("/")[0]
        if ifname.startswith(("lo", "docker", "br-", "veth", "tailscale")):
            continue
        found.setdefault("wired" if ifname.startswith(("en", "eth"))
                         else "other", addr)
    return found.get("wired") or found.get("other") or "127.0.0.1"


def kiosk_mode():
    """'station': the Nano's own screen runs /play (attract loop to the board).
    'board': the Nano's screen shows /board; players use tablets/phones."""
    return "station" if config.get("BTG_KIOSK_MODE", "board") == "station" \
        else "board"


_hotspot_cache = {"at": 0.0, "up": False}


def hotspot_active():
    """Only advertise the Wi-Fi QR when the booth hotspot is really up."""
    if time.time() - _hotspot_cache["at"] < 10:
        return _hotspot_cache["up"]
    try:
        out = subprocess.run(["nmcli", "-t", "-f", "NAME", "connection", "show",
                              "--active"], capture_output=True, text=True,
                             timeout=3).stdout.split()
        up = "btg-hotspot" in out
    except Exception:  # noqa: BLE001
        up = False
    _hotspot_cache.update(at=time.time(), up=up)
    return up


def wifi_config():
    return {"ssid": os.environ.get("BTG_WIFI_SSID", ""),
            "password": os.environ.get("BTG_WIFI_PASSWORD", "")}


LINK_IDS = ("specialist", "nano", "linkedin")


def external_links():
    """Follow-up links for attendees' own phones. Only real https URLs show."""
    out = []
    for lid in LINK_IDS:
        url = os.environ.get(f"BTG_LINK_{lid.upper()}_URL", "").strip()
        label = os.environ.get(f"BTG_LINK_{lid.upper()}_LABEL", lid).strip()
        if url.startswith("https://") and " " not in url:
            out.append({"id": lid, "label": label, "url": url})
    return out


def play_url():
    return os.environ.get("BTG_PLAY_URL") or f"http://{lan_ip()}:{PORT}/play"


def _wifi_qr_payload(ssid, password):
    esc = lambda v: re.sub(r'([\\;,:"])', r"\\\1", v)  # noqa: E731
    auth = "WPA" if password else "nopass"
    return f"WIFI:T:{auth};S:{esc(ssid)};P:{esc(password)};;"


@app.get("/api/board")
def board():
    wifi = wifi_config()
    return {
        "stats": db.board_stats(),
        "leaderboard": [
            {"initials": r["initials"], "score": r["score"],
             "status": r["status"],
             "mission": MISSIONS[r["mission_id"]]["title"]
             if r["mission_id"] in MISSIONS else r["mission_id"]}
            for r in db.leaderboard()],
        "play_url": play_url(),
        "wifi": {"ssid": wifi["ssid"]}
        if wifi["ssid"] and hotspot_active() else None,
        "mode": kiosk_mode(),
        "network": netstatus.status(),
        "cards": STATS,
    }


@app.get("/api/links")
def links():
    return [{"id": x["id"], "label": x["label"],
             "display": re.sub(r"^https://(www\.)?", "", x["url"]).rstrip("/")}
            for x in external_links()]


@app.get("/api/qr.svg")
def qr_svg(kind: str = "play", id: str = ""):
    wifi = wifi_config()
    if kind == "wifi" and wifi["ssid"]:
        payload = _wifi_qr_payload(wifi["ssid"], wifi["password"])
    elif kind == "link":
        link = next((x for x in external_links() if x["id"] == id), None)
        if not link:
            raise HTTPException(404, "link not configured")
        payload = link["url"]
    else:
        payload = play_url()
    img = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage,
                      border=1)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/health")
def health():
    return {"guard": guard.health(), "missions": len(MISSIONS)}
