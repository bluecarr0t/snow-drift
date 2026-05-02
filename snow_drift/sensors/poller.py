"""Background thread that polls every sensor at a fixed cadence.

The main loop wants to read fresh sensor data every tick without ever
blocking on I²C. The slowest read is the BME688 gas-resistance reading
(~150 ms on the first call while the heater warms up); even at steady
state, three I²C transactions per loop noticeably jitters a 25 Hz
update rate.

This module hides all that behind a single thread that:

- Calls ``pir.is_motion_detected()``, ``env.read()``, ``light.read()``
  on a fixed schedule (default :data:`config.PIR_READ_HZ`).
- Stores the latest results behind a lock and an ``Event`` so consumers
  can block-wait or poll-read without races.
- Surfaces per-sensor freshness so the mood engine can freeze any
  baseline whose underlying sensor has gone stale.

Each underlying sensor wrapper already implements its own caching at
the configured read intervals, so calling them at the poll rate is
cheap when no real I/O is due.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from snow_drift import config
from snow_drift.sensors.environment import EnvironmentReading, EnvironmentSensor
from snow_drift.sensors.light import LightSensor
from snow_drift.sensors.pir import PIRSensor

logger = logging.getLogger(__name__)


class SensorSnapshot:
    """Immutable view of the most recent sensor readings.

    Includes per-channel freshness so callers can decide whether to
    trust each value (e.g. don't smooth toward a temperature that came
    from a sensor we lost contact with 10 minutes ago).
    """

    __slots__ = (
        "motion",
        "env",
        "lux",
        "env_available",
        "light_available",
        "env_age_s",
        "light_age_s",
    )

    def __init__(
        self,
        motion: bool,
        env: EnvironmentReading,
        lux: float,
        env_available: bool,
        light_available: bool,
        env_age_s: float,
        light_age_s: float,
    ) -> None:
        self.motion = motion
        self.env = env
        self.lux = lux
        self.env_available = env_available
        self.light_available = light_available
        self.env_age_s = env_age_s
        self.light_age_s = light_age_s


class SensorPoller:
    """Owns a background thread that keeps sensor readings fresh.

    Lifecycle::

        poller = SensorPoller(pir, env_sensor, light_sensor)
        poller.start()
        try:
            while running:
                snap = poller.latest()
                ...
        finally:
            poller.stop()

    The poller is safe to ``stop()`` even if ``start()`` hasn't been
    called or the underlying thread has already exited.
    """

    # Cap how stale a reading can be before we declare it unavailable
    # to consumers. Generous default: 4× the slowest read interval.
    STALENESS_MULTIPLIER: float = 4.0

    def __init__(
        self,
        pir: PIRSensor,
        env: EnvironmentSensor,
        light: LightSensor,
        poll_hz: float = config.PIR_READ_HZ,
    ) -> None:
        self._pir = pir
        self._env = env
        self._light = light
        self._period = 1.0 / max(poll_hz, 0.1)

        # Pre-seed with whatever the cached defaults are so the first
        # ``latest()`` call after start() always returns something sane.
        self._motion: bool = False
        self._env_reading: EnvironmentReading = env.read()
        self._lux: float = light.read()
        now = time.monotonic()
        self._env_last_ok: float = now if env.available else 0.0
        self._light_last_ok: float = now if light.available else 0.0

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Launch the background polling thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="snow-drift-sensors", daemon=True
        )
        self._thread.start()
        logger.info(
            "SensorPoller started (poll=%.1f Hz)", 1.0 / self._period
        )

    def stop(self, timeout: float = 2.0) -> None:
        """Signal the polling thread to exit and wait for it."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning("SensorPoller thread did not stop within %.1fs", timeout)
        self._thread = None

    # ------------------------------------------------------------------
    # Polling worker
    # ------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                motion = self._pir.is_motion_detected()
            except Exception:  # pragma: no cover - hardware specific
                logger.exception("PIR poll raised; treating as no motion")
                motion = False

            try:
                env_reading = self._env.read()
                env_ok = self._env.available
            except Exception:  # pragma: no cover - hardware specific
                logger.exception("Environment poll raised; keeping last value")
                env_reading = self._env_reading
                env_ok = False

            try:
                lux = self._light.read()
                light_ok = self._light.available
            except Exception:  # pragma: no cover - hardware specific
                logger.exception("Light poll raised; keeping last value")
                lux = self._lux
                light_ok = False

            now = time.monotonic()
            with self._lock:
                self._motion = motion
                self._env_reading = env_reading
                self._lux = lux
                if env_ok:
                    self._env_last_ok = now
                if light_ok:
                    self._light_last_ok = now

            # Use Event.wait so stop() returns promptly instead of
            # blocking for up to one full poll period.
            self._stop_event.wait(self._period)

    # ------------------------------------------------------------------
    # Consumer API
    # ------------------------------------------------------------------
    def latest(self) -> SensorSnapshot:
        """Return the most recent readings as an immutable snapshot.

        Per-channel ``available`` flags combine the wrapper's underlying
        availability with a staleness check: if the last successful read
        is older than ``STALENESS_MULTIPLIER × read_interval``, the
        channel is reported as unavailable so the mood engine freezes
        rather than smoothing toward stale data.
        """
        now = time.monotonic()
        env_stale_after = (
            self.STALENESS_MULTIPLIER * config.BME688_READ_INTERVAL_SECONDS
        )
        light_stale_after = (
            self.STALENESS_MULTIPLIER * config.BH1750_READ_INTERVAL_SECONDS
        )
        with self._lock:
            env_age = now - self._env_last_ok if self._env_last_ok > 0 else float("inf")
            light_age = (
                now - self._light_last_ok if self._light_last_ok > 0 else float("inf")
            )
            return SensorSnapshot(
                motion=self._motion,
                env=dict(self._env_reading),  # shallow copy
                lux=self._lux,
                env_available=self._env.available and env_age < env_stale_after,
                light_available=self._light.available and light_age < light_stale_after,
                env_age_s=env_age,
                light_age_s=light_age,
            )
