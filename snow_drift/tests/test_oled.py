"""Bring-up test #3: verify the SSD1306 OLED.

Renders the standard Snow Drift status layout with animated fake fan
speeds for 15 seconds. If the display stays dark, check that I2C is
enabled (``sudo raspi-config``) and that ``i2cdetect -y 1`` shows
``0x3C``.

Run with::

    python -m snow_drift.tests.test_oled
"""

from __future__ import annotations

import logging
import math
import sys
import time

from snow_drift import config
from snow_drift.oled_display import StatusDisplay

logger = logging.getLogger(__name__)


def main() -> int:
    config.configure_logging()
    display = StatusDisplay()

    if not display.available:
        logger.error(
            "OLED not available - check I2C is enabled and 0x%02X is on "
            "the bus (i2cdetect -y 1).",
            config.OLED_ADDRESS,
        )
        return 1

    logger.info("OLED working. Animating test pattern for 15s.")

    start = time.time()
    duration = 15.0
    try:
        while time.time() - start < duration:
            t = time.time() - start
            speeds = [
                0.5 + 0.5 * math.sin(t + i * math.pi / 2) for i in range(4)
            ]
            display.render(
                {
                    "fan_speeds": speeds,
                    "temperature_f": 72.0,
                    "humidity": 45.0,
                    "lux": 240.0,
                    "presence_state": "AWAKE",
                    "mood_label": "Test",
                    "uptime_seconds": t,
                }
            )
            time.sleep(1.0 / config.OLED_UPDATE_HZ)
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted")
        return 130
    finally:
        display.clear()


if __name__ == "__main__":
    sys.exit(main())
