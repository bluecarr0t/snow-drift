# Snow Drift

> A kinetic wall sculpture that turns the weather in your room into wind
> across a chamber of plastic snow.

Four small 5V fans, four GPIO PWM channels, and a few cheap I²C sensors
turn a Raspberry Pi 5 into a slow, ambient piece that reacts to who's
in the room and what the air feels like. A **PIR motion sensor** wakes
it up; a **BME688** (temperature / humidity / pressure / gas) and a
**BH1750** ambient light sensor shape its mood; a small **SSD1306 OLED**
reports live status. All control is procedural — layered Perlin noise
plus occasional gust and stillness events, modulated by a sensor-driven
**mood engine** that picks one of four named choreography patterns.

```
              warm + dry                       warm + humid
            ┌──────────────────────┐         ┌──────────────────────┐
            │  ░░░  ░░░  ░░░  ░░░  │         │  ░  ░░░░  ░  ░░░░░░  │
            │   sweep  →  →  →    │         │     vortex (rotates)  │
            └──────────────────────┘         └──────────────────────┘
              cool + dry                       cool + humid
            ┌──────────────────────┐         ┌──────────────────────┐
            │  ░░░░░░░░░░░░░░░░░░  │         │  ░░  ░  ░░░  ░  ░░░  │
            │     breath (sync)    │         │   wander (per-fan)   │
            └──────────────────────┘         └──────────────────────┘
```

## Highlights

- **Mood-driven choreography** — temperature × humidity selects from
  `wander` / `sweep` / `vortex` / `breath` patterns, with hysteresis to
  prevent flapping and a 1.5 s cross-fade between transitions.
- **Live web UI** on port 8080 — replica of the OLED, animated fan bars,
  Pi system stats, and tuning controls (master intensity, force-awake,
  pattern lock, manual fan override). Single self-contained HTML file,
  no CDN, polls `GET /api/state` 2× per second.
- **Graceful degradation** — every sensor and the OLED fail soft; a
  missing chip logs a warning and the loop continues with cached
  defaults. Develop locally on macOS without any hardware attached.
- **Ready for unattended install** — systemd unit with `Restart=on-failure`,
  rate-limiting, memory caps, hardening, and journald-aware structured
  logging (`<6>` priority prefixes for `journalctl -p` filtering).
- **Smart wind algorithm** — non-blocking sensor poller in a daemon
  thread, `dt`-aware exponential smoothing, monotonic time everywhere,
  internal time-wrap to keep float magnitudes bounded over month-long
  runs.

> 📷 *Photos / video to come once the chamber's permanent housing is
> mounted on the wall.*

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
   pip install -r snow_drift/requirements.txt --break-system-packages
   ```

3. Verify the I²C bus sees every device, you should see `23`, `3c`,
   and `76` in the grid:

   ```bash
   i2cdetect -y 1
   ```

## Running

The whole project is a Python package under `snow_drift/`. Each test is
runnable as a module so imports always resolve correctly. From the repo
root:

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

## Choreography patterns

`wind_algorithm.py` produces per-fan baselines via one of four named
patterns. The mood engine picks the pattern from the current
`(intensity × chaos)` plane, and the algorithm cross-fades between
patterns over `PATTERN_FADE_SECONDS` (1.5 s by default).

|                       | low chaos (smooth)         | high chaos (chaotic)         |
| --------------------- | -------------------------- | ---------------------------- |
| **high intensity**    | `sweep` — traveling wave   | `vortex` — rotating peak     |
| **low intensity**     | `breath` — synced swell    | `wander` — independent noise |

- **`wander`** — the original look. Independent Perlin noise per fan;
  feels organic and restless.
- **`sweep`** — a single noise stream sampled with per-fan time delay,
  producing a wave that travels fan 0 → fan N at `1 / SWEEP_LAG_SECONDS`
  fans per second.
- **`vortex`** — narrow cosine peak rotates around the array
  (`VORTEX_PERIOD_SECONDS` per full revolution); one fan dominant at a
  time, others held at `VORTEX_PEAK_BASELINE`.
- **`breath`** — every fan in sync, sinusoidal swell with a power curve
  so the peak lingers. Calmest of the four.

The pattern selector uses a 0.1-wide hysteresis deadband around 0.5 on
each axis, so baselines wobbling near the threshold don't cause
flapping. Override the auto-selection from the web UI's pattern button
group, or programmatically:

```python
settings.set_forced_pattern("vortex")  # lock
settings.set_forced_pattern(None)      # release
```

Gust and stillness events run *across* pattern transitions: a gust that
starts under `wander` finishes naturally under `sweep`.

## Web UI

`main.py` starts a small FastAPI server on **port 8080** in a daemon
thread. Open `http://<pi-host>:8080/` from any device on the local
network to see:

- A live replica of the OLED layout
- Per-fan duty cycles (animated bars)
- Live sensor readings (motion, temperature, humidity, lux)
- Pi system stats (CPU temp, load, memory, disk, throttle status)
- Loop "age" indicator that turns yellow / red if the main loop stalls

…and four controls:

- **Master intensity** (0×–2× slider) — boosts or trims overall energy
  without touching `config.py`.
- **Force awake** toggle — pins presence to AWAKE during a viewing so
  the piece doesn't go to sleep while people are watching it.
- **Choreography pattern** — auto, or lock to a specific named pattern
  (`wander`, `sweep`, `vortex`, `breath`). See
  [Choreography patterns](#choreography-patterns) below for what each
  one looks like. Pattern transitions cross-fade smoothly over ~1.5s.
- **Manual fan override** — per-fan sliders that take complete control
  of the fans. Useful for show-floor demos and acceptance testing.
  Click "Release to auto" to hand back to the algorithm.

The page polls `GET /api/state` every 500 ms (and pauses polling when
the tab is hidden, so leaving it open isn't a Pi tax). All controls
POST to small endpoints; FastAPI's auto-generated schema docs live at
`/api/docs`.

### REST endpoints

```
GET  /api/state            # everything (loop snapshot + system + settings)
GET  /api/health           # {ok: bool, loop_age_s: float}
GET  /api/config           # current runtime settings
POST /api/config           # bulk-update any subset of settings
POST /api/control/fans     # {"speeds":[...]} or {"speeds":null} to release
POST /api/control/intensity         # {"multiplier": 0.0..2.0}
POST /api/control/force-awake       # {"enabled": bool}
POST /api/control/pattern           # {"pattern": "wander"|"sweep"|"vortex"|"breath"|null}
```

The web UI is a single `index.html` (no CDN, no build step), so the
Pi has no internet dependency for its own admin surface.

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
- **`wind_algorithm.py`** dispatches to one of four named patterns
  (`wander`, `sweep`, `vortex`, `breath`) for the per-fan baseline,
  then layers half-sine-shaped gust events and stillness pauses on top
  and applies visibility scaling driven by ambient light. Pattern
  changes cross-fade over ~1.5 s. See
  [Choreography patterns](#choreography-patterns).
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
├── README.md
├── deploy/
│   ├── snow-drift.service.template  # systemd unit (placeholders)
│   ├── install.sh                   # render + install + enable
│   └── uninstall.sh                 # symmetric removal
└── snow_drift/                      # Python package
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
    ├── runtime_settings.py
    ├── web/
    │   ├── __init__.py
    │   ├── server.py
    │   ├── shared_state.py
    │   ├── system_stats.py
    │   └── static/
    │       └── index.html
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
