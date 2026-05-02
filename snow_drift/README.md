# Snow Drift

A kinetic wall sculpture that pushes lightweight plastic snow particles
across a chamber with four small 5V fans, creating a visual effect like
wind blowing snow across a road. The piece responds to its environment
through a PIR motion sensor, a BME688 (temperature / humidity / pressure /
gas), and a BH1750 ambient light sensor. A small OLED reports live
status. All control is procedural, layered Perlin noise plus occasional
gust and stillness events, modulated by a sensor-driven mood engine.

## Hardware

- Raspberry Pi 5 (Raspberry Pi OS 64-bit, Bookworm, Python 3.11+)
- 4× GeeekPi 5V 4010 fans
- 4× IRLZ44N N-channel MOSFETs (low-side switching) with 10 kΩ pull-down
  resistors on the gates
- 1× SSD1306 0.96" OLED (128×64, I²C)
- 1× BME688 environmental sensor (I²C)
- 1× BH1750 ambient light sensor (I²C)
- 1× HC-SR501 PIR motion sensor
- 5V power for the fan rail via USB pigtail to a breadboard rail
- Common ground tying Pi GND to the fan supply GND

### Pin map

| Function   | BCM GPIO | Physical pin |
|------------|----------|--------------|
| Fan 1 PWM  | 18       | 12           |
| Fan 2 PWM  | 13       | 33           |
| Fan 3 PWM  | 12       | 32           |
| Fan 4 PWM  | 19       | 35           |
| PIR signal | 4        | 7            |
| PIR 5V     | —        | 2            |
| I²C SDA    | 2        | 3            |
| I²C SCL    | 3        | 5            |

I²C addresses: `0x23` BH1750, `0x3C` SSD1306, `0x76` BME688.

All four fan GPIOs are hardware-PWM capable on the Pi 5, so each fan
gets a clean, jitter-free duty cycle.

### Wiring (per fan)

```
                       +5V rail
                          │
                          ├──── Fan + (red)
                          │
                          │      Fan − (black) ──┐
                          │                       │
                          │                       │
                          │                  IRLZ44N
                          │                  ┌─D─┐
                          │                  │   │
                          │                  │   │  ← Drain
                       Pi GPIO ── 220 Ω ─── G│   │
                                              │   │  ← Source
                                              └─S─┘
                                                │
                                              GND
                          ┌── 10 kΩ ──┐
                          │            │
                       Pi GPIO        GND   ← gate pull-down
```

## Software setup

1. Enable I²C:

   ```bash
   sudo raspi-config
   # → Interface Options → I2C → Enable
   ```

2. Install dependencies (Bookworm requires `--break-system-packages`
   when not using a venv):

   ```bash
   pip install -r requirements.txt --break-system-packages
   ```

3. Verify the I²C bus sees every device, you should see `23`, `3c`,
   and `76` in the grid:

   ```bash
   i2cdetect -y 1
   ```

## Running

The whole project is a Python package under `snow_drift/`. Each test is
runnable as a module so imports always resolve correctly. From the
parent directory of this folder:

```bash
# Bring-up tests, in order
python -m snow_drift.tests.test_single_fan      # Fan 1 only
python -m snow_drift.tests.test_all_fans        # All four fans in turn
python -m snow_drift.tests.test_oled            # Animate the OLED
python -m snow_drift.tests.test_sensors         # 30s sensor readout
python -m snow_drift.tests.test_full_system     # Dry-run pipeline (no fans)

# Once everything passes:
python -m snow_drift                            # Real run
# or:
python snow_drift/main.py
```

`Ctrl+C` shuts everything down cleanly: fans go to 0%, OLED clears,
GPIO is released.

## Auto-start as a systemd service

For permanent installations, run Snow Drift under systemd so it
starts on boot, restarts on crash, and writes structured logs to the
journal. From the repo root on the Pi:

```bash
sudo ./deploy/install.sh
sudo systemctl start snow-drift
```

The installer auto-detects the invoking user, the repo path, and the
system Python interpreter. Override any of them with flags:

```bash
sudo ./deploy/install.sh --user nick --workdir /home/nick/snow-drift
```

Re-run `sudo ./deploy/install.sh --restart` after any `git pull` to
update the unit and bounce the service in one shot. Uninstall with
`sudo ./deploy/uninstall.sh`.

### Useful service commands

```bash
sudo systemctl start snow-drift          # start now
sudo systemctl stop snow-drift           # stop
sudo systemctl restart snow-drift        # bounce
sudo systemctl status snow-drift         # one-shot health check
journalctl -u snow-drift -f              # live tail
journalctl -u snow-drift -p warning      # warnings + errors only
journalctl -u snow-drift --since "1h ago"
journalctl -u snow-drift -o cat          # raw lines, no metadata
```

When running under systemd the application detects this and emits log
lines with syslog priorities (e.g. `<6>` for INFO, `<4>` for WARNING),
which is what makes `journalctl -p warning` filter correctly.

### Service policy

The unit file (`deploy/snow-drift.service.template`) configures:

- **Restart**: `on-failure` with a 5s cooldown and a 10-restarts-per-5min
  rate limit, so a transient sensor blip recovers automatically but a
  hard crash loop is contained.
- **Memory**: 128 MB soft, 256 MB hard ceiling. The loop normally sits
  well under 64 MB; the limit catches pathological leaks early.
- **Shutdown**: 15 s `TimeoutStopSec` with `SIGTERM` so the Python
  signal handler can stop the fans cleanly before systemd escalates.
- **Hardening**: `NoNewPrivileges`, `ProtectKernelTunables`,
  `ProtectKernelModules`, `ProtectControlGroups`, `ProtectHome=read-only`,
  `PrivateTmp` — none of which interfere with `/dev/gpiochip*` or
  `/dev/i2c-1`.
- **Time / network**: waits for `time-sync.target` and
  `network-online.target` so future weather-API features see correct
  local time and a usable network from the very first tick.

Adjust the template before running the installer to tweak any of the
above.

## Tuning

Every constant lives in [`config.py`](./config.py): GPIO pins, sleep /
wake timings, mood-mapping thresholds, wind algorithm parameters,
sensor read intervals, OLED rate, and logging. Adjust there, no need
to edit any other file.

## Architecture

```
sensors → mood_engine → wind_algorithm → fan_controller
                                       → oled_display
```

- **`sensors/`** wraps each device. Init failures fall back to cached
  defaults so a missing sensor never crashes the loop.
- **`mood_engine.py`** runs the AWAKE → SLEEPING → ASLEEP → WAKING
  state machine on the PIR, and exponentially smooths the BME688 +
  BH1750 readings into wind parameters.
- **`wind_algorithm.py`** layers Perlin baselines (one stream per fan),
  half-sine-shaped gust events, and stillness pauses, then applies
  visibility scaling driven by ambient light.
- **`fan_controller.py`** owns four `gpiozero.PWMOutputDevice`
  instances and stages startup to avoid a current spike.
- **`oled_display.py`** renders the live status frame, scoping all
  hardware imports so it can be imported on a non-Pi dev box.
- **`main.py`** is the orchestrator and signal-handler home.

## Troubleshooting

| Symptom                                  | Likely cause                                                                                          |
|------------------------------------------|-------------------------------------------------------------------------------------------------------|
| Fan doesn't spin at any duty cycle       | MOSFET source/drain swapped, missing common ground, or 5V rail not powered                            |
| Fan won't stop fully                     | Missing 10 kΩ gate pull-down resistor                                                                 |
| Fan runs full speed only                 | PWM frequency too high for the FET / gate driver, drop `PWM_FREQUENCY` in `config.py`                 |
| OLED dark                                | I²C not enabled, wrong address (run `i2cdetect -y 1`), or SDA/SCL swapped                             |
| BME688 / BH1750 missing in `i2cdetect`   | Pull-up resistors missing on SDA/SCL, or 3V3 not connected                                            |
| `gpiozero` "No module named 'lgpio'"     | Install the `lgpio` backend listed in `requirements.txt`                                              |
| `KeyboardInterrupt` traceback on exit    | Harmless: the signal handler still runs and triggers the `finally` cleanup                            |
| PIR fires constantly                     | The HC-SR501's two trim pots set sensitivity & retrigger time — start fully CCW and tune outward      |

## Layout

```
snow-drift/                          # repo root
├── deploy/
│   ├── snow-drift.service.template  # systemd unit (placeholders)
│   ├── install.sh                   # render + install + enable
│   └── uninstall.sh                 # symmetric removal
└── snow_drift/                      # Python package
    ├── README.md
    ├── requirements.txt
    ├── __init__.py
    ├── __main__.py
    ├── config.py
    ├── main.py
    ├── fan_controller.py
    ├── oled_display.py
    ├── wind_algorithm.py
    ├── mood_engine.py
    ├── sensors/
    │   ├── __init__.py
    │   ├── pir.py
    │   ├── environment.py
    │   ├── light.py
    │   └── poller.py
    ├── tools/
    │   ├── __init__.py
    │   └── fan_console.py
    ├── utils/
    │   ├── __init__.py
    │   └── perlin.py
    └── tests/
        ├── __init__.py
        ├── test_single_fan.py
        ├── test_all_fans.py
        ├── test_oled.py
        ├── test_sensors.py
        └── test_full_system.py
```
