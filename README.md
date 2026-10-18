# Auto Shutter

Controls a shutter built from an Arduino Uno, EasyDriver V4.4, and stepper
motor. Host software supports Linux, macOS, and Windows.

## Device discovery

Flash `auto_shutter_v1.ino` onto the Arduino. The Python interface enumerates
serial ports using pySerial, sends `ID`, and selects only the device that
answers `AUTO_SHUTTER_V1`. This is more reliable than matching a port name,
USB VID/PID, or description, which can differ between operating systems and
Uno-compatible boards.

Automatic detection:

```bash
uv run python main.py 90
```

Optional explicit port override:

```bash
uv run python main.py --port COM3 90
# or
AUTO_SHUTTER_PORT=/dev/ttyACM0 uv run python main.py 90
```

## Python API

```python
from interface import AutoShutter

with AutoShutter.connect() as shutter:
    shutter.set_speed(500)
    shutter.move(90)
```

`AutoShutter.connect("COM3")` can select a known port explicitly. Explicit
ports are still checked with the firmware ID handshake to prevent sending
motor commands to the wrong serial device.
