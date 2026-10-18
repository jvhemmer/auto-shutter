"""Python interface for the Auto Shutter Arduino controller."""

from __future__ import annotations

import argparse
import os
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import serial
from serial.tools import list_ports


BAUD_RATE = 115200
DEVICE_ID = "AUTO_SHUTTER_V1"
PORT_ENV_VAR = "AUTO_SHUTTER_PORT"
SPEED_RETRIES = 3


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
        if not 50 <= microsteps_per_second <= 2000:
            raise ValueError("speed must be between 50 and 2000 microsteps per second")

        # Some Windows USB-serial drivers can lose the first command sent
        # immediately after identification. SPEED is safe to retry because
        # setting the same value more than once has no additional effect.
        last_response = ""
        for attempt in range(SPEED_RETRIES):
            response = self.command(f"SPEED {microsteps_per_second}")
            if response == "SPEED SET":
                return response
            if response == "INVALID SPEED":
                raise ValueError("controller rejected speed")
            last_response = response
            if attempt < SPEED_RETRIES - 1:
                time.sleep(0.1)

        detail = f"; last response was {last_response!r}" if last_response else ""
        raise TimeoutError(
            f"Controller did not acknowledge SPEED after {SPEED_RETRIES} attempts{detail}"
        )

    def close(self) -> None:
        self.serial.close()

    def __enter__(self) -> AutoShutter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass(frozen=True)
class _ScriptCommand:
    line_number: int
    text: str


@dataclass(frozen=True)
class _ScriptLoop:
    line_number: int
    count: int
    commands: list[_ScriptCommand | _ScriptLoop]


def _parse_script(lines: Iterable[str]) -> list[_ScriptCommand | _ScriptLoop]:
    source: list[tuple[int, int, str]] = []
    for line_number, source_line in enumerate(lines, start=1):
        expanded = source_line.expandtabs(4).rstrip()
        text = expanded.lstrip(" ")
        if not text or text.startswith("#"):
            continue
        source.append((line_number, len(expanded) - len(text), text))

    if source and source[0][1] != 0:
        raise ValueError(f"script line {source[0][0]}: unexpected indentation")

    def parse_block(
        index: int, indentation: int
    ) -> tuple[list[_ScriptCommand | _ScriptLoop], int]:
        commands: list[_ScriptCommand | _ScriptLoop] = []
        while index < len(source):
            line_number, current_indentation, text = source[index]
            if current_indentation < indentation:
                break
            if current_indentation > indentation:
                raise ValueError(f"script line {line_number}: unexpected indentation")

            command, *arguments = text.split(maxsplit=1)
            if command.upper() != "LOOP":
                commands.append(_ScriptCommand(line_number, text))
                index += 1
                continue

            if not arguments:
                raise ValueError(f"script line {line_number}: LOOP requires a count")
            try:
                count = int(arguments[0])
            except ValueError as exc:
                raise ValueError(
                    f"script line {line_number}: LOOP count must be an integer"
                ) from exc
            if count < 0:
                raise ValueError(
                    f"script line {line_number}: LOOP count cannot be negative"
                )
            if index + 1 >= len(source) or source[index + 1][1] <= indentation:
                raise ValueError(
                    f"script line {line_number}: LOOP requires an indented block"
                )

            child_indentation = source[index + 1][1]
            body, index = parse_block(index + 1, child_indentation)
            commands.append(_ScriptLoop(line_number, count, body))
        return commands, index

    commands, _ = parse_block(0, 0)
    return commands


def _run_script_command(shutter: AutoShutter, command: _ScriptCommand) -> None:
    line = command.text
    name, *arguments = line.split(maxsplit=1)
    name = name.upper()
    argument = arguments[0] if arguments else ""

    try:
        if name == "WAIT":
            seconds = float(argument)
            if seconds < 0:
                raise ValueError("WAIT duration cannot be negative")
            print(f"> WAIT {seconds:g}")
            time.sleep(seconds)
            # Movement completion is asynchronous. Drain messages such as
            # DONE now so they cannot be mistaken for the next command's
            # acknowledgement.
            while shutter.serial.in_waiting:
                response = shutter.serial.readline().decode(
                    "ascii", errors="replace"
                ).strip()
                if response:
                    print(response)
            return

        if name == "SPEED":
            speed = int(argument)
            print(f"> SPEED {speed}")
            print(shutter.set_speed(speed))
            return

        if name == "MOVE":
            angle = float(argument)
            text = f"MOVE {angle:g}"
        elif name in {"STOP", "ID"} and not argument:
            text = name
        else:
            raise ValueError(f"unsupported command: {line!r}")

        print(f"> {text}")
        response = shutter.command(text)
        if response:
            print(response)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"script line {command.line_number}: {exc}") from exc


def _run_script_block(
    shutter: AutoShutter, commands: Iterable[_ScriptCommand | _ScriptLoop]
) -> None:
    for command in commands:
        if isinstance(command, _ScriptLoop):
            for iteration in range(1, command.count + 1):
                print(f"> LOOP {iteration}/{command.count}")
                _run_script_block(shutter, command.commands)
        else:
            _run_script_command(shutter, command)


def run_script(shutter: AutoShutter, lines: Iterable[str]) -> None:
    """Run shutter commands from an iterable while keeping one connection open.

    Supported device commands are ``SPEED``, ``MOVE``, ``STOP``, and ``ID``.
    ``WAIT <seconds>`` pauses on the host. ``LOOP <count>`` repeats its
    indented block. Blank lines and lines starting with ``#`` are ignored.
    """
    _run_script_block(shutter, _parse_script(lines))


def interactive_terminal(shutter: AutoShutter) -> None:
    """Run an interactive terminal backed by one persistent serial connection."""
    prompt = "shutter> "

    def start_reader() -> tuple[threading.Event, threading.Thread]:
        stopped = threading.Event()

        def print_responses() -> None:
            while not stopped.is_set():
                try:
                    response = shutter.serial.readline().decode(
                        "ascii", errors="replace"
                    ).strip()
                except (OSError, serial.SerialException) as exc:
                    if not stopped.is_set():
                        print(f"Serial error: {exc}")
                    return
                if response:
                    # Responses such as DONE arrive while input() owns the
                    # line. Redraw the prompt so terminal does not look stuck.
                    print(f"\n{response}\n{prompt}", end="", flush=True)

        reader = threading.Thread(target=print_responses, daemon=True)
        reader.start()
        return stopped, reader

    def stop_reader(reader_state: tuple[threading.Event, threading.Thread]) -> None:
        stopped, reader = reader_state
        stopped.set()
        reader.join(timeout=1.1)

    reader_state = start_reader()
    help_text = (
        "Commands: SPEED <50-2000>, MOVE <angle>, STOP, ID, "
        "SCRIPT <path>, HELP, EXIT"
    )
    print(help_text)

    try:
        while True:
            try:
                line = input(prompt).strip()
            except EOFError:
                break
            if not line:
                continue
            if line.upper() in {"EXIT", "QUIT"}:
                break
            if line.upper() == "HELP":
                print(help_text)
                continue

            command, *arguments = line.split(maxsplit=1)
            command = command.upper()
            if command == "SCRIPT":
                if not arguments:
                    print("SCRIPT requires a file path.")
                    continue
                script_path = Path(arguments[0]).expanduser()
                stop_reader(reader_state)
                try:
                    with script_path.open(encoding="utf-8") as script:
                        run_script(shutter, script)
                except (OSError, ValueError) as exc:
                    print(f"Script error: {exc}")
                finally:
                    reader_state = start_reader()
                continue
            if command not in {"SPEED", "MOVE", "STOP", "ID"}:
                print(f"Unsupported command: {command}. Enter HELP for commands.")
                continue
            text = command + (f" {arguments[0]}" if arguments else "")
            shutter.serial.write((text + "\n").encode("ascii"))
            shutter.serial.flush()
    except KeyboardInterrupt:
        print()
    finally:
        stop_reader(reader_state)


def main() -> None:
    parser = argparse.ArgumentParser(description="Control the Auto Shutter")
    parser.add_argument("--port", help="serial port override (normally auto-detected)")
    parser.add_argument("--speed", type=int, help="microsteps per second")
    parser.add_argument("--script", type=Path, help="run commands from a file")
    parser.add_argument("angle", type=float, nargs="?", help="angle to move in degrees")
    args = parser.parse_args()

    if args.script is not None and args.angle is not None:
        parser.error("angle and --script cannot be used together")

    with AutoShutter.connect(args.port) as shutter:
        print(f"Connected to {shutter.port}")
        if args.script is not None:
            if args.speed is not None:
                print(shutter.set_speed(args.speed))
            with args.script.open(encoding="utf-8") as script:
                run_script(shutter, script)
        elif args.angle is not None:
            print(shutter.set_speed(args.speed if args.speed is not None else 500))
            print(shutter.move(args.angle))
        else:
            if args.speed is not None:
                print(shutter.set_speed(args.speed))
            interactive_terminal(shutter)


if __name__ == "__main__":
    main()
