"""Bring-up test #4: read every sensor for 30 seconds.

Useful for confirming each sensor returns plausible values before
integrating with the wind algorithm. Each sensor is independent - if
one fails to init, the others still report.

Run with::

    python -m snow_drift.tests.test_sensors
"""

from __future__ import annotations

import logging
import sys
import time

from snow_drift import config
from snow_drift.sensors.environment import EnvironmentSensor
from snow_drift.sensors.light import LightSensor
from snow_drift.sensors.pir import PIRSensor

logger = logging.getLogger(__name__)


def main() -> int:
    config.configure_logging()
    logger.info("Sensor test: 30 seconds of continuous reads")

    pir = PIRSensor(config.PIR_PIN)
    env = EnvironmentSensor()
    light = LightSensor()

    logger.info(
        "Availability: PIR=%s BME688=%s BH1750=%s",
        pir.available,
        env.available,
        light.available,
    )

    end = time.time() + 30.0
    try:
        while time.time() < end:
            motion = pir.is_motion_detected()
            reading = env.read()
            lux = light.read()
            print(
                f"motion={motion!s:5}  "
                f"T={reading['temp_c']:5.1f}C  "
                f"RH={reading['humidity']:5.1f}%  "
                f"P={reading['pressure']:7.1f}hPa  "
                f"gas={reading['gas']:8.0f}Ω  "
                f"lux={lux:7.1f}",
                flush=True,
            )
            time.sleep(0.5)
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted")
        return 130
    finally:
        pir.cleanup()


if __name__ == "__main__":
    sys.exit(main())
