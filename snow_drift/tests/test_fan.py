"""Bring-up a single fan with optional pin selection.

Use this after you wire **one** MOSFET + fan to the Pi (default: Fan 1 /
GPIO 18 per :data:`config.FAN_PINS`). Ramp up, hold, ramp down — same
shape as ``test_single_fan`` but with a small CLI so you can point at
any BCM pin without editing ``config.py``.

Run::

    python -m snow_drift.tests.test_fan
    python -m snow_drift.tests.test_fan --fan 1
    python -m snow_drift.tests.test_fan --gpio 18

From the repo root, ``PYTHONPATH`` is the project directory so the
``snow_drift`` package resolves (same as other ``-m snow_drift.tests.*``
scripts).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from snow_drift import config
from snow_drift.fan_controller import FanController

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ramp one fan PWM up / hold / down for breadboard bring-up."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--fan",
        type=int,
        choices=range(1, len(config.FAN_PINS) + 1),
        metavar="N",
        help=f"which logical fan slot (1–{len(config.FAN_PINS)}); "
        f"uses config FAN_PINS index N-1 (default: 1)",
    )
    group.add_argument(
        "--gpio",
        type=int,
        metavar="BCM",
        help="BCM GPIO number directly (overrides --fan); for a one-off test pin",
    )
    parser.add_argument(
        "--ramp",
        type=float,
        default=5.0,
        metavar="SEC",
        help="seconds for each ramp leg (default: 5)",
    )
    parser.add_argument(
        "--hold",
        type=float,
        default=2.0,
        metavar="SEC",
        help="seconds at 100%% duty between ramps (default: 2)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=50,
        metavar="N",
        help="linear steps per ramp (default: 50)",
    )
    args = parser.parse_args(argv)
    if args.gpio is None and args.fan is None:
        args.fan = 1
    return args


def _resolve_pin(args: argparse.Namespace) -> tuple[int, str]:
    if args.gpio is not None:
        return args.gpio, f"BCM {args.gpio} (explicit)"
    assert args.fan is not None
    pin = config.FAN_PINS[args.fan - 1]
    return pin, f"Fan {args.fan} → BCM {pin}"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    pin, label = _resolve_pin(args)

    config.configure_logging()
    logger.info("test_fan: %s", label)

    fans = FanController(pins=[pin])

    if not fans.available:
        logger.error(
            "Fan PWM hardware not available — install gpiozero + lgpio on the Pi "
            "and run this on the board (not a dev laptop)."
        )
        fans.cleanup()
        return 1

    ramp_sec = args.ramp
    hold_sec = args.hold
    steps = max(1, args.steps)

    try:
        logger.info("Ramping 0 → 100%% over %.1fs (%d steps)", ramp_sec, steps)
        for i in range(steps + 1):
            fans.set_speed(0, i / steps)
            time.sleep(ramp_sec / steps)

        logger.info("Holding at 100%% for %.1fs", hold_sec)
        fans.set_speed(0, 1.0)
        time.sleep(hold_sec)

        logger.info("Ramping 100 → 0%% over %.1fs", ramp_sec)
        for i in range(steps + 1):
            fans.set_speed(0, 1.0 - i / steps)
            time.sleep(ramp_sec / steps)

        logger.info("Done — fan should have spun up, held, then stopped.")
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted — zeroing output")
        return 130
    finally:
        fans.cleanup()


if __name__ == "__main__":
    sys.exit(main())
