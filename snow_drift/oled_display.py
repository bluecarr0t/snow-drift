"""SSD1306 OLED status display.

Shows the live state of the piece in a tight 128x64 layout:

  ┌────────────────────────────┐
  │ Snow Drift   02:14:33      │  title + uptime
  │                            │
  │ F1: 45%      F3: 38%       │  fan speeds 2x2 grid
  │ F2: 52%      F4: 41%       │
  │                            │
  │ T:72F H:45% Lux:240        │  sensor values
  │ State:AWAKE Mood:Active    │  system state
  └────────────────────────────┘

If the OLED isn't connected we log a warning once and turn ``render``
into a no-op so the rest of the system keeps running.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence, TypedDict

from snow_drift import config

logger = logging.getLogger(__name__)


class StatusState(TypedDict, total=False):
    """Snapshot of the values rendered to the OLED.

    All fields are optional so the display gracefully handles missing
    pieces of state during early init.
    """

    fan_speeds: Sequence[float]
    temperature_f: float
    humidity: float
    lux: float
    presence_state: str
    mood_label: str
    uptime_seconds: float


class StatusDisplay:
    """Render Snow Drift status to a 128x64 SSD1306.

    The hardware/Pillow imports are scoped to ``__init__`` so the class
    can be imported on a non-Pi development machine.
    """

    def __init__(self) -> None:
        self._device: Optional[Any] = None
        self._image_module: Optional[Any] = None
        self._draw_module: Optional[Any] = None
        self._font: Optional[Any] = None
        self._available = False

        try:
            from luma.core.interface.serial import i2c
            from luma.oled.device import ssd1306
            from PIL import Image, ImageDraw, ImageFont

            serial = i2c(port=config.I2C_BUS, address=config.OLED_ADDRESS)
            self._device = ssd1306(
                serial,
                width=config.OLED_WIDTH,
                height=config.OLED_HEIGHT,
            )
            self._image_module = Image
            self._draw_module = ImageDraw
            try:
                self._font = ImageFont.load_default()
            except Exception:  # pragma: no cover
                self._font = None
            self._available = True
            logger.info(
                "OLED initialised at I2C 0x%02X (%dx%d)",
                config.OLED_ADDRESS,
                config.OLED_WIDTH,
                config.OLED_HEIGHT,
            )
        except Exception as exc:  # pragma: no cover - hardware specific
            logger.warning("OLED unavailable, render() will be no-op: %s", exc)

    @property
    def available(self) -> bool:
        """Whether the display was successfully opened."""
        return self._available

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        seconds = max(0, int(seconds))
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    @staticmethod
    def _fmt_pct(value: float) -> str:
        return f"{int(round(value * 100))}%"

    def render(self, state_dict: StatusState) -> None:
        """Render a frame to the OLED.

        The state dict is the same one ``main.py`` builds each tick.
        Missing keys are tolerated so this is safe to call before all
        sensors have produced their first reading.
        """
        if (
            not self._available
            or self._device is None
            or self._image_module is None
            or self._draw_module is None
        ):
            return

        try:
            fan_speeds: Sequence[float] = state_dict.get("fan_speeds", [0.0] * 4)
            if len(fan_speeds) < 4:
                fan_speeds = list(fan_speeds) + [0.0] * (4 - len(fan_speeds))

            temp_f = float(state_dict.get("temperature_f", 0.0))
            humidity = float(state_dict.get("humidity", 0.0))
            lux = float(state_dict.get("lux", 0.0))
            presence = str(state_dict.get("presence_state", "?"))
            mood = str(state_dict.get("mood_label", "?"))
            uptime = float(state_dict.get("uptime_seconds", 0.0))

            image = self._image_module.new(
                "1", (config.OLED_WIDTH, config.OLED_HEIGHT)
            )
            draw = self._draw_module.Draw(image)
            font = self._font

            # Row 1 - title + uptime
            draw.text((0, 0), "Snow Drift", font=font, fill=255)
            draw.text((72, 0), self._format_uptime(uptime), font=font, fill=255)

            # Rows 2-3 - fans in a 2x2 grid (F1/F3 on row 1, F2/F4 on row 2)
            draw.text(
                (0, 16),
                f"F1:{self._fmt_pct(fan_speeds[0])}",
                font=font,
                fill=255,
            )
            draw.text(
                (64, 16),
                f"F3:{self._fmt_pct(fan_speeds[2])}",
                font=font,
                fill=255,
            )
            draw.text(
                (0, 28),
                f"F2:{self._fmt_pct(fan_speeds[1])}",
                font=font,
                fill=255,
            )
            draw.text(
                (64, 28),
                f"F4:{self._fmt_pct(fan_speeds[3])}",
                font=font,
                fill=255,
            )

            # Row 4 - sensors
            sensor_line = (
                f"T:{int(round(temp_f))}F "
                f"H:{int(round(humidity))}% "
                f"Lx:{int(round(lux))}"
            )
            draw.text((0, 44), sensor_line[:21], font=font, fill=255)

            # Row 5 - system state
            state_line = f"{presence[:5]} {mood[:14]}"
            draw.text((0, 54), state_line[:21], font=font, fill=255)

            self._device.display(image)
        except Exception as exc:  # pragma: no cover - hardware specific
            logger.warning("OLED render failed: %s", exc)

    def clear(self) -> None:
        """Blank the screen on shutdown. Never raises."""
        if not self._available or self._device is None:
            return
        try:
            self._device.clear()
        except Exception as exc:  # pragma: no cover
            logger.debug("OLED clear failed: %s", exc)
