"""BME688 environmental sensor (temperature / humidity / pressure / gas).

The BME680 and BME688 share the same I2C protocol, so the well-supported
``adafruit_bme680`` CircuitPython driver works for both.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, TypedDict

from snow_drift import config

logger = logging.getLogger(__name__)


class EnvironmentReading(TypedDict):
    """Snapshot of the BME688 readings."""

    temp_c: float
    humidity: float
    pressure: float
    gas: float


class EnvironmentSensor:
    """BME688 reader with caching and graceful degradation.

    Reads are relatively expensive (gas resistance especially), so we
    only re-read at :data:`config.BME688_READ_INTERVAL_SECONDS` and
    serve cached values in between.
    """

    def __init__(self) -> None:
        self.last_read_time: float = 0.0
        self.cached_temp: float = 22.0     # safe indoor default
        self.cached_humidity: float = 50.0
        self.cached_pressure: float = 1013.0
        self.cached_gas: float = 100_000.0

        self._sensor: Optional[object] = None
        self._available = False

        try:
            import board  # type: ignore[import-not-found]
            import busio  # type: ignore[import-not-found]
            import adafruit_bme680  # type: ignore[import-not-found]

            i2c = busio.I2C(board.SCL, board.SDA)
            self._sensor = adafruit_bme680.Adafruit_BME680_I2C(
                i2c, address=config.BME688_ADDRESS
            )
            self._available = True
            logger.info(
                "BME688 initialised at I2C 0x%02X", config.BME688_ADDRESS
            )
        except Exception as exc:  # pragma: no cover - hardware specific
            logger.warning("BME688 unavailable, using defaults: %s", exc)

    @property
    def available(self) -> bool:
        """Whether the underlying sensor responded during init."""
        return self._available

    def read(self) -> EnvironmentReading:
        """Return the latest environmental snapshot.

        Re-reads the sensor at most once per
        :data:`config.BME688_READ_INTERVAL_SECONDS`; otherwise returns
        the last cached value. On read failure, the cached value is
        retained so the system never crashes from a flaky bus.
        """
        now = time.time()
        if (
            self._available
            and self._sensor is not None
            and now - self.last_read_time >= config.BME688_READ_INTERVAL_SECONDS
        ):
            try:
                self.cached_temp = float(self._sensor.temperature)  # type: ignore[attr-defined]
                self.cached_humidity = float(self._sensor.humidity)  # type: ignore[attr-defined]
                self.cached_pressure = float(self._sensor.pressure)  # type: ignore[attr-defined]
                # gas resistance can be None on the very first read while
                # the heater is warming up.
                gas = self._sensor.gas  # type: ignore[attr-defined]
                if gas is not None:
                    self.cached_gas = float(gas)
                self.last_read_time = now
                logger.debug(
                    "BME688: temp=%.1fC rh=%.1f%% p=%.1fhPa gas=%.0fΩ",
                    self.cached_temp,
                    self.cached_humidity,
                    self.cached_pressure,
                    self.cached_gas,
                )
            except Exception as exc:  # pragma: no cover - hardware specific
                logger.warning("BME688 read failed (using cached): %s", exc)
                self.last_read_time = now  # back off until next interval

        return EnvironmentReading(
            temp_c=self.cached_temp,
            humidity=self.cached_humidity,
            pressure=self.cached_pressure,
            gas=self.cached_gas,
        )

    def temperature_f(self) -> float:
        """Return the cached temperature in Fahrenheit."""
        return self.cached_temp * 9.0 / 5.0 + 32.0
