"""Python interface for the Auto Shutter Arduino controller."""

from __future__ import annotations

import argparse
import os
import time
from collections.abc import Iterable

import serial
from serial.tools import list_ports


BAUD_RATE = 115200
DEVICE_ID = "AUTO_SHUTTER_V1"
PORT_ENV_VAR = "AUTO_SHUTTER_PORT"


class ShutterNotFoundError(ConnectionError):
    """Raised when no connected Auto Shutter controller can be identified."""


def _candidate_ports(port: str | None = None) -> Iterable[str]:
    """Yield an override, or every serial port reported by the host OS."""
    selected_port = port or os.environ.get(PORT_ENV_VAR)
    if selected_port:
        yield selected_port
        return

    # USB serial devices are likely candidates. Try them before built-in or
    # virtual ports, but keep every port as a fallback for unusual boards.
    ports = list(list_ports.comports())
    ports.sort(key=lambda item: (item.vid is None, item.device))
    for item in ports:
        yield item.device


def open_shutter(
    port: str | None = None,
    *,
    startup_delay: float = 2.0,
    probe_timeout: float = 1.0,
) -> serial.Serial:
    """Find the controller by firmware ID and return its open serial port.

    ``pyserial`` supplies platform-specific port enumeration for Linux,
    macOS, and Windows. Opening an Uno resets it, so probing waits for its
    bootloader before sending the ``ID`` command.

    Pass ``port`` or set ``AUTO_SHUTTER_PORT`` to bypass enumeration while
    retaining the identity check.
    """
    attempted: list[str] = []
    errors: list[str] = []

    for candidate in _candidate_ports(port):
        attempted.append(candidate)
        connection: serial.Serial | None = None
        try:
            connection = serial.Serial(
                candidate,
                BAUD_RATE,
                timeout=0.1,
                write_timeout=1,
            )
            time.sleep(startup_delay)
            connection.reset_input_buffer()
            connection.write(b"ID\n")
            connection.flush()

            deadline = time.monotonic() + probe_timeout
            while time.monotonic() < deadline:
                response = connection.readline().decode("ascii", errors="replace").strip()
                if response == DEVICE_ID:
                    connection.timeout = 1
                    identified = connection
                    connection = None
                    return identified
        except (OSError, serial.SerialException) as exc:
            errors.append(f"{candidate}: {exc}")
        finally:
            if connection is not None:
                connection.close()

    if not attempted:
        detail = "No serial ports were found."
    else:
        detail = "Checked: " + ", ".join(attempted) + "."
    if errors:
        detail += " Port errors: " + "; ".join(errors)
    raise ShutterNotFoundError(
        f"No {DEVICE_ID} controller found. {detail} "
        f"Use --port or {PORT_ENV_VAR} to select a port explicitly."
    )


class AutoShutter:
    """Small API for sending commands to an identified shutter controller."""

    def __init__(self, connection: serial.Serial):
        self.serial = connection

    @classmethod
    def connect(cls, port: str | None = None) -> AutoShutter:
        return cls(open_shutter(port))

    @property
    def port(self) -> str:
        return self.serial.port

    def command(self, text: str) -> str:
        self.serial.write((text + "\n").encode("ascii"))
        self.serial.flush()
        return self.serial.readline().decode("ascii", errors="replace").strip()

    def move(self, angle: float) -> str:
        return self.command(f"MOVE {angle}")

    def stop(self) -> str:
        return self.command("STOP")

    def set_speed(self, microsteps_per_second: int) -> str:
        return self.command(f"SPEED {microsteps_per_second}")

    def close(self) -> None:
        self.serial.close()

    def __enter__(self) -> AutoShutter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Control the Auto Shutter")
    parser.add_argument("--port", help="serial port override (normally auto-detected)")
    parser.add_argument("--speed", type=int, default=500, help="microsteps per second")
    parser.add_argument("angle", type=float, nargs="?", help="angle to move in degrees")
    args = parser.parse_args()

    with AutoShutter.connect(args.port) as shutter:
        print(f"Connected to {shutter.port}")
        print(shutter.set_speed(args.speed))
        if args.angle is not None:
            print(shutter.move(args.angle))


if __name__ == "__main__":
    main()
