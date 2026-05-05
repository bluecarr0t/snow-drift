#!/usr/bin/env python3
"""Repo-root launcher for the minimal single-fan test.

    python3 test_single_fan_simple.py

Same as: python3 -m snow_drift.tests.test_single_fan_simple
"""

from __future__ import annotations

import sys

from snow_drift.tests.test_single_fan_simple import main

if __name__ == "__main__":
    sys.exit(main())
