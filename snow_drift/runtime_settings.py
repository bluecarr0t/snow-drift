"""Live-tunable settings shared between the main loop and the web UI.

The static defaults in :mod:`snow_drift.config` aren't enough for an
installation: at the gallery you want to nudge the master intensity,
keep the piece awake during a viewing, or temporarily pin specific
fan speeds. Those overrides live here so they can be mutated from the
web layer without restarting the service.

Every getter / setter takes the lock; the lock is reentrant so a setter
can read its old value during validation. The whole object is a plain
in-memory thing - nothing is persisted yet (a future improvement is
serialising to ``~/.snow_drift/runtime.json``).
"""

from __future__ import annotations

import logging
import threading
from typing import List, Optional, TypedDict

from snow_drift import config

logger = logging.getLogger(__name__)


class RuntimeSettingsSnapshot(TypedDict):
    """Plain-data view of a :class:`RuntimeSettings` for serialisation."""

    intensity_multiplier: float
    force_awake: bool
    manual_fan_speeds: Optional[List[float]]
    forced_pattern: Optional[str]


class RuntimeSettings:
    """Thread-safe bundle of values the web UI is allowed to mutate."""

    INTENSITY_MIN: float = 0.0
    INTENSITY_MAX: float = 2.0

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._intensity_multiplier: float = 1.0
        self._force_awake: bool = False
        self._manual_fan_speeds: Optional[List[float]] = None
        self._forced_pattern: Optional[str] = None

    # ------------------------------------------------------------------
    # Snapshot / diff
    # ------------------------------------------------------------------
    def snapshot(self) -> RuntimeSettingsSnapshot:
        """Return an immutable view of the current settings."""
        with self._lock:
            return {
                "intensity_multiplier": self._intensity_multiplier,
                "force_awake": self._force_awake,
                "manual_fan_speeds": (
                    list(self._manual_fan_speeds)
                    if self._manual_fan_speeds is not None
                    else None
                ),
                "forced_pattern": self._forced_pattern,
            }

    # ------------------------------------------------------------------
    # Intensity multiplier
    # ------------------------------------------------------------------
    def get_intensity_multiplier(self) -> float:
        with self._lock:
            return self._intensity_multiplier

    def set_intensity_multiplier(self, value: float) -> float:
        clamped = max(self.INTENSITY_MIN, min(self.INTENSITY_MAX, float(value)))
        with self._lock:
            if clamped != self._intensity_multiplier:
                logger.info(
                    "runtime: intensity_multiplier %.2f → %.2f",
                    self._intensity_multiplier,
                    clamped,
                )
            self._intensity_multiplier = clamped
        return clamped

    # ------------------------------------------------------------------
    # Force-awake (prevents PIR-driven sleep)
    # ------------------------------------------------------------------
    def get_force_awake(self) -> bool:
        with self._lock:
            return self._force_awake

    def set_force_awake(self, enabled: bool) -> bool:
        enabled = bool(enabled)
        with self._lock:
            if enabled != self._force_awake:
                logger.info("runtime: force_awake → %s", enabled)
            self._force_awake = enabled
        return enabled

    # ------------------------------------------------------------------
    # Manual fan override
    # ------------------------------------------------------------------
    def get_manual_fan_speeds(self) -> Optional[List[float]]:
        """Return a copy of the override vector, or ``None`` when auto."""
        with self._lock:
            if self._manual_fan_speeds is None:
                return None
            return list(self._manual_fan_speeds)

    def set_manual_fan_speeds(
        self, speeds: Optional[List[float]]
    ) -> Optional[List[float]]:
        """Pin per-fan duty cycles, or pass ``None`` to release control.

        Any caller-supplied list is clamped to ``[0.0, 1.0]`` per element.
        """
        if speeds is None:
            with self._lock:
                if self._manual_fan_speeds is not None:
                    logger.info("runtime: manual fan override cleared (back to auto)")
                self._manual_fan_speeds = None
            return None

        clamped = [max(0.0, min(1.0, float(s))) for s in speeds]
        with self._lock:
            self._manual_fan_speeds = clamped
            logger.info("runtime: manual fan override = %s", clamped)
        return list(clamped)

    # ------------------------------------------------------------------
    # Forced pattern (locks the choreography pattern regardless of mood)
    # ------------------------------------------------------------------
    def get_forced_pattern(self) -> Optional[str]:
        with self._lock:
            return self._forced_pattern

    def set_forced_pattern(self, pattern: Optional[str]) -> Optional[str]:
        """Pin the pattern to a specific name, or pass ``None`` for auto.

        Raises :class:`ValueError` if ``pattern`` isn't one of
        :data:`config.PATTERNS`.
        """
        if pattern is None:
            with self._lock:
                if self._forced_pattern is not None:
                    logger.info("runtime: forced_pattern cleared (auto)")
                self._forced_pattern = None
            return None
        if pattern not in config.PATTERNS:
            raise ValueError(
                f"unknown pattern {pattern!r}; expected one of {list(config.PATTERNS)}"
            )
        with self._lock:
            if self._forced_pattern != pattern:
                logger.info("runtime: forced_pattern → %s", pattern)
            self._forced_pattern = pattern
        return pattern
