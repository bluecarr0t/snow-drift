"""Bring-up test #5: dry-run of the full pipeline.

Runs the same sensors → mood → wind → display flow as ``main.py`` but
prints the commanded fan speeds to the console instead of driving the
MOSFETs. Lets you verify the wind algorithm and mood engine are
behaving without requiring physical fans.

Run with::

    python -m snow_drift.tests.test_full_system
"""

from __future__ import annotations

import logging
import sys
import time

from snow_drift import config
from snow_drift.mood_engine import MoodEngine
from snow_drift.oled_display import StatusDisplay
from snow_drift.sensors.environment import EnvironmentSensor
from snow_drift.sensors.light import LightSensor
from snow_drift.sensors.pir import PIRSensor
from snow_drift.sensors.poller import SensorPoller
from snow_drift.wind_algorithm import WindAlgorithm

logger = logging.getLogger(__name__)


def _bar(value: float, width: int = 20) -> str:
    """Render a 0..1 value as a unicode-free ASCII bar."""
    filled = max(0, min(width, int(round(value * width))))
    return "[" + "#" * filled + "." * (width - filled) + "]"


def main() -> int:
    config.configure_logging()
    logger.info("Full-system DRY RUN - fans will NOT spin.")

    pir = PIRSensor(config.PIR_PIN)
    env_sensor = EnvironmentSensor()
    light_sensor = LightSensor()
    oled = StatusDisplay()
    mood_engine = MoodEngine()
    wind_algo = WindAlgorithm(num_fans=len(config.FAN_PINS))
    poller = SensorPoller(pir, env_sensor, light_sensor)
    poller.start()

    target_period = 1.0 / config.UPDATE_RATE_HZ
    last_time = time.monotonic()
    last_print = 0.0
    last_oled_update = 0.0
    start_time = last_time

    try:
        while True:
            now = time.monotonic()
            dt = now - last_time
            last_time = now

            snap = poller.latest()

            mood_engine.update_presence(snap.motion)
            mood_engine.update_environment(
                dt,
                temp_c=snap.env["temp_c"] if snap.env_available else None,
                humidity=snap.env["humidity"] if snap.env_available else None,
                lux=snap.lux if snap.light_available else None,
            )
            mood_params = mood_engine.get_wind_params()
            speeds = wind_algo.step(dt, mood_params)

            if now - last_oled_update > 1.0 / config.OLED_UPDATE_HZ:
                temp_f = snap.env["temp_c"] * 9.0 / 5.0 + 32.0
                oled.render(
                    {
                        "fan_speeds": speeds,
                        "temperature_f": temp_f,
                        "humidity": snap.env["humidity"],
                        "lux": snap.lux,
                        "presence_state": mood_engine.presence_state,
                        "mood_label": mood_params["mood_label"],
                        "uptime_seconds": now - start_time,
                    }
                )
                last_oled_update = now

            # Throttle console output to ~2 Hz so it's readable.
            if now - last_print > 0.5:
                pat = wind_algo.current_pattern
                if wind_algo.transitioning:
                    pat = f"{pat}*"
                line = (
                    f"{mood_engine.presence_state:8} "
                    f"{mood_params['mood_label']:14} "
                    f"pat={pat:7} "
                    f"int={mood_params['base_intensity']:.2f} "
                    f"gust={mood_params['gust_rate']:.2f} "
                    f"vis={mood_params['visibility_factor']:.2f}  "
                )
                for idx, s in enumerate(speeds):
                    line += f"F{idx + 1}{_bar(s, 10)} "
                print(line, flush=True)
                last_print = now

            elapsed = time.monotonic() - now
            time.sleep(max(0.0, target_period - elapsed))
    except KeyboardInterrupt:
        logger.info("Interrupted")
        return 0
    finally:
        poller.stop()
        oled.clear()
        pir.cleanup()


if __name__ == "__main__":
    sys.exit(main())
