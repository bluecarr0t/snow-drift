# Snow Drift — Single-fan breadboard setup (v0)

Field reference for **nimbus** (Raspberry Pi 5) and the first GeeekPi 4010
fan on a BB830 breadboard. Pin numbers below use **physical** (board) pins
unless the column says **BCM**.

Software mapping for all four fans lives in `snow_drift/config.py` as
`FAN_PINS` = **[18, 13, 12, 19]** (BCM), i.e. Fan 1…Fan 4 slots.

---

## Bill of materials (this build)

| Qty | Part |
|-----|------|
| 1 | Raspberry Pi 5 |
| 1 | BB830 breadboard |
| 1 | IRLZ44N N-channel MOSFET (TO-220) |
| 1 | 10 kΩ resistor (gate → GND pull-down) |
| 1 | 5 V GeeekPi 4010 fan |
| 1 | USB pigtail (5 V + GND for fan rail) |
| — | F–M jumper wires |

**Optional:** 220 Ω in series from Pi GPIO → gate (see main README wiring
diagram; some builds jumper gate directly on a breadboard for bring-up).

---

## Power rails

| Connection | From | To |
|------------|------|-----|
| 5 V power | USB pigtail **red** | Top **(+)** rail |
| Ground | USB pigtail **black** | Top **(−)** rail |
| Power bridge | Top **(+)** rail | Bottom **(+)** rail |
| Ground bridge | Top **(−)** rail | Bottom **(−)** rail |

The Pi 5 itself is powered separately (e.g. official 27 W USB-C supply).
The **fan +5 V rail** comes from the pigtail. **Pi GND** and **pigtail GND**
must meet on the breadboard **(−)** rail so PWM and return current share a
reference.

---

## MOSFET placement (IRLZ44N)

- **Position:** Rows **5, 6, 7**, column **B**
- **Orientation:** Silkscreen “IRLZ44N” readable from the front; metal tab
  faces **away** from you

**Pin mapping (left → right when reading the part label):**

| Leg | Row | MOSFET terminal |
|-----|-----|-----------------|
| Left | 5 | **Gate** |
| Middle | 6 | **Drain** |
| Right | 7 | **Source** |

---

## Component connections

| Connection | Location |
|------------|----------|
| 10 kΩ leg 1 | Row **5**, column **D** (same row as Gate) |
| 10 kΩ leg 2 | Bottom **(−)** rail |
| Pi **GPIO 18** (physical **pin 12**) | Row **5**, column **C** (Gate) |
| Fan **black** (negative) | Row **6**, column **E** (Drain) |
| Fan **red** (positive) | Top **(+)** rail |
| Source → GND | Row **7**, column **C** → bottom **(−)** rail |
| Pi **GND** (physical **pin 6**) | Bottom **(−)** rail |

---

## Pi GPIO (Fan 1 only)

| Physical pin | BCM GPIO | Function | Goes to |
|--------------|----------|----------|---------|
| **12** | **18** | PWM (Fan 1 in software) | MOSFET **Gate** (row 5) |
| **6** | — | Ground | Breadboard **(−)** rail |

---

## How it works

1. Pi drives **BCM 18** with PWM (Snow Drift uses **1000 Hz** in code).
2. Gate voltage turns the MOSFET on/off; duty cycle sets average current
   through the fan.
3. Current path: **+5 V rail** → fan red → motor → fan black → **Drain** →
   **Source** → **GND rail**.
4. The **10 kΩ** resistor holds the gate near 0 V when the GPIO is not
   driving, avoiding a floating gate.

---

## Tests (this repository)

After `git clone` / `git pull`, from the repo root on **nimbus**:

```bash
cd ~/snow-drift   # or your clone path
python3 test_fan.py
# same thing:
python3 -m snow_drift.tests.test_fan
```

Default uses **Fan 1** → **BCM 18** (your wiring). Options:

```bash
python3 test_fan.py --fan 1
python3 test_fan.py --gpio 18 --ramp 3 --hold 2
```

`snow_drift.tests.test_single_fan` is the same ramp curve without CLI flags.

### Minimal scratch script (not required)

If you want a tiny `gpiozero` one-off in `~/test_fan.py`, this matches the
idea of the bring-up you described (no project package):

```python
from gpiozero import PWMOutputDevice
from time import sleep

fan1 = PWMOutputDevice(18, frequency=1000)

print("Testing Fan 1 (BCM 18)...")
for duty, label in [(0.3, "30%"), (0.6, "60%"), (1.0, "100%")]:
    print(label)
    fan1.value = duty
    sleep(3)

print("Stopping...")
fan1.value = 0
sleep(1)
fan1.close()
print("Done.")
```

Prefer the repo’s `test_fan.py` so behavior stays aligned with
`FanController` (frequency, cleanup, future multi-fan work).

---

## Future expansion (Fans 2–4)

Repeat the same MOSFET + 10 kΩ + source-to-GND pattern in free breadboard
real estate. Software slots (`config.FAN_PINS`):

| Fan | BCM GPIO | Physical pin (typ.) |
|-----|----------|---------------------|
| 1 | 18 | 12 |
| 2 | 13 | 33 |
| 3 | 12 | 32 |
| 4 | 19 | 35 |

Each channel needs: MOSFET; 10 kΩ gate–GND; source→GND jumper; GPIO→gate
jumper; fan + to **+ rail**, fan − to **drain** row.

---

## Host

- **Hostname:** `nimbus`
- Use this doc as hardware context when editing `snow_drift` on that Pi.
