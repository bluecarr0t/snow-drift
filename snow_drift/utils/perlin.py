"""Tiny self-contained 1D Perlin noise.

This is the classic Ken Perlin gradient-noise construction restricted
to one dimension:

  - hash each integer lattice point to a pseudo-random gradient (-1 or 1)
  - interpolate between the two surrounding lattice gradients with the
    quintic fade curve 6t^5 - 15t^4 + 10t^3
  - the result is a smooth, deterministic, repeatable signal in [-1, 1]

Same input always returns the same output (no internal RNG state), and
the seed parameter lets callers run independent noise streams - we use
this so each fan has its own subtly different breeze pattern.
"""

from __future__ import annotations

import math


def _hash(i: int, seed: int) -> int:
    """Deterministic 32-bit integer hash of ``(i, seed)``."""
    h = (i * 374761393 + seed * 668265263) & 0xFFFFFFFF
    h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
    return h ^ (h >> 16)


def _gradient(i: int, seed: int) -> float:
    """Pick a gradient of -1 or +1 for lattice point ``i``."""
    return 1.0 if (_hash(i, seed) & 1) else -1.0


def _fade(t: float) -> float:
    """Perlin's quintic fade curve - C2-continuous at lattice points."""
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def perlin_1d(x: float, seed: int = 0) -> float:
    """Compute 1D Perlin noise at coordinate ``x``.

    Args:
        x: Input coordinate. Lattice spacing is 1.0.
        seed: Independent noise stream identifier.

    Returns:
        Smooth pseudo-random value in approximately ``[-1.0, 1.0]``.
        Calling with the same ``(x, seed)`` always returns the same value.
    """
    if not math.isfinite(x):
        return 0.0

    x0 = math.floor(x)
    x1 = x0 + 1
    t = x - x0

    g0 = _gradient(x0, seed)
    g1 = _gradient(x1, seed)

    # Distances from each lattice point to x, dotted with the lattice
    # gradient. In 1D this collapses to a simple multiplication.
    n0 = g0 * t
    n1 = g1 * (t - 1.0)

    # Single-octave 1D Perlin with unit gradients peaks at ±0.5; scale
    # by 2 to give the documented [-1, 1] range.
    return 2.0 * ((1.0 - _fade(t)) * n0 + _fade(t) * n1)
