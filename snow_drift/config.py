"""Central configuration for Snow Drift.

All "magic numbers" live here so the piece can be tuned without hunting
through the rest of the codebase. Constants are grouped by subsystem.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Final

# ---------------------------------------------------------------------------
# Fan GPIO pins (BCM numbering)
# ---------------------------------------------------------------------------
# All four pins are hardware-PWM capable on the Pi 5.
# Physical pins:  Fan1=12, Fan2=33, Fan3=32, Fan4=35
FAN_PINS: Final[list[int]] = [18, 13, 12, 19]
PWM_FREQUENCY: Final[int] = 1000  # Hz - fast enough to be silent on tiny fans

# Stagger fan startup to avoid an inrush-current spike on the 5V rail.
FAN_STARTUP_STAGGER_SECONDS: Final[float] = 0.2

# ---------------------------------------------------------------------------
# Sensor pins / I2C
# ---------------------------------------------------------------------------
PIR_PIN: Final[int] = 4  # BCM 4 / Physical 7

OLED_ADDRESS: Final[int] = 0x3C
BME688_ADDRESS: Final[int] = 0x76
BH1750_ADDRESS: Final[int] = 0x23
I2C_BUS: Final[int] = 1  # default Pi I2C bus

# ---------------------------------------------------------------------------
# Sleep / wake behavior
# ---------------------------------------------------------------------------
MOTION_TIMEOUT_SECONDS: Final[float] = 900.0   # 15 min of no motion → SLEEPING
FULL_SLEEP_SECONDS: Final[float] = 1200.0      # 20 min total → ASLEEP
WAKE_FADE_IN_SECONDS: Final[float] = 30.0      # ramp 0→1 on wake
SLEEP_FADE_OUT_SECONDS: Final[float] = 300.0   # ramp 1→0 on sleep

# ---------------------------------------------------------------------------
# Environmental → mood mapping
# ---------------------------------------------------------------------------
# Temperature (Celsius)
TEMP_CALM_C: Final[float] = 18.0    # ≤ this → calm baseline
TEMP_ACTIVE_C: Final[float] = 24.0  # ≥ this → active baseline

# Humidity (%RH)
HUMIDITY_LOW: Final[float] = 30.0   # ≤ this → ordered, smooth flow
HUMIDITY_HIGH: Final[float] = 70.0  # ≥ this → chaotic gusts

# Light (lux)
LUX_BRIGHT: Final[float] = 500.0    # bright daylight → subtler movement
LUX_DIM: Final[float] = 10.0        # near darkness → dramatic movement

# Time constant (seconds) for environment-driven baseline smoothing.
# We compute a per-step alpha as ``1 - exp(-dt / tau)`` so smoothing
# behaves the same regardless of loop rate. ~63% of the way to a new
# target after ``ENV_SMOOTHING_TAU_SECONDS``, ~95% after 3*tau.
ENV_SMOOTHING_TAU_SECONDS: Final[float] = 5.0

# ---------------------------------------------------------------------------
# Wind algorithm
# ---------------------------------------------------------------------------
UPDATE_RATE_HZ: Final[float] = 25.0   # main loop / fan update rate
PERLIN_SCALE: Final[float] = 0.3      # smaller = slower noise wandering

GUST_PROBABILITY: Final[float] = 0.05      # per-second chance of a gust
GUST_DURATION_SECONDS: Final[float] = 2.0
GUST_INTENSITY: Final[float] = 0.9         # peak speed during a gust

STILLNESS_PROBABILITY: Final[float] = 0.02  # per-second chance of pause
STILLNESS_DURATION_SECONDS: Final[float] = 4.0

# Lower bound on fan output once they are spinning. Tiny 4010 fans
# need a minimum duty cycle to overcome stiction.
MIN_RUNNING_DUTY: Final[float] = 0.18

# Periodically re-base the wind algorithm's internal time accumulator
# so single-precision-ish drift can't degrade Perlin lattice resolution
# over very long uninterrupted runs. ~11 days at 1.0 lattice spacing.
WIND_TIME_WRAP_SECONDS: Final[float] = 1_000_000.0

# ---------------------------------------------------------------------------
# Sensor read intervals
# ---------------------------------------------------------------------------
PIR_READ_HZ: Final[float] = 10.0
BME688_READ_INTERVAL_SECONDS: Final[float] = 30.0
BH1750_READ_INTERVAL_SECONDS: Final[float] = 5.0

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
OLED_UPDATE_HZ: Final[float] = 5.0
OLED_WIDTH: Final[int] = 128
OLED_HEIGHT: Final[int] = 64

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL: Final[int] = logging.INFO
LOG_FORMAT: Final[str] = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_FORMAT_JOURNAL: Final[str] = "%(name)s: %(message)s"

# Map Python log levels to RFC 5424 / syslog priority numbers. journald
# reads the leading ``<N>`` from each line and uses it for filtering.
_SYSLOG_PRIORITY: Final[dict[int, int]] = {
    logging.DEBUG: 7,     # debug
    logging.INFO: 6,      # info
    logging.WARNING: 4,   # warning
    logging.ERROR: 3,     # err
    logging.CRITICAL: 2,  # crit
}


def _running_under_systemd() -> bool:
    """Detect whether we're being supervised by systemd.

    systemd sets ``INVOCATION_ID`` for every spawned unit and exposes
    ``JOURNAL_STREAM`` when stdout/stderr are connected directly to the
    journal. Either is sufficient evidence.
    """
    return bool(os.environ.get("INVOCATION_ID")) or bool(
        os.environ.get("JOURNAL_STREAM")
    )


class _JournalFormatter(logging.Formatter):
    """Render log records with a ``<priority>`` prefix for journald.

    Strips the leading timestamp (journald has its own) and prepends a
    syslog priority so ``journalctl -p warning`` etc. filter correctly.
    """

    def __init__(self) -> None:
        super().__init__(LOG_FORMAT_JOURNAL)

    def format(self, record: logging.LogRecord) -> str:
        prio = _SYSLOG_PRIORITY.get(record.levelno, 6)
        return f"<{prio}>" + super().format(record)


def configure_logging(level: int | None = None) -> None:
    """Configure the root logger with the project's standard format.

    Auto-detects systemd: under a unit, log lines get a syslog priority
    prefix and drop their timestamp (the journal adds both). Outside
    systemd, you get a human-friendly timestamped format on stderr.

    Safe to call multiple times - only configures the root logger if
    no handlers are attached yet.
    """
    root = logging.getLogger()
    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stderr)
    if _running_under_systemd():
        handler.setFormatter(_JournalFormatter())
    else:
        handler.setFormatter(logging.Formatter(LOG_FORMAT))

    root.addHandler(handler)
    root.setLevel(level if level is not None else LOG_LEVEL)
