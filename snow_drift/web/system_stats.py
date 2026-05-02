"""Lightweight Raspberry Pi system stats reader.

Pulls CPU temperature, load averages, memory, disk, system uptime, and
the Pi-specific throttle status (under-voltage / thermal throttling)
without depending on ``psutil``. Each call is cached for two seconds
so polling the web UI doesn't cost real I/O.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS: float = 2.0

_cache: Dict[str, Any] = {}
_cache_at: float = 0.0
_cache_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Individual probes - each returns ``None`` on failure so the JSON shape
# stays stable. The web UI checks for ``null`` and renders "—" instead.
# ---------------------------------------------------------------------------
def _read_cpu_temp_c() -> Optional[float]:
    path = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        return int(path.read_text().strip()) / 1000.0
    except Exception:
        return None


def _read_loadavg() -> tuple[Optional[float], Optional[float], Optional[float]]:
    try:
        a, b, c = os.getloadavg()
        return a, b, c
    except (OSError, AttributeError):
        return None, None, None


def _read_meminfo() -> Dict[str, Optional[int]]:
    try:
        info: Dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            value = rest.strip().split()[0]
            info[key] = int(value) * 1024  # kB → bytes
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        used = max(0, total - avail)
        return {
            "mem_total_bytes": total,
            "mem_used_bytes": used,
            "mem_pct": (used / total * 100.0) if total else None,
        }
    except Exception:
        return {"mem_total_bytes": None, "mem_used_bytes": None, "mem_pct": None}


def _read_disk_root() -> Dict[str, Optional[float]]:
    try:
        st = os.statvfs("/")
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        used = max(0, total - free)
        return {
            "disk_total_bytes": total,
            "disk_used_bytes": used,
            "disk_pct": (used / total * 100.0) if total else None,
        }
    except Exception:
        return {"disk_total_bytes": None, "disk_used_bytes": None, "disk_pct": None}


def _read_system_uptime_seconds() -> Optional[float]:
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except Exception:
        return None


# Bit flags returned by ``vcgencmd get_throttled``. The high half are
# "since boot" history bits; the low half are "right now" bits.
_THROTTLE_FLAGS: dict[int, str] = {
    0x1: "under-voltage now",
    0x2: "freq capped now",
    0x4: "throttled now",
    0x8: "soft temp limit now",
    0x10000: "under-voltage occurred",
    0x20000: "freq capping occurred",
    0x40000: "throttling occurred",
    0x80000: "soft temp limit occurred",
}


def _read_throttle_status() -> Dict[str, Any]:
    """Run ``vcgencmd get_throttled`` and decode the bit flags."""
    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
        out = result.stdout.strip()
        # Expected format: "throttled=0x0"
        if "=" not in out:
            return {"raw": out, "value": None, "flags": [], "throttled_now": False}
        raw_value = out.split("=", 1)[1]
        value = int(raw_value, 16)
        flags = [label for bit, label in _THROTTLE_FLAGS.items() if value & bit]
        return {
            "raw": raw_value,
            "value": value,
            "flags": flags,
            # Just the low-half "right now" flags; history bits are
            # noisy on Pis that booted under-voltaged once weeks ago.
            "throttled_now": bool(value & 0xF),
        }
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, OSError):
        return {"raw": None, "value": None, "flags": [], "throttled_now": False}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def read_pi_stats() -> Dict[str, Any]:
    """Return a freshly-cached snapshot of Pi system stats."""
    global _cache, _cache_at
    now = time.monotonic()
    with _cache_lock:
        if _cache and now - _cache_at < _CACHE_TTL_SECONDS:
            return dict(_cache)

    stats: Dict[str, Any] = {
        "cpu_temp_c": _read_cpu_temp_c(),
        "system_uptime_seconds": _read_system_uptime_seconds(),
        "throttle": _read_throttle_status(),
    }
    load1, load5, load15 = _read_loadavg()
    stats["load_1m"] = load1
    stats["load_5m"] = load5
    stats["load_15m"] = load15
    stats.update(_read_meminfo())
    stats.update(_read_disk_root())

    with _cache_lock:
        _cache = stats
        _cache_at = now
    return dict(stats)
