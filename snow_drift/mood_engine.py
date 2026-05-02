"""Mood engine - translates sensor readings into wind parameters.

This is the "brain" of the piece. It runs a small state machine for the
PIR-driven sleep / wake cycle and continuously eases environmental
readings (temperature, humidity, light) into the high-level wind
parameters that the wind algorithm consumes.

Design notes:

- Environmental updates use exponential smoothing with a time constant
  (:data:`config.ENV_SMOOTHING_TAU_SECONDS`) and are dt-aware, so the
  piece's mood drifts at the same real-world rate regardless of the
  loop's update rate.
- The presence state machine is the source of truth for the master
  intensity multiplier; the wind algorithm itself is unaware of sleep.
- ``get_wind_params`` is pure - it just reads current state - so it
  can be called many times per loop without side effects.
- All elapsed-time math uses :func:`time.monotonic` so an NTP step
  cannot cause spurious presence transitions.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Literal, Optional, TypedDict

from snow_drift import config

logger = logging.getLogger(__name__)


PresenceState = Literal["AWAKE", "SLEEPING", "ASLEEP", "WAKING"]


class WindParams(TypedDict):
    """Bundle of high-level inputs for the wind algorithm + display."""

    base_intensity: float
    gust_rate: float
    visibility_factor: float
    mood_label: str


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _inverse_lerp(a: float, b: float, value: float) -> float:
    """Map ``value`` from ``[a, b]`` into ``[0, 1]`` (clamped)."""
    if a == b:
        return 0.0
    t = (value - a) / (b - a)
    return max(0.0, min(1.0, t))


def _smoothing_alpha(dt: float, tau: float) -> float:
    """Per-step alpha for ``1 - exp(-dt / tau)`` exponential smoothing.

    Returns 0 when ``dt`` is non-positive, 1 when ``tau`` is non-positive.
    """
    if tau <= 0:
        return 1.0
    if dt <= 0:
        return 0.0
    return 1.0 - math.exp(-dt / tau)


class MoodEngine:
    """Sensor-driven mood + presence state machine."""

    def __init__(self) -> None:
        now = time.monotonic()
        self.last_motion_time: float = now
        self.wake_started_at: float | None = None
        self.sleep_started_at: float | None = None
        self.presence_state: PresenceState = "AWAKE"

        self.baseline_intensity: float = 0.5
        self.baseline_chaos: float = 0.3
        self.visibility_factor: float = 1.0

        self._mood_label: str = "Calm"

    # ------------------------------------------------------------------
    # Presence (PIR) state machine
    # ------------------------------------------------------------------
    def update_presence(
        self, motion_detected: bool, force_awake: bool = False
    ) -> None:
        """Advance the AWAKE / SLEEPING / ASLEEP / WAKING state machine.

        Transitions:

        - ``AWAKE``    →  ``SLEEPING`` after MOTION_TIMEOUT_SECONDS of no motion
        - ``SLEEPING`` →  ``ASLEEP``   after FULL_SLEEP_SECONDS total
        - ``ASLEEP``   →  ``WAKING``   on motion
        - ``SLEEPING`` →  ``WAKING``   on motion
        - ``WAKING``   →  ``AWAKE``    after WAKE_FADE_IN_SECONDS

        ``force_awake=True`` (driven by the web UI's "force awake"
        toggle) keeps the piece in AWAKE regardless of PIR activity.
        We refresh ``last_motion_time`` every tick while it's set so a
        return to normal mode doesn't immediately count the override
        period as idle time.
        """
        now = time.monotonic()
        if force_awake:
            self.last_motion_time = now
            if self.presence_state != "AWAKE":
                logger.info(
                    "Presence: %s → AWAKE (forced via runtime settings)",
                    self.presence_state,
                )
                self.presence_state = "AWAKE"
                self.wake_started_at = None
                self.sleep_started_at = None
            return
        if motion_detected:
            self.last_motion_time = now

        elapsed = now - self.last_motion_time

        if self.presence_state == "AWAKE":
            if not motion_detected and elapsed >= config.MOTION_TIMEOUT_SECONDS:
                self.presence_state = "SLEEPING"
                self.sleep_started_at = now
                logger.info("Presence: AWAKE → SLEEPING (idle %.0fs)", elapsed)

        elif self.presence_state == "SLEEPING":
            if motion_detected:
                self._begin_wake(now)
            elif elapsed >= config.FULL_SLEEP_SECONDS:
                self.presence_state = "ASLEEP"
                logger.info("Presence: SLEEPING → ASLEEP")

        elif self.presence_state == "ASLEEP":
            if motion_detected:
                self._begin_wake(now)

        elif self.presence_state == "WAKING":
            if (
                self.wake_started_at is not None
                and now - self.wake_started_at >= config.WAKE_FADE_IN_SECONDS
            ):
                self.presence_state = "AWAKE"
                self.wake_started_at = None
                logger.info("Presence: WAKING → AWAKE")

        else:  # pragma: no cover - exhaustive on Literal
            raise AssertionError(f"Unknown presence state {self.presence_state!r}")

    def _begin_wake(self, now: float) -> None:
        self.presence_state = "WAKING"
        self.wake_started_at = now
        self.sleep_started_at = None
        logger.info("Presence: → WAKING (motion detected)")

    # ------------------------------------------------------------------
    # Environmental update (BME688 + BH1750)
    # ------------------------------------------------------------------
    def update_environment(
        self,
        dt: float,
        temp_c: Optional[float] = None,
        humidity: Optional[float] = None,
        lux: Optional[float] = None,
    ) -> None:
        """Ease the mood baselines toward the values implied by the sensors.

        Each input is independent: pass ``None`` for any sensor that is
        unavailable so its corresponding baseline freezes rather than
        drifting toward a stale cached default. Smoothing is dt-aware
        with time constant :data:`config.ENV_SMOOTHING_TAU_SECONDS`.

        Args:
            dt: Real seconds elapsed since the last call.
            temp_c: Latest ambient temperature in Celsius, or ``None``.
            humidity: Latest relative humidity (%RH), or ``None``.
            lux: Latest ambient light reading, or ``None``.
        """
        alpha = _smoothing_alpha(dt, config.ENV_SMOOTHING_TAU_SECONDS)

        if temp_c is not None:
            target_intensity = _inverse_lerp(
                config.TEMP_CALM_C, config.TEMP_ACTIVE_C, temp_c
            )
            self.baseline_intensity = _lerp(
                self.baseline_intensity, target_intensity, alpha
            )

        if humidity is not None:
            target_chaos = _inverse_lerp(
                config.HUMIDITY_LOW, config.HUMIDITY_HIGH, humidity
            )
            self.baseline_chaos = _lerp(
                self.baseline_chaos, target_chaos, alpha
            )

        if lux is not None:
            # Bright rooms → 0.5x (subtle), dim rooms → 1.5x (dramatic).
            # Note LUX_DIM < LUX_BRIGHT so we invert the mapping here.
            bright_t = _inverse_lerp(config.LUX_DIM, config.LUX_BRIGHT, lux)
            target_visibility = _lerp(1.5, 0.5, bright_t)
            self.visibility_factor = _lerp(
                self.visibility_factor, target_visibility, alpha
            )

        self._mood_label = self._compute_mood_label()

    def _compute_mood_label(self) -> str:
        """Pick a short human-readable label describing the current mood."""
        if self.baseline_intensity < 0.25:
            base = "Calm"
        elif self.baseline_intensity < 0.6:
            base = "Drifting"
        else:
            base = "Active"

        if self.baseline_chaos > 0.7:
            base += " (Chaotic)"
        elif self.baseline_chaos < 0.2:
            base += " (Smooth)"
        return base

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def get_wind_params(self) -> WindParams:
        """Snapshot the current wind parameters for the wind algorithm.

        Applies the presence multiplier:

        - ``ASLEEP``:    intensity 0.0
        - ``SLEEPING``:  intensity ramping 1 → 0 over SLEEP_FADE_OUT_SECONDS
        - ``WAKING``:    intensity ramping 0 → 1 over WAKE_FADE_IN_SECONDS
        - ``AWAKE``:     full computed values
        """
        presence_multiplier = self._compute_presence_multiplier()

        base_intensity = self.baseline_intensity * presence_multiplier
        gust_rate = self.baseline_chaos * presence_multiplier
        mood_label = self._mood_label

        if self.presence_state == "ASLEEP":
            mood_label = "Asleep"
        elif self.presence_state == "SLEEPING":
            mood_label = "Drowsy"
        elif self.presence_state == "WAKING":
            mood_label = "Waking"

        return WindParams(
            base_intensity=base_intensity,
            gust_rate=gust_rate,
            visibility_factor=self.visibility_factor,
            mood_label=mood_label,
        )

    def _compute_presence_multiplier(self) -> float:
        """Return the master intensity gain implied by the presence state."""
        now = time.monotonic()
        state = self.presence_state

        if state == "AWAKE":
            return 1.0
        if state == "ASLEEP":
            return 0.0
        if state == "WAKING":
            if self.wake_started_at is None:
                return 1.0
            t = (now - self.wake_started_at) / max(
                config.WAKE_FADE_IN_SECONDS, 1e-6
            )
            return max(0.0, min(1.0, t))
        if state == "SLEEPING":
            if self.sleep_started_at is None:
                return 1.0
            t = (now - self.sleep_started_at) / max(
                config.SLEEP_FADE_OUT_SECONDS, 1e-6
            )
            return max(0.0, min(1.0, 1.0 - t))
        # pragma: no cover - exhaustive on Literal
        raise AssertionError(f"Unknown presence state {state!r}")
