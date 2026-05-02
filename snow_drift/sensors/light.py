"""BH1750 ambient light sensor wrapper."""

from __future__ import annotations

import logging
import time
from typing import Optional

from snow_drift import config

logger = logging.getLogger(__name__)


class LightSensor:
    """BH1750 lux reader with caching and graceful degradation.

    Same caching pattern as :class:`EnvironmentSensor`: re-reads at
    :data:`config.BH1750_READ_INTERVAL_SECONDS` and serves cached
    values in between.
    """

    def __init__(self) -> None:
        self.cached_lux: float = 100.0  # safe indoor default
        self.last_read_time: float = 0.0

        self._sensor: Optional[object] = None
        self._available = False

        try:
            import board  # type: ignore[import-not-found]
            import busio  # type: ignore[import-not-found]
            import adafruit_bh1750  # type: ignore[import-not-found]

            i2c = busio.I2C(board.SCL, board.SDA)
            self._sensor = adafruit_bh1750.BH1750(
                i2c, address=config.BH1750_ADDRESS
            )
            self._available = True
            logger.info(
                "BH1750 initialised at I2C 0x%02X", config.BH1750_ADDRESS
            )
        except Exception as exc:  # pragma: no cover - hardware specific
            logger.warning("BH1750 unavailable, using defaults: %s", exc)

    @property
    def available(self) -> bool:
        """Whether the underlying sensor responded during init."""
        return self._available

    def read(self) -> float:
        """Return the latest lux reading (cached between intervals)."""
        now = time.time()
        if (
            self._available
            and self._sensor is not None
            and now - self.last_read_time >= config.BH1750_READ_INTERVAL_SECONDS
        ):
            try:
                self.cached_lux = float(self._sensor.lux)  # type: ignore[attr-defined]
                self.last_read_time = now
                logger.debug("BH1750: %.1f lux", self.cached_lux)
            except Exception as exc:  # pragma: no cover - hardware specific
                logger.warning("BH1750 read failed (using cached): %s", exc)
                self.last_read_time = now

        return self.cached_lux
