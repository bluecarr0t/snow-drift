"""Central configuration for Snow Drift.

All "magic numbers" live here so the piece can be tuned without hunting
through the rest of the codebase. Constants are grouped by subsystem.
"""

from __future__ import annotations

import logging
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

# Smoothing factor for environment-driven baselines (0-1, smaller = slower).
ENV_SMOOTHING_ALPHA: Final[float] = 0.05

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


def configure_logging(level: int | None = None) -> None:
    """Configure the root logger with the project's standard format.

    Safe to call multiple times - only configures the root logger if
    no handlers are attached yet.
    """
    if logging.getLogger().handlers:
        return
    logging.basicConfig(level=level if level is not None else LOG_LEVEL,
                        format=LOG_FORMAT)
