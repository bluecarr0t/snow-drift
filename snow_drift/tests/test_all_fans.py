"""Bring-up test #2: cycle through all four fans.

Each fan runs at 50% for 3 seconds in sequence. Confirms every channel
is wired correctly and that no two fans are crossed.

Run with::

    python -m snow_drift.tests.test_all_fans
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
    logger.info("All-fans test: pins=%s", config.FAN_PINS)
    fans = FanController()

    if not fans.available:
        logger.error("Fan PWM hardware not available")
        fans.cleanup()
        return 1

    try:
        for idx, pin in enumerate(config.FAN_PINS):
            logger.info("→ Fan %d (GPIO %d) at 50%% for 3s", idx + 1, pin)
            fans.stop_all()
            fans.set_speed(idx, 0.5)
            time.sleep(3.0)

        logger.info("All four fans tested. Stopping.")
        fans.stop_all()
        time.sleep(0.5)
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted")
        return 130
    finally:
        fans.cleanup()


if __name__ == "__main__":
    sys.exit(main())
