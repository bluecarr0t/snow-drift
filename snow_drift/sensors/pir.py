"""HC-SR501 PIR motion sensor wrapper."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PIRSensor:
    """Thin wrapper around an HC-SR501 connected to a Pi GPIO pin.

    Falls back to a no-op stub when ``gpiozero`` is unavailable or the
    pin can't be opened (eg. when running tests on a non-Pi machine).
    """

    def __init__(self, pin: int) -> None:
        self.pin = pin
        self._device: Optional[object] = None
        self._available = False
        try:
            from gpiozero import MotionSensor

            self._device = MotionSensor(pin)
            self._available = True
            logger.info("PIR sensor initialised on GPIO %d", pin)
        except Exception as exc:  # pragma: no cover - hardware specific
            logger.warning("PIR sensor unavailable on GPIO %d: %s", pin, exc)

    @property
    def available(self) -> bool:
        """Whether the underlying GPIO device was successfully opened."""
        return self._available

    def is_motion_detected(self) -> bool:
        """Return ``True`` if the PIR is currently triggered.

        Returns ``False`` if the sensor failed to initialise so the rest
        of the system can keep running in a calm baseline state.
        """
        if not self._available or self._device is None:
            return False
        try:
            return bool(getattr(self._device, "motion_detected", False))
        except Exception as exc:  # pragma: no cover - hardware specific
            logger.warning("PIR read failed: %s", exc)
            return False

    def cleanup(self) -> None:
        """Release the underlying GPIO resource."""
        if self._device is None:
            return
        try:
            close = getattr(self._device, "close", None)
            if callable(close):
                close()
        except Exception as exc:  # pragma: no cover - hardware specific
            logger.debug("PIR cleanup error: %s", exc)
        finally:
            self._device = None
            self._available = False
