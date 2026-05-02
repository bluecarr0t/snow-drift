"""Snow Drift - kinetic wall sculpture controller for Raspberry Pi 5.

A modular controller that drives 4× 5V fans (via MOSFETs on hardware-PWM
GPIOs) to push lightweight plastic snow particles across a chamber.
Sensors (PIR, BME688, BH1750) shape the wind in response to the
surrounding environment.
"""

__version__ = "0.1.0"
