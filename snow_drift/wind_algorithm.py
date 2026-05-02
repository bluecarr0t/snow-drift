"""Layered procedural wind with selectable choreography patterns.

The output of every step is built up in three layers:

1. **Pattern**  — a per-fan baseline shape, one of:
     - ``wander`` — independent Perlin noise per fan (the original look)
     - ``sweep``  — single noise stream sampled with per-fan time delay,
                   so it reads as a wave moving fan 0 → fan N
     - ``vortex`` — narrow cosine peak that rotates around the array,
                   one fan dominant at a time with a low rest baseline
     - ``breath`` — every fan in sync, sinusoidal swell with a power
                   curve so the peak lingers
2. **Gust events**  — occasional pulses where all fans surge together
   toward :data:`config.GUST_INTENSITY`. Probability biased by mood.
3. **Stillness events** — occasional pauses where the whole field is
   pulled toward zero. Probability biased the opposite way.

The result is then scaled by ``visibility_factor`` (light-driven) and
floor-clamped at :data:`config.MIN_RUNNING_DUTY` so any signal that's
non-zero actually has enough duty cycle to overcome fan stiction.

When the requested pattern changes, the algorithm cross-fades from the
old pattern's baseline to the new one over
:data:`config.PATTERN_FADE_SECONDS` using a smoothstep curve. The
gust/stillness/visibility/stiction layers continue running across the
transition so a gust that started under ``wander`` finishes naturally
under ``sweep``.
"""

from __future__ import annotations

import logging
import math
import random
from typing import Callable, Mapping

from snow_drift import config
from snow_drift.utils.perlin import perlin_1d

logger = logging.getLogger(__name__)


def _smoothstep(t: float) -> float:
    """Hermite smoothstep from 0 to 1, with C1 continuity at endpoints."""
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * (3.0 - 2.0 * t)


class WindAlgorithm:
    """Stateful procedural wind generator with named patterns.

    Attributes:
        time: Accumulated seconds of simulated wind time.
        gust_active_until: Simulated time at which the current gust ends.
        stillness_until: Simulated time at which the current stillness ends.
        perlin_offsets: Per-fan offsets used by the ``wander`` pattern.
        current_pattern: Pattern actively driving the per-fan baseline.
            Set by :meth:`step` from each call's ``mood_params['pattern']``;
            transitions cross-fade from the previous pattern.
    """

    def __init__(self, num_fans: int = 4) -> None:
        self.num_fans = num_fans
        self.time: float = 0.0
        self.gust_active_until: float = 0.0
        self.stillness_until: float = 0.0
        # Spaced offsets so wander's four fans never read the same
        # lattice cell at the same moment.
        self.perlin_offsets: list[float] = [i * 1.5 for i in range(num_fans)]
        self._rng = random.Random()

        # Pattern transition state. Initialise the "changed at" time well
        # in the past so the first step doesn't try to cross-fade.
        self._current_pattern: str = "wander"
        self._previous_pattern: str = "wander"
        self._pattern_changed_at: float = -config.PATTERN_FADE_SECONDS - 1.0

        self._patterns: dict[str, Callable[[float], list[float]]] = {
            "wander": self._pattern_wander,
            "sweep": self._pattern_sweep,
            "vortex": self._pattern_vortex,
            "breath": self._pattern_breath,
        }

    # ------------------------------------------------------------------
    # Read-only state for the web UI.
    # ------------------------------------------------------------------
    @property
    def current_pattern(self) -> str:
        return self._current_pattern

    @property
    def transitioning(self) -> bool:
        """Whether a cross-fade is currently in flight."""
        return (
            self._previous_pattern != self._current_pattern
            and self.time - self._pattern_changed_at < config.PATTERN_FADE_SECONDS
        )

    # ------------------------------------------------------------------
    # Pattern math. Each takes the master ``intensity`` (already
    # multiplied by mood + presence) and returns a clamped per-fan
    # baseline vector. They never mutate state.
    # ------------------------------------------------------------------
    def _pattern_wander(self, intensity: float) -> list[float]:
        """Independent Perlin noise per fan — restless, organic."""
        speeds: list[float] = []
        for i in range(self.num_fans):
            x = self.time * config.PERLIN_SCALE + self.perlin_offsets[i]
            raw = perlin_1d(x, seed=i)  # [-1, 1]
            speeds.append(max(0.0, min(1.0, 0.5 + 0.5 * raw)) * intensity)
        return speeds

    def _pattern_sweep(self, intensity: float) -> list[float]:
        """Single noise stream sampled with per-fan delay → traveling wave."""
        speeds: list[float] = []
        for i in range(self.num_fans):
            # Each fan reads the same noise stream but ``i * lag`` seconds
            # behind fan 0, so the whole pattern translates across the
            # array left → right at 1 / lag fans per second.
            x = (self.time - i * config.SWEEP_LAG_SECONDS) * config.SWEEP_NOISE_SCALE
            raw = perlin_1d(x, seed=99)
            speeds.append(max(0.0, min(1.0, 0.5 + 0.5 * raw)) * intensity)
        return speeds

    def _pattern_vortex(self, intensity: float) -> list[float]:
        """Narrow cosine peak rotating around the fan array."""
        phase = self.time * 2.0 * math.pi / config.VORTEX_PERIOD_SECONDS
        speeds: list[float] = []
        for i in range(self.num_fans):
            fan_phase = i * 2.0 * math.pi / self.num_fans
            # ((cos+1)/2)^3 is a narrow bell — at any moment, one fan is
            # near 1 and the others are near 0.
            raw = (math.cos(phase - fan_phase) + 1.0) / 2.0
            peak = raw ** 3
            base = config.VORTEX_PEAK_BASELINE
            speeds.append((base + (1.0 - base) * peak) * intensity)
        return speeds

    def _pattern_breath(self, intensity: float) -> list[float]:
        """All fans in sync, slow swell. Calmest of the four patterns."""
        raw = (math.sin(self.time * 2.0 * math.pi / config.BREATH_PERIOD_SECONDS) + 1.0) / 2.0
        swell = raw ** config.BREATH_SHAPE
        return [swell * intensity for _ in range(self.num_fans)]

    # ------------------------------------------------------------------
    # Event envelopes (gust / stillness)
    # ------------------------------------------------------------------
    def _maybe_trigger_event(
        self, dt: float, mood_params: Mapping[str, float]
    ) -> None:
        if self.time >= self.gust_active_until and self.time >= self.stillness_until:
            gust_rate = float(mood_params.get("gust_rate", 0.5))
            gust_p = config.GUST_PROBABILITY * dt * (0.5 + gust_rate)
            still_p = config.STILLNESS_PROBABILITY * dt * (1.5 - gust_rate)

            if self._rng.random() < gust_p:
                self.gust_active_until = self.time + config.GUST_DURATION_SECONDS
                logger.debug("Gust triggered until t=%.2f", self.gust_active_until)
            elif self._rng.random() < still_p:
                self.stillness_until = self.time + config.STILLNESS_DURATION_SECONDS
                logger.debug("Stillness triggered until t=%.2f", self.stillness_until)

    def _gust_envelope(self) -> float:
        if self.time >= self.gust_active_until:
            return 0.0
        remaining = self.gust_active_until - self.time
        progress = 1.0 - remaining / config.GUST_DURATION_SECONDS
        return math.sin(math.pi * progress)

    def _stillness_envelope(self) -> float:
        if self.time >= self.stillness_until:
            return 0.0
        remaining = self.stillness_until - self.time
        progress = 1.0 - remaining / config.STILLNESS_DURATION_SECONDS
        return math.sin(math.pi * progress)

    # ------------------------------------------------------------------
    # Pattern transition
    # ------------------------------------------------------------------
    def _maybe_change_pattern(self, requested: str) -> None:
        """Begin a cross-fade if the requested pattern differs."""
        if requested not in self._patterns:
            logger.debug("ignoring unknown pattern %r", requested)
            return
        if requested == self._current_pattern:
            return
        self._previous_pattern = self._current_pattern
        self._current_pattern = requested
        self._pattern_changed_at = self.time
        logger.info(
            "Pattern: %s → %s", self._previous_pattern, self._current_pattern
        )

    def _pattern_baselines(self, intensity: float) -> list[float]:
        """Compute the per-fan baseline, blending two patterns mid-fade."""
        current = self._patterns[self._current_pattern](intensity)
        if self._previous_pattern == self._current_pattern:
            return current

        elapsed = self.time - self._pattern_changed_at
        if elapsed >= config.PATTERN_FADE_SECONDS:
            # Fade complete: collapse history so we don't keep computing
            # the previous pattern's math forever.
            self._previous_pattern = self._current_pattern
            return current

        previous = self._patterns[self._previous_pattern](intensity)
        t = _smoothstep(elapsed / config.PATTERN_FADE_SECONDS)
        return [prev + (curr - prev) * t for prev, curr in zip(previous, current)]

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def step(self, dt: float, mood_params: Mapping[str, object]) -> list[float]:
        """Advance one timestep and return the fan-speed vector.

        Args:
            dt: Real time elapsed since the previous call (seconds).
            mood_params: Mapping containing at least:

                - ``base_intensity`` (0.0–1.0): master gain on wind
                - ``gust_rate``     (0.0–1.0): how often gusts occur
                - ``visibility_factor`` (0.5–1.5): final overall multiplier
                - ``pattern`` (str, optional): one of :data:`config.PATTERNS`.
                  Falls back to the algorithm's current pattern if omitted
                  or unknown.

        Returns:
            List of ``num_fans`` floats in ``[0.0, 1.0]``.
        """
        if dt < 0:
            dt = 0.0
        self.time += dt

        # Re-base internal time periodically to keep float magnitude small.
        if self.time > config.WIND_TIME_WRAP_SECONDS:
            self.time -= config.WIND_TIME_WRAP_SECONDS
            self.gust_active_until -= config.WIND_TIME_WRAP_SECONDS
            self.stillness_until -= config.WIND_TIME_WRAP_SECONDS
            self._pattern_changed_at -= config.WIND_TIME_WRAP_SECONDS
            logger.debug("Wind time wrapped (t=%.2f)", self.time)

        self._maybe_trigger_event(dt, mood_params)

        requested = str(mood_params.get("pattern", self._current_pattern))
        self._maybe_change_pattern(requested)

        base_intensity = float(mood_params.get("base_intensity", 0.5))
        visibility_factor = float(mood_params.get("visibility_factor", 1.0))
        gust = self._gust_envelope()
        stillness = self._stillness_envelope()

        baselines = self._pattern_baselines(base_intensity)

        speeds: list[float] = []
        for value in baselines:
            # Layer 2: gust mixes everyone toward GUST_INTENSITY.
            value = value * (1.0 - gust) + config.GUST_INTENSITY * gust
            # Layer 3: stillness pulls everyone toward zero.
            value = value * (1.0 - stillness)
            # Final scaling and floor.
            value *= visibility_factor
            if 0.0 < value < config.MIN_RUNNING_DUTY:
                value = config.MIN_RUNNING_DUTY
            speeds.append(max(0.0, min(1.0, value)))

        return speeds
