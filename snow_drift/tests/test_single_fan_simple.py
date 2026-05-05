"""Minimal single-fan smoke test: **full speed until Ctrl+C**.

Uses :class:`snow_drift.fan_controller.FanController` on **Fan 1**
(:data:`config.FAN_PINS[0]`, BCM **18**) at the project PWM frequency so
behavior matches the rest of Snow Drift.

Run from the repo root::

    python3 -m snow_drift.tests.test_single_fan_simple

or::

    python3 test_single_fan_simple.py
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
    pin = config.FAN_PINS[0]
    logger.info(
        "Single-fan SIMPLE: full speed on Fan 1 (BCM %d). Ctrl+C to stop.", pin
    )

    fans = FanController(pins=[pin])
    if not fans.available:
        logger.error("Fan PWM not available — run on the Pi with gpiozero + lgpio.")
        fans.cleanup()
        return 1

    fans.set_speed(0, 1.0)
    print("Fan ON at 100%. Press Ctrl+C to stop.", flush=True)

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Interrupted — turning fan off.")
    finally:
        fans.cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
