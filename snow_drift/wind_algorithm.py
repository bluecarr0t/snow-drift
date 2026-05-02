"""Layered procedural wind for the four fans.

Three independent layers are blended every step:

1. **Perlin baseline** - each fan has its own slow noise stream so they
   wander independently, giving the chamber an organic restless feel.
2. **Gust events** - occasionally all fans pulse together for a short
   interval, simulating a wind blast across the road.
3. **Stillness events** - occasionally the whole field drops near zero
   for a few seconds, like a held breath before the next gust.

The output is finally scaled by ``visibility_factor`` (driven by ambient
light) to make the piece subtler in bright rooms and dramatic in dim
ones. ``base_intensity`` is the master gain (driven by mood + sleep).
"""

from __future__ import annotations

import logging
import math
import random
from typing import Mapping

from snow_drift import config
from snow_drift.utils.perlin import perlin_1d

logger = logging.getLogger(__name__)


class WindAlgorithm:
    """Stateful procedural wind generator.

    Attributes:
        time: Accumulated seconds of simulated wind time.
        gust_active_until: Simulated time at which the current gust ends.
        stillness_until: Simulated time at which the current stillness ends.
        perlin_offsets: Per-fan offsets into the noise field so each fan
            has a distinct wandering pattern.
    """

    def __init__(self, num_fans: int = 4) -> None:
        self.num_fans = num_fans
        self.time: float = 0.0
        self.gust_active_until: float = 0.0
        self.stillness_until: float = 0.0
        # Spaced offsets so the four fans never read the same lattice
        # cell at the same moment.
        self.perlin_offsets: list[float] = [i * 1.5 for i in range(num_fans)]
        self._rng = random.Random()

    def _maybe_trigger_event(self, dt: float, mood_params: Mapping[str, float]) -> None:
        """Roll for new gust / stillness events based on per-second probabilities.

        ``GUST_PROBABILITY`` and ``STILLNESS_PROBABILITY`` are expressed
        per second; we scale by ``dt`` to get a per-step probability.
        ``mood_params['gust_rate']`` boosts gust likelihood when humidity
        (or other chaos drivers) is high.
        """
        if self.time >= self.gust_active_until and self.time >= self.stillness_until:
            gust_rate = float(mood_params.get("gust_rate", 0.5))
            # Symmetric scaling: humid/chaotic moods bias toward gusts in
            # the same proportion that calm/dry moods bias toward
            # stillness. Both factors land in [0.5, 1.5] so the total
            # rate of "something is happening" stays roughly constant.
            gust_p = config.GUST_PROBABILITY * dt * (0.5 + gust_rate)
            still_p = config.STILLNESS_PROBABILITY * dt * (1.5 - gust_rate)

            if self._rng.random() < gust_p:
                self.gust_active_until = self.time + config.GUST_DURATION_SECONDS
                logger.debug("Gust triggered until t=%.2f", self.gust_active_until)
            elif self._rng.random() < still_p:
                self.stillness_until = self.time + config.STILLNESS_DURATION_SECONDS
                logger.debug("Stillness triggered until t=%.2f", self.stillness_until)

    def _gust_envelope(self) -> float:
        """Return the current gust amplitude in ``[0.0, 1.0]``.

        Shaped as a smooth half-sine over the gust duration so the gust
        ramps up and down rather than snapping on/off.
        """
        if self.time >= self.gust_active_until:
            return 0.0
        remaining = self.gust_active_until - self.time
        progress = 1.0 - remaining / config.GUST_DURATION_SECONDS
        return math.sin(math.pi * progress)

    def _stillness_envelope(self) -> float:
        """Return the current stillness amount in ``[0.0, 1.0]``.

        ``1.0`` means "fully still right now"; the envelope is a smooth
        half-sine over the stillness duration.
        """
        if self.time >= self.stillness_until:
            return 0.0
        remaining = self.stillness_until - self.time
        progress = 1.0 - remaining / config.STILLNESS_DURATION_SECONDS
        return math.sin(math.pi * progress)

    def _perlin_value(self, fan_index: int) -> float:
        """Return a Perlin sample in ``[0.0, 1.0]`` for the given fan."""
        x = self.time * config.PERLIN_SCALE + self.perlin_offsets[fan_index]
        # perlin_1d returns roughly [-1, 1]; remap to [0, 1].
        raw = perlin_1d(x, seed=fan_index)
        return max(0.0, min(1.0, 0.5 + 0.5 * raw))

    def step(self, dt: float, mood_params: Mapping[str, float]) -> list[float]:
        """Advance one timestep and return the fan-speed vector.

        Args:
            dt: Real time elapsed since the previous call (seconds).
            mood_params: Mapping containing at least:
                - ``base_intensity`` (0.0-1.0): master gain on wind
                - ``gust_rate`` (0.0-1.0): how often gusts occur
                - ``visibility_factor`` (0.5-1.5): final overall multiplier

        Returns:
            List of ``num_fans`` floats in ``[0.0, 1.0]`` representing
            the commanded duty cycle for each fan.
        """
        if dt < 0:
            dt = 0.0
        self.time += dt

        # Re-base internal time to keep the float magnitude bounded so
        # Perlin lattice resolution stays clean over very long runs.
        # Subtracting the same amount from every event deadline keeps
        # the algorithm's behaviour completely unchanged.
        if self.time > config.WIND_TIME_WRAP_SECONDS:
            self.time -= config.WIND_TIME_WRAP_SECONDS
            self.gust_active_until -= config.WIND_TIME_WRAP_SECONDS
            self.stillness_until -= config.WIND_TIME_WRAP_SECONDS
            logger.debug("Wind time wrapped (t=%.2f)", self.time)

        self._maybe_trigger_event(dt, mood_params)

        base_intensity = float(mood_params.get("base_intensity", 0.5))
        visibility_factor = float(mood_params.get("visibility_factor", 1.0))

        gust = self._gust_envelope()
        stillness = self._stillness_envelope()

        speeds: list[float] = []
        for i in range(self.num_fans):
            perlin = self._perlin_value(i)

            # Layer 1: baseline scaled by mood intensity.
            value = perlin * base_intensity

            # Layer 2: gust boosts everyone toward GUST_INTENSITY.
            value = value * (1.0 - gust) + config.GUST_INTENSITY * gust

            # Layer 3: stillness pulls everyone toward zero.
            value = value * (1.0 - stillness)

            # Final layer: light-driven visibility scaling.
            value *= visibility_factor

            # Apply a stiction floor only if there's any signal to speak
            # of - we don't want to spin fans that should be fully still.
            if 0.0 < value < config.MIN_RUNNING_DUTY:
                value = config.MIN_RUNNING_DUTY

            speeds.append(max(0.0, min(1.0, value)))

        return speeds
