"""
Live network status for the /board badge.

"Offline" is claimed only when it is true: no default route on the host
(nothing can be routed beyond the booth LAN) and an outbound probe fails.
Bytes are counted on any interface that carries a default route.
"""

import socket
import threading
import time
from pathlib import Path

PROBES = [("1.1.1.1", 443), ("8.8.8.8", 53)]
CACHE_S = 5

_lock = threading.Lock()
_cache = {"at": 0.0, "value": None}


def _default_route_ifaces():
    """
    Interfaces holding an IPv4 or IPv6 default route, read straight from the
    kernel (no dependency on the `ip` binary). Returns None if the routing
    tables can't be read, so a failed check is never reported as offline.
    """
    try:
        v4 = Path("/proc/net/route").read_text().splitlines()[1:]
    except OSError:
        return None
    ifaces = set()
    for line in v4:
        f = line.split()
        # Iface Destination Gateway Flags ... Mask
        if len(f) >= 8 and f[1] == "00000000" and f[7] == "00000000" \
                and int(f[3], 16) & 0x1:
            ifaces.add(f[0])
    try:
        for line in Path("/proc/net/ipv6_route").read_text().splitlines():
            f = line.split()
            # dest plen src splen nexthop metric refcnt use flags iface
            if len(f) >= 10 and f[0] == "0" * 32 and f[1] == "00" \
                    and f[9] != "lo" and int(f[8], 16) & 0x1 \
                    and not int(f[8], 16) & 0x200:          # skip RTF_REJECT
                ifaces.add(f[9])
    except OSError:
        pass
    return sorted(ifaces)


def _tx_bytes(iface):
    try:
        return int(Path(f"/sys/class/net/{iface}/statistics/tx_bytes")
                   .read_text())
    except Exception:  # noqa: BLE001
        return 0


def _probe():
    for host, port in PROBES:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except OSError:
            continue
    return False


def status():
    with _lock:
        if time.time() - _cache["at"] < CACHE_S and _cache["value"]:
            return _cache["value"]
        uplinks = _default_route_ifaces()
        if uplinks is None:
            value = {"offline": False, "unknown": True,
                     "internet_reachable": False, "uplinks": [],
                     "uplink_tx_bytes": 0, "checked_at": time.time()}
            _cache.update(at=time.time(), value=value)
            return value
        # without a default route the kernel can't send anything off-LAN, so
        # the probe below fails locally without a packet leaving
        reachable = _probe() if uplinks else False
        value = {
            "offline": not uplinks and not reachable,
            "unknown": False,
            "internet_reachable": reachable,
            "uplinks": uplinks,
            "uplink_tx_bytes": sum(_tx_bytes(i) for i in uplinks),
            "checked_at": time.time(),
        }
        _cache.update(at=time.time(), value=value)
        return value
