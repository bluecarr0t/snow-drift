"""PWM control of the four 5V fans via IRLZ44N MOSFETs."""

from __future__ import annotations

import logging
import time
from typing import Optional, Sequence

from snow_drift import config

logger = logging.getLogger(__name__)


class FanController:
    """Drive four PWM fans with graceful no-Pi fallback.

    Each fan is owned by a ``gpiozero.PWMOutputDevice`` whose duty cycle
    is the fan's speed in ``[0.0, 1.0]``. Startup is staggered to avoid
    an inrush-current spike on the shared 5V rail.
    """

    def __init__(
        self,
        pins: Sequence[int] = config.FAN_PINS,
        pwm_frequency: int = config.PWM_FREQUENCY,
        startup_stagger: float = config.FAN_STARTUP_STAGGER_SECONDS,
    ) -> None:
        self.pins: list[int] = list(pins)
        self._frequency = pwm_frequency
        self._devices: list[Optional[object]] = [None] * len(self.pins)
        self._speeds: list[float] = [0.0] * len(self.pins)
        self._available = False

        try:
            from gpiozero import Device, PWMOutputDevice

            for idx, pin in enumerate(self.pins):
                device = PWMOutputDevice(
                    pin, frequency=pwm_frequency, initial_value=0.0
                )
                self._devices[idx] = device
                if idx == 0:
                    # Log the resolved pin factory once. On Pi 5 we want
                    # ``LGPIOFactory``; a software/mock factory means
                    # PWM_FREQUENCY won't be respected by the hardware.
                    factory = type(Device.pin_factory).__name__ if Device.pin_factory else "?"
                    logger.info("gpiozero pin factory: %s", factory)
                logger.info(
                    "Fan %d initialised on GPIO %d @ %d Hz",
                    idx + 1,
                    pin,
                    pwm_frequency,
                )
                # Stagger init to spread any initial current draw.
                if startup_stagger > 0 and idx < len(self.pins) - 1:
                    time.sleep(startup_stagger)
            self._available = True
        except Exception as exc:  # pragma: no cover - hardware specific
            logger.warning(
                "Fan PWM unavailable (running in stub mode): %s", exc
            )
            for idx, dev in enumerate(self._devices):
                if dev is not None:
                    try:
                        getattr(dev, "close", lambda: None)()
                    except Exception:
                        pass
                self._devices[idx] = None

    @property
    def available(self) -> bool:
        """Whether real PWM hardware is attached."""
        return self._available

    @staticmethod
    def _clamp(value: float) -> float:
        if value < 0.0:
            return 0.0
        if value > 1.0:
            return 1.0
        return value

    def set_speed(self, fan_index: int, speed: float) -> None:
        """Set a single fan's speed.

        Args:
            fan_index: Zero-based fan index (0 through ``len(pins) - 1``).
            speed: Duty cycle in ``[0.0, 1.0]``. Values are clamped.
        """
        if not 0 <= fan_index < len(self.pins):
            raise IndexError(f"Fan index {fan_index} out of range")
        speed = self._clamp(speed)
        self._speeds[fan_index] = speed
        device = self._devices[fan_index]
        if device is None:
            return
        try:
            device.value = speed  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - hardware specific
            logger.warning(
                "Fan %d set_speed(%.2f) failed: %s",
                fan_index + 1,
                speed,
                exc,
            )

    def set_all(self, speeds: Sequence[float]) -> None:
        """Set all fan speeds from a sequence of floats.

        Length must match ``self.pins``. Out-of-range values are clamped.
        """
        if len(speeds) != len(self.pins):
            raise ValueError(
                f"Expected {len(self.pins)} speeds, got {len(speeds)}"
            )
        for idx, speed in enumerate(speeds):
            self.set_speed(idx, speed)

    def get_speeds(self) -> list[float]:
        """Return a copy of the current commanded speeds."""
        return list(self._speeds)

    def pwm_readback(self, fan_index: int) -> Optional[float]:
        """Return ``PWMOutputDevice.value`` for bring-up diagnostics, or ``None``."""
        if not 0 <= fan_index < len(self._devices):
            return None
        device = self._devices[fan_index]
        if device is None:
            return None
        raw = getattr(device, "value", None)
        if raw is None:
            return None
        return float(raw)

    def stop_all(self) -> None:
        """Set all fans to 0% duty cycle."""
        self.set_all([0.0] * len(self.pins))

    def cleanup(self) -> None:
        """Stop all fans and release PWM resources.

        Safe to call from ``finally`` blocks and signal handlers; never
        raises.
        """
        try:
            self.stop_all()
        except Exception as exc:  # pragma: no cover
            logger.debug("stop_all during cleanup raised: %s", exc)

        for idx, device in enumerate(self._devices):
            if device is None:
                continue
            try:
                close = getattr(device, "close", None)
                if callable(close):
                    close()
            except Exception as exc:  # pragma: no cover
                logger.debug("Fan %d close raised: %s", idx + 1, exc)
            finally:
                self._devices[idx] = None
        self._available = False
