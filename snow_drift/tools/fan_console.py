"""Interactive single-fan console.

A live curses TUI for hardware bring-up. Lets you drive one fan with
arrow keys, watch the commanded duty cycle on a big bar, and (if your
fan has a tachometer wire) read live RPM and total revolutions.

Usage::

    # Speed control only (works for 2-wire fans)
    python -m snow_drift.tools.fan_console --pin 18

    # With RPM, requires a 3- or 4-wire fan whose yellow tach wire is
    # connected to the given BCM GPIO pin (with the gpiozero internal
    # pull-up enabled - tach lines are open-collector).
    python -m snow_drift.tools.fan_console --pin 18 --tach-pin 17

Keys:

    ↑ / + / =       +5% duty
    ↓ / -           -5% duty
    →               +1% (fine)
    ←               -1% (fine)
    0..9            jump to 0%, 10%, ..., 90%
    f               100%
    space           toggle off / last non-zero value
    r               reset total revolution counter
    q / Esc         quit
"""

from __future__ import annotations

import argparse
import curses
import logging
import time
from collections import deque
from threading import Lock
from typing import Optional, Sequence

from snow_drift import config
from snow_drift.fan_controller import FanController

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tach reader
# ---------------------------------------------------------------------------
class TachCounter:
    """Edge-counting tachometer reader for a 3- or 4-wire PC-style fan.

    Standard PC fans output two pulses per revolution on an open-collector
    tach line, so we enable gpiozero's internal pull-up. RPM is averaged
    over a sliding ``window_seconds`` window to keep the display stable.
    """

    def __init__(
        self,
        pin: int,
        pulses_per_rev: int = 2,
        window_seconds: float = 1.0,
    ) -> None:
        from gpiozero import DigitalInputDevice

        self.pin = pin
        self.pulses_per_rev = max(1, pulses_per_rev)
        self.window_seconds = max(0.1, window_seconds)

        self._recent: deque[float] = deque()
        self._total_pulses = 0
        self._lock = Lock()

        self._device = DigitalInputDevice(pin, pull_up=True, bounce_time=None)
        self._device.when_activated = self._on_pulse
        logger.info("Tach reader on GPIO %d (%d pulses/rev)", pin, pulses_per_rev)

    def _on_pulse(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._recent.append(now)
            self._total_pulses += 1

    def rpm(self) -> float:
        """Return the average RPM over the last ``window_seconds``."""
        cutoff = time.monotonic() - self.window_seconds
        with self._lock:
            while self._recent and self._recent[0] < cutoff:
                self._recent.popleft()
            count = len(self._recent)
        return (count / self.pulses_per_rev) / self.window_seconds * 60.0

    def total_revolutions(self) -> float:
        """Return total revolutions counted since startup (or last reset)."""
        with self._lock:
            return self._total_pulses / self.pulses_per_rev

    def reset_total(self) -> None:
        with self._lock:
            self._total_pulses = 0
            self._recent.clear()

    def cleanup(self) -> None:
        try:
            self._device.close()
        except Exception as exc:  # pragma: no cover
            logger.debug("Tach close raised: %s", exc)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Live single-fan console with arrow-key control + optional RPM."
    )
    p.add_argument(
        "--pin",
        type=int,
        default=config.FAN_PINS[0],
        help="BCM GPIO pin driving the fan (default: %(default)s)",
    )
    p.add_argument(
        "--tach-pin",
        type=int,
        default=None,
        help=(
            "BCM GPIO pin reading the fan's tach signal (yellow wire on "
            "3/4-wire fans). Omit for 2-wire fans."
        ),
    )
    p.add_argument(
        "--frequency",
        type=int,
        default=config.PWM_FREQUENCY,
        help="PWM frequency in Hz (default: %(default)s)",
    )
    p.add_argument(
        "--pulses-per-rev",
        type=int,
        default=2,
        help="Tach pulses per revolution (default: %(default)s; PC-fan standard)",
    )
    p.add_argument(
        "--rpm-window",
        type=float,
        default=1.0,
        help="Sliding window in seconds for RPM averaging (default: %(default)s)",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
_HELP_LINE = (
    "↑/↓:±5%  ←/→:±1%  0-9:0-90%  f:100%  space:toggle  r:reset rev  q:quit"
)


def _clamp(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _draw(
    stdscr: "curses._CursesWindow",
    *,
    duty: float,
    pin: int,
    frequency: int,
    tach: Optional[TachCounter],
    uptime: float,
) -> None:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    if h < 12 or w < 50:
        stdscr.addstr(0, 0, "Terminal too small (need >=50x12)")
        stdscr.refresh()
        return

    title = f" Snow Drift  fan console  GPIO {pin} @ {frequency} Hz "
    stdscr.addstr(0, 0, title.ljust(w - 1)[: w - 1], curses.A_REVERSE)

    stdscr.addstr(2, 2, "Duty cycle:")
    stdscr.addstr(2, 16, f"{duty * 100:6.1f}%", curses.A_BOLD)

    bar_width = max(10, w - 8)
    filled = int(round(duty * bar_width))
    stdscr.addstr(4, 2, "[")
    stdscr.addstr(4, 3, "#" * filled, curses.A_BOLD)
    stdscr.addstr(4, 3 + filled, "." * (bar_width - filled))
    stdscr.addstr(4, 3 + bar_width, "]")

    if tach is not None:
        rpm = tach.rpm()
        revs = tach.total_revolutions()
        stdscr.addstr(6, 2, f"RPM:               {rpm:7.0f}")
        stdscr.addstr(7, 2, f"Total revolutions: {revs:7.1f}")
    else:
        stdscr.addstr(
            6, 2, "RPM: (no tach pin; pass --tach-pin <gpio> for 3-wire fans)"
        )

    stdscr.addstr(9, 2, f"Uptime: {uptime:6.1f}s")

    stdscr.addstr(h - 1, 0, _HELP_LINE.ljust(w - 1)[: w - 1], curses.A_REVERSE)
    stdscr.refresh()


def _run_curses(
    stdscr: "curses._CursesWindow",
    fan: FanController,
    tach: Optional[TachCounter],
    args: argparse.Namespace,
) -> None:
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.keypad(True)

    duty = 0.0
    last_nonzero = 0.5
    start = time.monotonic()
    last_render = 0.0

    while True:
        ch = stdscr.getch()

        if ch != -1:
            if ch in (ord("q"), ord("Q"), 27):  # q or Esc
                return
            elif ch in (curses.KEY_UP, ord("+"), ord("=")):
                duty = _clamp(duty + 0.05)
            elif ch in (curses.KEY_DOWN, ord("-"), ord("_")):
                duty = _clamp(duty - 0.05)
            elif ch == curses.KEY_RIGHT:
                duty = _clamp(duty + 0.01)
            elif ch == curses.KEY_LEFT:
                duty = _clamp(duty - 0.01)
            elif ch == ord(" "):
                if duty > 0.0:
                    last_nonzero = duty
                    duty = 0.0
                else:
                    duty = last_nonzero
            elif ch in (ord("f"), ord("F")):
                duty = 1.0
            elif ord("0") <= ch <= ord("9"):
                duty = (ch - ord("0")) / 10.0
            elif ch in (ord("r"), ord("R")) and tach is not None:
                tach.reset_total()

            fan.set_speed(0, duty)
            if duty > 0:
                last_nonzero = duty

        now = time.monotonic()
        if now - last_render >= 0.05:
            _draw(
                stdscr,
                duty=duty,
                pin=args.pin,
                frequency=args.frequency,
                tach=tach,
                uptime=now - start,
            )
            last_render = now

        time.sleep(0.01)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    config.configure_logging(level=logging.WARNING)  # quiet in TUI mode

    fan = FanController(pins=[args.pin], pwm_frequency=args.frequency,
                        startup_stagger=0.0)
    if not fan.available:
        print(
            "Fan PWM hardware not available - is gpiozero installed and "
            "are you on the Pi?"
        )
        fan.cleanup()
        return 1

    tach: Optional[TachCounter] = None
    if args.tach_pin is not None:
        try:
            tach = TachCounter(
                pin=args.tach_pin,
                pulses_per_rev=args.pulses_per_rev,
                window_seconds=args.rpm_window,
            )
        except Exception as exc:
            print(f"Could not open tach on GPIO {args.tach_pin}: {exc}")
            fan.cleanup()
            return 1

    try:
        curses.wrapper(_run_curses, fan, tach, args)
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        fan.cleanup()
        if tach is not None:
            tach.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
