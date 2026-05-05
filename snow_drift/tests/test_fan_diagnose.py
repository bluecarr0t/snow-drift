"""Fan bring-up **diagnostic** — prove software ↔ GPIO, separate from wiring.

Run from repo root::

    python3 -m snow_drift.tests.test_fan_diagnose

This script **does not fix** a dead fan. It answers: “Did the Pi and Python
actually command the pin, and does solid DC behave differently from PWM?”

Phases (same BCM pin as Fan 1 / ``config.FAN_PINS[0]``):

1. **FanController** @ 100% PWM (:data:`config.PWM_FREQUENCY` Hz): logs
   factory, ``get_speeds()``, ``pwm_readback()``, optional ``pinctrl get``.
2. **Pause** — hold 100% a few seconds so you can meter pin 12 vs GND or
   watch the fan.
3. **PWMOutputDevice** only (same frequency) — same readback.
4. **DigitalOutputDevice** HIGH for 3 s — same as ``pinctrl op dh`` / your
   earlier sanity test; then LOW and close.

Between phases the previous device is **closed** so the pin is not double-owned.

If phases 1–3 show readback **1.0** but the fan never moves, the scripts
are **not** the problem — it's **5 V / MOSFET / gate row / fan** (see
``HARDWARE_SETUP.md``). If phase 4 spins the fan but 1–3 do not, say so
(that would be unusual; report Pi OS + gpiozero versions).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time

from snow_drift import config
from snow_drift.fan_controller import FanController

logger = logging.getLogger(__name__)


def _pinctrl_get(pin: int) -> None:
    exe = shutil.which("pinctrl")
    if not exe:
        logger.info("(no pinctrl in PATH — skip; install raspi-utils on Pi OS)")
        return
    try:
        r = subprocess.run(
            [exe, "get", str(pin)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        line = (r.stdout or r.stderr or "").strip()
        if line:
            logger.info("pinctrl get %s → %s", pin, line.splitlines()[0])
        if r.returncode != 0:
            logger.warning("pinctrl exited %s", r.returncode)
    except Exception as exc:
        logger.warning("pinctrl failed: %s", exc)


def main() -> int:
    config.configure_logging()
    pin = int(config.FAN_PINS[0])
    hz = int(config.PWM_FREQUENCY)

    print()
    print("========== Snow Drift fan DIAGNOSE ==========")
    print(f"  FAN_PINS (all slots) = {list(config.FAN_PINS)}")
    print(f"  This test uses Fan 1 → BCM GPIO {pin}, PWM {hz} Hz")
    print("============================================")
    print()

    # --- Phase 1: FanController ---
    print("[1/4] FanController: construct + 100% duty")
    fans = FanController(pins=[pin])
    if not fans.available:
        logger.error("FanController.available is False — PWM stack not working.")
        fans.cleanup()
        return 1

    fans.set_speed(0, 1.0)
    print(f"      get_speeds()        = {fans.get_speeds()}")
    rb = fans.pwm_readback(0)
    print(f"      pwm_readback(0)    = {rb}   (expect ~1.0)")
    _pinctrl_get(pin)

    if rb is not None and rb < 0.99:
        print()
        print("  WARNING: gpiozero readback is not ~1.0 — software path may be wrong.")
    print("      (holding 5s — watch fan / meter pin 12 vs GND)")
    time.sleep(5.0)
    fans.cleanup()
    time.sleep(0.3)

    # --- Phase 2: raw PWMOutputDevice ---
    print()
    print("[2/4] gpiozero.PWMOutputDevice only @ 100%")
    try:
        from gpiozero import PWMOutputDevice

        pwm = PWMOutputDevice(pin, frequency=hz, initial_value=0.0)
        pwm.value = 1.0
        print(f"      .value readback    = {pwm.value}")
        _pinctrl_get(pin)
        print("      (holding 3s)")
        time.sleep(3.0)
        pwm.off()
        pwm.close()
    except Exception as exc:
        logger.exception("Phase 2 failed: %s", exc)
        return 1
    time.sleep(0.3)

    # --- Phase 3: DigitalOutputDevice (solid high) ---
    print()
    print("[3/4] gpiozero.DigitalOutputDevice HIGH (like pinctrl op dh)")
    try:
        from gpiozero import DigitalOutputDevice

        dig = DigitalOutputDevice(pin)
        dig.on()
        print(f"      .value = {dig.value}  is_active = {dig.is_active}")
        _pinctrl_get(pin)
        print("      (holding 3s)")
        time.sleep(3.0)
        dig.off()
        dig.close()
    except Exception as exc:
        logger.exception("Phase 3 failed: %s", exc)
        return 1

    print()
    print("[4/4] Done — all phases released the pin.")
    print()
    print("Interpretation:")
    print("  • pwm_readback ~1.0 + LGPIOFactory → Python commanded full duty.")
    print("  • Fan still dead → breadboard + MOSFET + 5 V + gate row (not this repo).")
    print("  • Pin 12 unplug test: if pinctrl | hi only when unplugged, gate net shorts.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
