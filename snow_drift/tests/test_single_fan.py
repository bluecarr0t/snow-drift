"""Bring-up test #1: verify a single fan responds to PWM.

Run this *first* when you wire up the breadboard. It exercises Fan 1
(GPIO 18) only:

  - ramp 0 → 100% over 5 seconds
  - hold at 100% for 2 seconds
  - ramp 100 → 0 over 5 seconds

Run with::

    python -m snow_drift.tests.test_single_fan
"""

from __future__ import annotations

import logging
import sys
import time

from snow_drift import config
from snow_drift.fan_controller import FanController

logger = logging.getLogger(__name__)


def main() -> int:
    config.configure_logging()
    logger.info("Single-fan test: GPIO %d", config.FAN_PINS[0])
    fans = FanController(pins=[config.FAN_PINS[0]])

    if not fans.available:
        logger.error(
            "Fan PWM hardware not available - is gpiozero installed and "
            "are you on the Pi?"
        )
        fans.cleanup()
        return 1

    try:
        ramp_seconds = 5.0
        steps = 50
        logger.info("Ramping up over %.1fs", ramp_seconds)
        for i in range(steps + 1):
            fans.set_speed(0, i / steps)
            time.sleep(ramp_seconds / steps)

        logger.info("Holding at 100%% for 2s")
        fans.set_speed(0, 1.0)
        time.sleep(2.0)

        logger.info("Ramping down over %.1fs", ramp_seconds)
        for i in range(steps + 1):
            fans.set_speed(0, 1.0 - i / steps)
            time.sleep(ramp_seconds / steps)

        logger.info("Done. If the fan didn't move, check wiring & power.")
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted")
        return 130
    finally:
        fans.cleanup()


if __name__ == "__main__":
    sys.exit(main())
