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

## Persistent terminal

Start without an angle to keep one serial connection open:

```bash
uv run main.py
```

Then enter commands:

```text
shutter> SPEED 100
SPEED SET
shutter> MOVE 90
MOVING
DONE
shutter> STOP
STOPPED
shutter> SCRIPT example_sequence.txt
shutter> EXIT
```

This avoids reopening and resetting the Arduino between commands. `EXIT`,
`QUIT`, Ctrl+C, or end-of-input closes the connection. `SCRIPT <path>` runs a
command file through the same open connection, then returns to the prompt.

## Command scripts

Store one command per line. `WAIT` is a host-side delay in seconds; comments
start with `#`. `LOOP N` repeats its indented block `N` times. Tabs and spaces
are accepted for indentation, and loops can be nested.

```text
SPEED 250
LOOP 5
    MOVE 90
    WAIT 5
MOVE -90
```

Run the file through one persistent connection:

```bash
uv run main.py --script example_sequence.txt
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

Valid speed values are 50 through 2000 microsteps per second. The interface
retries a dropped speed command, which can occur while some Windows USB serial
drivers settle after opening an Arduino Uno. It will not send the move command
unless the speed command receives a response.
