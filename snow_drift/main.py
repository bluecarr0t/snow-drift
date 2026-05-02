"""Main entry point for Snow Drift.

Wires every subsystem together and runs the update loop:

    sensors → mood_engine → wind_algorithm → fan_controller
                                          → oled_display

Each subsystem fails soft on init, so a missing sensor (or a
non-Pi development environment) only logs a warning - the loop keeps
running with cached defaults. ``Ctrl+C`` and ``SIGTERM`` both trigger a
clean shutdown that turns every fan off and clears the OLED.
"""

from __future__ import annotations

import logging
import signal
import sys
import time
from types import FrameType
from typing import Optional

from snow_drift import config
from snow_drift.fan_controller import FanController
from snow_drift.mood_engine import MoodEngine
from snow_drift.oled_display import StatusDisplay
from snow_drift.sensors.environment import EnvironmentSensor
from snow_drift.sensors.light import LightSensor
from snow_drift.sensors.pir import PIRSensor
from snow_drift.wind_algorithm import WindAlgorithm

logger = logging.getLogger("snow_drift.main")


def _install_signal_handlers() -> dict[str, bool]:
    """Install handlers that flip a shared flag on SIGINT / SIGTERM."""
    flag = {"stop": False}

    def _handler(signum: int, _frame: Optional[FrameType]) -> None:
        logger.info("Received signal %d, shutting down", signum)
        flag["stop"] = True

    signal.signal(signal.SIGINT, _handler)
    try:
        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError):  # pragma: no cover - platform specific
        pass
    return flag


def main() -> int:
    """Run the Snow Drift main loop. Returns a process exit code."""
    config.configure_logging()
    logger.info("Snow Drift starting")

    stop_flag = _install_signal_handlers()
    start_monotonic = time.monotonic()

    fan_controller: Optional[FanController] = None
    oled: Optional[StatusDisplay] = None
    pir: Optional[PIRSensor] = None

    try:
        fan_controller = FanController()
        oled = StatusDisplay()
        pir = PIRSensor(config.PIR_PIN)
        env_sensor = EnvironmentSensor()
        light_sensor = LightSensor()
        mood_engine = MoodEngine()
        wind_algo = WindAlgorithm(num_fans=len(config.FAN_PINS))

        last_time = time.monotonic()
        last_oled_update = 0.0
        target_period = 1.0 / config.UPDATE_RATE_HZ

        logger.info(
            "Entering main loop at %.1f Hz", config.UPDATE_RATE_HZ
        )

        while not stop_flag["stop"]:
            now = time.monotonic()
            dt = now - last_time
            last_time = now

            motion = pir.is_motion_detected()
            env = env_sensor.read()
            lux = light_sensor.read()

            mood_engine.update_presence(motion)
            # Pass ``None`` for sensors that failed to initialise so the
            # corresponding mood baseline freezes instead of drifting
            # toward our cached safe-defaults.
            mood_engine.update_environment(
                dt,
                temp_c=env["temp_c"] if env_sensor.available else None,
                humidity=env["humidity"] if env_sensor.available else None,
                lux=lux if light_sensor.available else None,
            )

            mood_params = mood_engine.get_wind_params()
            fan_speeds = wind_algo.step(dt, mood_params)
            fan_controller.set_all(fan_speeds)

            if now - last_oled_update > 1.0 / config.OLED_UPDATE_HZ:
                oled.render(
                    {
                        "fan_speeds": fan_speeds,
                        "temperature_f": env_sensor.temperature_f(),
                        "humidity": env["humidity"],
                        "lux": lux,
                        "presence_state": mood_engine.presence_state,
                        "mood_label": mood_params["mood_label"],
                        "uptime_seconds": now - start_monotonic,
                    }
                )
                last_oled_update = now

            elapsed = time.monotonic() - now
            time.sleep(max(0.0, target_period - elapsed))

        return 0
    except Exception:
        logger.exception("Fatal error in main loop")
        return 1
    finally:
        if fan_controller is not None:
            try:
                fan_controller.cleanup()
            except Exception:
                logger.exception("fan_controller cleanup failed")
        if oled is not None:
            try:
                oled.clear()
            except Exception:
                logger.exception("oled clear failed")
        if pir is not None:
            try:
                pir.cleanup()
            except Exception:
                logger.exception("pir cleanup failed")
        logger.info("Shutdown complete")


if __name__ == "__main__":
    sys.exit(main())
