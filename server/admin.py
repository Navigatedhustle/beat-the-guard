"""/admin: password-protected booth controls."""

import csv
import hashlib
import hmac
import io
import os
import secrets
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config, db, guard, missions as M, netstatus, report

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app/static"
ARCHIVE = ROOT / "data/archive"
SECRET_FILE = ROOT / "data/.admin_secret"
COOKIE = "btg_admin"
SESSION_S = 12 * 3600
MAX_FAILS = 5
FAIL_WINDOW_S = 60
MODEL_CONTAINER = "btg-sentinel"

router = APIRouter()
_fails = {}


def _secret():
    if not SECRET_FILE.exists():
        SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        SECRET_FILE.write_text(secrets.token_hex(32))
        SECRET_FILE.chmod(0o600)
    return SECRET_FILE.read_text().strip().encode()


def _password():
    return config.get("BTG_ADMIN_PASSWORD") or ""


def _sign(expiry):
    mac = hmac.new(_secret(), str(expiry).encode(), hashlib.sha256).hexdigest()
    return f"{expiry}.{mac}"


def _valid(token):
    try:
        expiry, mac = token.split(".", 1)
        return (int(expiry) > time.time()
                and hmac.compare_digest(_sign(int(expiry)), token))
    except Exception:  # noqa: BLE001
        return False


def require(request: Request):
    if not _valid(request.cookies.get(COOKIE, "")):
        raise HTTPException(401, "login required")


# pages & auth ---------------------------------------------------------------

@router.get("/admin")
def admin_page():
    return FileResponse(STATIC / "admin.html")


class LoginIn(BaseModel):
    password: str


@router.post("/api/admin/login")
def login(body: LoginIn, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    now = time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < FAIL_WINDOW_S]
    if len(recent) >= MAX_FAILS:
        raise HTTPException(429, "Too many attempts. Wait a minute.")
    pw = _password()
    if not pw or not hmac.compare_digest(body.password.encode(), pw.encode()):
        _fails[ip] = recent + [now]
        raise HTTPException(401, "Wrong password.")
    _fails.pop(ip, None)
    response.set_cookie(COOKIE, _sign(int(now + SESSION_S)), max_age=SESSION_S,
                        httponly=True, samesite="strict")
    return {"ok": True}


@router.post("/api/admin/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


# overview & health ----------------------------------------------------------

def _gpu():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,temperature.gpu,utilization.gpu,"
             "power.draw", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3).stdout.strip()
        name, temp, util, power = [x.strip() for x in out.split(",")]
        return {"ok": True, "name": name, "temp_c": temp, "util_pct": util,
                "power_w": power}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _memory():
    info = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, v = line.split(":", 1)
        info[k] = int(v.split()[0])
    return {"total_gb": round(info["MemTotal"] / 1048576, 1),
            "available_gb": round(info["MemAvailable"] / 1048576, 1)}


@router.get("/api/admin/overview")
def overview(request: Request):
    require(request)
    from .main import (external_links, hotspot_active, kiosk_mode,  # avoids a cycle
                       play_url, wifi_config)
    return {
        "counts": db.counts(),
        "demo_mode": db.get_setting("demo_mode", "0") == "1",
        "board_epoch": db.board_epoch(),
        "guard": guard.health(),
        "latency": db.recent_latency(),
        "gpu": _gpu(),
        "memory": _memory(),
        "network": netstatus.status(),
        "play_url": play_url(),
        "wifi": {"ssid": wifi_config()["ssid"], "active": hotspot_active()},
        "mode": kiosk_mode(),
        "links_configured": len(external_links()),
        "server_time": time.time(),
    }


@router.post("/api/admin/test-verdict")
def test_verdict(request: Request):
    require(request)
    from .main import MISSIONS
    m = next(iter(MISSIONS.values()))
    try:
        out = list(guard.stream(m["question"], M.evidence_records(
            m, "Please send the file with the agent.")))
    except guard.GuardError as e:
        raise HTTPException(503, f"Guard not responding: {e}")
    verdict = next(e for e in out if e[0] == "verdict")
    final = out[-1]
    return {"decision": verdict[1], "t_decision_ms": verdict[2],
            "t_total_ms": final[4], "json_ok": final[2] is not None}


@router.post("/api/admin/restart-model")
def restart_model(request: Request):
    """Kills the model container; systemd brings it back (about 1 min)."""
    require(request)
    r = subprocess.run(["docker", "kill", MODEL_CONTAINER],
                       capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise HTTPException(500, r.stderr.strip() or "docker kill failed")
    return {"ok": True, "note": "Model restarting. Allow about 1-2 minutes."}


# controls -------------------------------------------------------------------

REHEARSAL_FLAG = Path(os.path.expanduser("~/.cache/btg-rehearsal-armed"))


@router.post("/api/admin/preflight")
def run_preflight(request: Request):
    require(request)
    port = os.environ.get("BTG_PORT", "8080")
    r = subprocess.run([str(ROOT / "scripts/preflight.sh")], capture_output=True,
                       text=True, timeout=90,
                       env={**os.environ, "BTG_URL": f"http://127.0.0.1:{port}"})
    return {"ok": r.returncode == 0, "output": r.stdout + r.stderr}


@router.post("/api/admin/rehearsal/arm")
def arm_rehearsal(request: Request):
    """The next login (cold boot) runs rehearsal_check.sh automatically."""
    require(request)
    REHEARSAL_FLAG.parent.mkdir(parents=True, exist_ok=True)
    REHEARSAL_FLAG.touch()
    return {"ok": True, "note": "Armed. Power the Nano off and on; the check "
                                "starts at login and its result shows here."}


@router.get("/api/admin/rehearsal")
def last_rehearsal(request: Request):
    require(request)
    runs = sorted((ROOT / "logs").glob("rehearsal-*.txt"))
    return {"armed": REHEARSAL_FLAG.exists(),
            "file": runs[-1].name if runs else None,
            "output": runs[-1].read_text() if runs else ""}


class KioskIn(BaseModel):
    mode: str


@router.post("/api/admin/kiosk")
def kiosk_mode(body: KioskIn, request: Request):
    """Maintenance: unlock the Nano's desktop and pause the board. Lock: undo."""
    require(request)
    if body.mode not in ("lock", "maintenance"):
        raise HTTPException(400, "mode must be lock or maintenance")
    uid = os.getuid()
    env = {**os.environ, "HOME": os.path.expanduser("~"),
           "XDG_RUNTIME_DIR": f"/run/user/{uid}",
           "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus"}
    r = subprocess.run([str(ROOT / "scripts/kiosk_mode.sh"), body.mode],
                       capture_output=True, text=True, timeout=30, env=env)
    if r.returncode != 0:
        raise HTTPException(500, (r.stdout + r.stderr).strip()[-300:])
    return {"ok": True, "mode": body.mode, "note": r.stdout.strip()}


class Toggle(BaseModel):
    on: bool


@router.post("/api/admin/demo-mode")
def demo_mode(body: Toggle, request: Request):
    require(request)
    db.set_setting("demo_mode", "1" if body.on else "0")
    return {"demo_mode": body.on}


@router.post("/api/admin/reset-board")
def reset_board(request: Request):
    """Starts a fresh leaderboard and stats. Players, leads, attempts are kept."""
    require(request)
    db.set_setting("board_epoch", time.time())
    return {"ok": True}


class WipeIn(BaseModel):
    confirm: str


@router.post("/api/admin/archive-wipe")
def archive_wipe(body: WipeIn, request: Request):
    require(request)
    if body.confirm != "WIPE":
        raise HTTPException(400, 'Type WIPE to confirm.')
    dest = db.archive_and_wipe(ARCHIVE, time.strftime("%Y%m%d-%H%M%S"))
    return {"ok": True, "archive": str(dest.relative_to(ROOT))}


@router.get("/api/admin/leaderboard")
def admin_leaderboard(request: Request):
    require(request)
    from .main import MISSIONS
    rows = db.leaderboard(limit=50)
    for r in rows:
        m = MISSIONS.get(r["mission_id"])
        r["mission"] = m["title"] if m else r["mission_id"]
    return rows


class HiddenIn(BaseModel):
    hidden: bool


@router.post("/api/admin/players/{pid}/hidden")
def hide_player(pid: int, body: HiddenIn, request: Request):
    require(request)
    db.set_hidden(pid, body.hidden)
    return {"ok": True}


@router.get("/api/admin/gaps")
def list_gaps(request: Request):
    require(request)
    from .main import MISSIONS
    rows = db.gaps()
    for r in rows:
        m = MISSIONS.get(r["mission_id"])
        r["mission"] = m["title"] if m else r["mission_id"]
    return rows


class ReviewedIn(BaseModel):
    reviewed: bool


@router.post("/api/admin/gaps/{aid}/reviewed")
def review_gap(aid: int, body: ReviewedIn, request: Request):
    require(request)
    db.set_reviewed(aid, body.reviewed)
    return {"ok": True}


# exports --------------------------------------------------------------------

def _csv_text(rows):
    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return buf.getvalue()


def _export_files(since_midnight):
    day = time.strftime("%Y-%m-%d")
    return {
        f"leads-{day}.csv": _csv_text(db.export_leads(since_midnight)),
        "leads-ALL.csv": _csv_text(db.export_leads()),
        f"attempts-{day}.csv": _csv_text(db.export_attempts(since_midnight)),
        "attempts-ALL.csv": _csv_text(db.export_attempts()),
    }


def _export_password():
    pw = config.get("BTG_EXPORT_PASSWORD")
    if len(pw) < 20:
        raise HTTPException(500, "BTG_EXPORT_PASSWORD is missing or shorter "
                                 "than 20 characters in config/booth.env.")
    return pw.encode()


def _encrypted_zip(files):
    """AES-256 (WinZip AE-2) zip; opens with 7-Zip, Keka, The Unarchiver."""
    import pyzipper
    buf = io.BytesIO()
    with pyzipper.AESZipFile(buf, "w", compression=pyzipper.ZIP_DEFLATED,
                             encryption=pyzipper.WZ_AES) as z:
        z.setpassword(_export_password())
        z.setencryption(pyzipper.WZ_AES, nbits=256)
        for name, text in files.items():
            z.writestr(name, text.encode())
    return buf.getvalue()


def _verify_zip(path, files):
    import pyzipper
    with pyzipper.AESZipFile(path) as z:
        z.setpassword(_export_password())
        if sorted(z.namelist()) != sorted(files):
            return False
        return all(z.read(n) == t.encode() for n, t in files.items())


@router.get("/api/admin/export/report.pdf")
def export_report(request: Request):
    """Lead report for the team: AES-256 PDF, opens with BTG_EXPORT_PASSWORD."""
    require(request)
    data = report.build(_export_password().decode())
    stamp = time.strftime("%Y%m%d-%H%M")
    return Response(data, media_type="application/pdf", headers={
        "Content-Disposition":
            f'attachment; filename="BeatTheGuard-lead-report-{stamp}.pdf"',
        "Cache-Control": "no-store"})


@router.get("/api/admin/export.zip")
def export_zip(request: Request):
    """Encrypted download of the same files the USB export writes."""
    require(request)
    data = _encrypted_zip(_export_files(_local_midnight()))
    stamp = time.strftime("%Y%m%d-%H%M")
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition":
            f'attachment; filename="BeatTheGuard-{stamp}-encrypted.zip"',
        "Cache-Control": "no-store"})


# USB export -----------------------------------------------------------------
# Drives are auto-mounted by the desktop session (udisks) under /media/<user>.

USB_ROOTS = [Path(p) for p in os.environ.get(
    "BTG_USB_ROOTS", f"/media/{os.environ.get('USER', 'demo')}:/run/media/"
    f"{os.environ.get('USER', 'demo')}").split(":")]


def _usb_mounts():
    mounts = {}
    try:
        for line in Path("/proc/mounts").read_text().splitlines():
            dev, mnt = line.split()[:2]
            mounts[mnt.replace("\\040", " ")] = dev
    except OSError:
        pass
    out = []
    for root in USB_ROOTS:
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            if d.is_dir() and (str(d) in mounts
                               or os.environ.get("BTG_USB_ROOTS")):
                try:
                    st = os.statvfs(d)
                    free = round(st.f_bavail * st.f_frsize / 1e9, 1)
                except OSError:
                    continue
                out.append({"path": str(d), "label": d.name,
                            "device": mounts.get(str(d), ""),
                            "free_gb": free,
                            "writable": os.access(d, os.W_OK)})
    return out


def _local_midnight():
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


@router.get("/api/admin/usb")
def usb_list(request: Request):
    require(request)
    return {"drives": _usb_mounts(), "today": time.strftime("%Y-%m-%d"),
            "leads_today": len(db.export_leads(_local_midnight()))}


class UsbIn(BaseModel):
    path: str


@router.post("/api/admin/usb-export")
def usb_export(body: UsbIn, request: Request):
    """Writes today's and all-time leads + attempts, then verifies them."""
    require(request)
    drive = next((d for d in _usb_mounts() if d["path"] == body.path), None)
    if not drive:
        raise HTTPException(404, "That drive isn't mounted any more.")
    if not drive["writable"]:
        raise HTTPException(400, "That drive is read-only.")
    files = _export_files(_local_midnight())
    data = _encrypted_zip(files)
    folder = Path(drive["path"]) / "BeatTheGuard-exports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"BeatTheGuard-{time.strftime('%Y%m%d-%H%M')}.zip"
    with open(path, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.sync()
    # read back from the drive and decrypt: it must match what we meant to write
    if path.read_bytes() != data or not _verify_zip(path, files):
        raise HTTPException(500, "Verification failed. Try another drive.")
    pdf = report.build(_export_password().decode())
    pdf_path = folder / f"BeatTheGuard-lead-report-{time.strftime('%Y%m%d-%H%M')}.pdf"
    with open(pdf_path, "wb") as f:
        f.write(pdf)
        f.flush()
        os.fsync(f.fileno())
    os.sync()
    if pdf_path.read_bytes() != pdf:
        raise HTTPException(500, "PDF verification failed. Try another drive.")
    return {"ok": True, "file": str(path), "report": str(pdf_path),
            "contents": [{"file": n, "rows": max(0, t.count("\n") - 1)}
                         for n, t in files.items()],
            "note": "Encrypted (AES-256), written and verified. Eject the "
                    "drive from the desktop or wait 5 seconds before pulling "
                    "it."}
