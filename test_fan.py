#!/usr/bin/env python3
"""Run single-fan PWM bring-up from the repo root.

    python3 test_fan.py
    python3 test_fan.py --fan 1
    python3 test_fan.py --gpio 18 --ramp 3

Equivalent to: python3 -m snow_drift.tests.test_fan ...
"""

from __future__ import annotations

import sys

from snow_drift.tests.test_fan import main

if __name__ == "__main__":
    sys.exit(main())
