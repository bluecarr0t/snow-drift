#!/usr/bin/env python3
"""Repo-root launcher for fan debug logging.

    python3 test_fan_debug_log.py
    python3 test_fan_debug_log.py --log ~/fan_debug.log

Same as: python3 -m snow_drift.tests.test_fan_debug_log
"""

from __future__ import annotations

import sys

from snow_drift.tests.test_fan_debug_log import main

if __name__ == "__main__":
    sys.exit(main())
