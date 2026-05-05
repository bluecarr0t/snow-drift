"""Main entry point for Snow Drift.

Wires every subsystem together and runs the update loop:

    sensors → mood_engine → wind_algorithm → fan_controller
                                          → oled_display

Each subsystem fails soft on init, so a missing sensor (or a
non-Pi development environment) only logs a warning - the loop keeps
running with cached defaults. ``Ctrl+C`` and ``SIGTERM`` both trigger a
clean shutdown that turns every fan off and clears the OLED.

Hardware bring-up (single-fan breadboard, Pi 5): see ``HARDWARE_SETUP.md``
at the repo root.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from types import FrameType
from typing import Optional

from snow_drift import config
from snow_drift.fan_controller import FanController
from snow_drift.mood_engine import MoodEngine
from snow_drift.oled_display import StatusDisplay
from snow_drift.runtime_settings import RuntimeSettings
from snow_drift.sensors.environment import EnvironmentSensor
from snow_drift.sensors.light import LightSensor
from snow_drift.sensors.pir import PIRSensor
from snow_drift.sensors.poller import SensorPoller
from snow_drift.web import SharedState, WebServer
from snow_drift.wind_algorithm import WindAlgorithm

# Web UI configuration. Bind to all interfaces by default so the piece
# is reachable from any device on the local network. Override with
# SNOW_DRIFT_WEB_HOST / SNOW_DRIFT_WEB_PORT env vars (handy for local dev).
WEB_HOST: str = os.environ.get("SNOW_DRIFT_WEB_HOST", "0.0.0.0")
WEB_PORT: int = int(os.environ.get("SNOW_DRIFT_WEB_PORT", "8080"))

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
    poller: Optional[SensorPoller] = None
    web_server: Optional[WebServer] = None

    try:
        fan_controller = FanController()
        oled = StatusDisplay()
        pir = PIRSensor(config.PIR_PIN)
        env_sensor = EnvironmentSensor()
        light_sensor = LightSensor()
        mood_engine = MoodEngine()
        wind_algo = WindAlgorithm(num_fans=len(config.FAN_PINS))
        settings = RuntimeSettings()
        shared_state = SharedState()

        # All I²C / GPIO reads happen on a background thread so a slow
        # sensor (especially the BME688's gas reading) cannot stall the
        # 25 Hz fan update loop.
        poller = SensorPoller(pir, env_sensor, light_sensor)
        poller.start()

        # Local web UI runs in its own daemon thread. Failure to start
        # (e.g. FastAPI missing in dev) logs a warning and is otherwise
        # silent - the rest of the system is unaffected.
        web_server = WebServer(shared_state, settings, host=WEB_HOST, port=WEB_PORT)
        web_server.start()

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

            snap = poller.latest()

            mood_engine.update_presence(
                snap.motion, force_awake=settings.get_force_awake()
            )
            mood_engine.update_environment(
                dt,
                temp_c=snap.env["temp_c"] if snap.env_available else None,
                humidity=snap.env["humidity"] if snap.env_available else None,
                lux=snap.lux if snap.light_available else None,
            )

            mood_params = mood_engine.get_wind_params()
            # Apply runtime master intensity multiplier. The wind
            # algorithm clamps the final per-fan output anyway, so >1.0
            # boosts the piece's energy until physical saturation.
            intensity = settings.get_intensity_multiplier()
            mood_params = dict(mood_params)
            mood_params["base_intensity"] *= intensity

            # Apply forced-pattern override (if any). The wind algorithm
            # cross-fades over PATTERN_FADE_SECONDS, so flipping this on
            # the web UI doesn't snap the piece between styles.
            forced_pattern = settings.get_forced_pattern()
            if forced_pattern is not None:
                mood_params["pattern"] = forced_pattern

            algo_speeds = wind_algo.step(dt, mood_params)

            # Manual override from the web UI takes precedence when set.
            override = settings.get_manual_fan_speeds()
            if override is not None:
                # Pad / truncate to match the configured fan count so a
                # mistakenly-sized request can't crash the loop.
                num = len(algo_speeds)
                fan_speeds = list(override[:num]) + [0.0] * max(0, num - len(override))
            else:
                fan_speeds = algo_speeds

            fan_controller.set_all(fan_speeds)

            temp_f = snap.env["temp_c"] * 9.0 / 5.0 + 32.0

            # Publish a fresh snapshot every tick for the web UI.
            shared_state.publish(
                {
                    "fan_speeds": fan_speeds,
                    "algo_fan_speeds": algo_speeds,
                    "motion": snap.motion,
                    "presence_state": mood_engine.presence_state,
                    "uptime_seconds": now - start_monotonic,
                    "env": {
                        "temperature_c": snap.env["temp_c"],
                        "temperature_f": temp_f,
                        "humidity": snap.env["humidity"],
                        "pressure": snap.env.get("pressure"),
                        "gas": snap.env.get("gas"),
                        "lux": snap.lux,
                        "env_available": snap.env_available,
                        "light_available": snap.light_available,
                        "env_age_s": snap.env_age_s,
                        "light_age_s": snap.light_age_s,
                    },
                    "mood": {
                        "label": mood_params["mood_label"],
                        "base_intensity": mood_params["base_intensity"],
                        "gust_rate": mood_params["gust_rate"],
                        "visibility_factor": mood_params["visibility_factor"],
                        "baseline_intensity": mood_engine.baseline_intensity,
                        "baseline_chaos": mood_engine.baseline_chaos,
                    },
                    "pattern": {
                        # The pattern actually driving the fans right now
                        # (after cross-fade settles this equals the requested).
                        "active": wind_algo.current_pattern,
                        # What the mood engine would pick if not overridden.
                        "mood_selected": mood_engine.current_pattern,
                        # The runtime override (None means auto).
                        "forced": forced_pattern,
                        "transitioning": wind_algo.transitioning,
                    },
                }
            )

            if now - last_oled_update > 1.0 / config.OLED_UPDATE_HZ:
                oled.render(
                    {
                        "fan_speeds": fan_speeds,
                        "temperature_f": temp_f,
                        "humidity": snap.env["humidity"],
                        "lux": snap.lux,
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
        # Stop the web server first so its handlers can't hold
        # references to about-to-be-released resources.
        if web_server is not None:
            try:
                web_server.stop()
            except Exception:
                logger.exception("web server stop failed")
        # Stop the poller before tearing down its underlying sensors so
        # the worker thread doesn't see a half-closed device.
        if poller is not None:
            try:
                poller.stop()
            except Exception:
                logger.exception("sensor poller stop failed")
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
