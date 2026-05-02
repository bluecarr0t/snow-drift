"""Sensor wrappers for the Snow Drift piece.

All sensors are designed to fail soft: if hardware is missing or returns
an error, the wrapper logs a warning and returns cached/default values
so the main loop continues running.
"""

from snow_drift.sensors.environment import EnvironmentSensor
from snow_drift.sensors.light import LightSensor
from snow_drift.sensors.pir import PIRSensor

__all__ = ["EnvironmentSensor", "LightSensor", "PIRSensor"]
