"""Fan GPIO / PWM debug run with **file + console logs** for support.

Run from the **repository root** (so ``snow_drift`` imports work)::

    python3 -m snow_drift.tests.test_fan_debug_log
    python3 -m snow_drift.tests.test_fan_debug_log --log ./my_fan_debug.log

Default log path: ``./snow_drift_fan_debug_<timestamp>.log`` in the current
working directory. Override with ``--log PATH`` or ``SNOW_DRIFT_FAN_DEBUG_LOG``.

The log includes: platform / Python / gpiozero version, pin factory,
:mod:`snow_drift.config` fan settings, three drive phases (``FanController``,
raw ``PWMOutputDevice``, ``DigitalOutputDevice``), and ``pinctrl get`` output
when available.

``SNOW_DRIFT_FAN_DEBUG_SKIP_SLEEP=1`` shortens hold times (for CI / dry-run).
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from snow_drift import config
from snow_drift.fan_controller import FanController

logger = logging.getLogger(__name__)

_SKIP_LONG_SLEEP = os.environ.get("SNOW_DRIFT_FAN_DEBUG_SKIP_SLEEP", "").strip() in (
    "1",
    "true",
    "yes",
)


def _default_log_path() -> Path:
    env = os.environ.get("SNOW_DRIFT_FAN_DEBUG_LOG", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path.cwd() / f"snow_drift_fan_debug_{ts}.log"


def _attach_file_handler(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(logging.Formatter(config.LOG_FORMAT))
    root = logging.getLogger()
    root.addHandler(fh)


def _log_environment() -> None:
    logger.info("=== Environment ===")
    logger.info("platform: %s", platform.platform())
    logger.info("machine: %s", platform.machine())
    logger.info("python_executable: %s", sys.executable)
    logger.info("python_version: %s", sys.version.replace("\n", " "))
    try:
        import gpiozero

        ver = getattr(gpiozero, "__version__", "unknown")
        logger.info("gpiozero_version: %s", ver)
        from gpiozero import Device

        fac = Device.pin_factory
        logger.info(
            "gpiozero_pin_factory: %s",
            type(fac).__name__ if fac is not None else None,
        )
    except Exception as exc:
        logger.warning("gpiozero_probe_failed: %s", exc)


def _log_config_summary() -> None:
    logger.info("=== snow_drift.config (fan-related) ===")
    logger.info("FAN_PINS (BCM): %s", list(config.FAN_PINS))
    logger.info("PWM_FREQUENCY_Hz: %s", config.PWM_FREQUENCY)
    logger.info(
        "physical mapping (docs): Fan1 header pin 12 = BCM %s",
        config.FAN_PINS[0],
    )


def _pinctrl_get(pin: int) -> None:
    exe = shutil.which("pinctrl")
    if not exe:
        logger.info("pinctrl: not in PATH (skipped)")
        return
    try:
        r = subprocess.run(
            [exe, "get", str(pin)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if out:
            for line in out.splitlines():
                logger.info("pinctrl get %s stdout: %s", pin, line)
        if err:
            for line in err.splitlines():
                logger.warning("pinctrl get %s stderr: %s", pin, line)
        logger.info("pinctrl get %s returncode: %s", pin, r.returncode)
    except Exception as exc:
        logger.warning("pinctrl failed: %s", exc)


def _sleep(name: str, seconds: float) -> None:
    if _SKIP_LONG_SLEEP:
        logger.info("sleep %s: skipped (SNOW_DRIFT_FAN_DEBUG_SKIP_SLEEP)", name)
        return
    logger.info("sleep %s: %.1fs", name, seconds)
    time.sleep(seconds)


def _run_phases(pin: int, hz: int) -> int:
    logger.info("=== Phase 1: FanController @ 100 percent duty ===")
    fans = FanController(pins=[pin])
    if not fans.available:
        logger.error("FanController.available is False — PWM not usable.")
        fans.cleanup()
        return 1

    fans.set_speed(0, 1.0)
    rb = fans.pwm_readback(0)
    logger.info("get_speeds: %s", fans.get_speeds())
    logger.info("pwm_readback(0): %s (expect ~1.0)", rb)
    _pinctrl_get(pin)

    if rb is not None and rb < 0.99:
        logger.warning(
            "pwm_readback below 0.99 — software/command path may be wrong."
        )

    _sleep("phase1_hold", 5.0)
    fans.cleanup()
    time.sleep(0.3)

    logger.info("=== Phase 2: PWMOutputDevice only @ 100 percent ===")
    try:
        from gpiozero import PWMOutputDevice

        pwm = PWMOutputDevice(pin, frequency=hz, initial_value=0.0)
        pwm.value = 1.0
        logger.info("PWMOutputDevice.value readback: %s", pwm.value)
        _pinctrl_get(pin)
        _sleep("phase2_hold", 3.0)
        pwm.off()
        pwm.close()
    except Exception:
        logger.exception("Phase 2 failed")
        return 1

    time.sleep(0.3)

    logger.info("=== Phase 3: DigitalOutputDevice HIGH ===")
    try:
        from gpiozero import DigitalOutputDevice

        dig = DigitalOutputDevice(pin)
        dig.on()
        logger.info(
            "DigitalOutputDevice: value=%s is_active=%s",
            dig.value,
            dig.is_active,
        )
        _pinctrl_get(pin)
        _sleep("phase3_hold", 3.0)
        dig.off()
        dig.close()
    except Exception:
        logger.exception("Phase 3 failed")
        return 1

    logger.info("=== Phases complete: pin released ===")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Snow Drift fan GPIO debug — writes a detailed log file.",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Log file path (default: ./snow_drift_fan_debug_<timestamp>.log)",
    )
    parser.add_argument(
        "--console-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Console stderr log level (file always INFO from root).",
    )
    args = parser.parse_args(argv)

    log_path = (args.log or _default_log_path()).expanduser().resolve()

    # Root: stderr via project helper, then add file (avoid double stderr).
    logging.getLogger().handlers.clear()
    config.configure_logging(level=logging.DEBUG)
    console_level = getattr(logging, args.console_level)
    for h in logging.getLogger().handlers:
        h.setLevel(console_level)

    _attach_file_handler(log_path)
    logging.getLogger().setLevel(logging.DEBUG)

    pin = int(config.FAN_PINS[0])
    hz = int(config.PWM_FREQUENCY)

    logger.info("=== Snow Drift fan debug log ===")
    logger.info("log_file: %s", log_path)
    _log_environment()
    _log_config_summary()
    logger.info(
        "BCM pin under test: %s (header physical pin 12 for Fan 1)", pin
    )

    print(f"Logging to: {log_path}", file=sys.stderr)
    try:
        rc = _run_phases(pin, hz)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user (KeyboardInterrupt)")
        rc = 130

    logger.info("=== End (exit_code=%s) ===", rc)
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.FileHandler):
            h.flush()
            break

    print(f"Log file: {log_path}", file=sys.stderr)
    return rc if rc != 130 else 130


if __name__ == "__main__":
    sys.exit(main())
