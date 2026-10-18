import unittest
from types import SimpleNamespace
from unittest.mock import patch

import interface


class FakeSerial:
    responses_by_port = {}
    instances = []

    def __init__(self, port, baudrate, timeout, write_timeout):
        self.port = port
        self.timeout = timeout
        self.is_open = True
        self.responses = iter(self.responses_by_port.get(port, []))
        self.writes = []
        self.instances.append(self)

    def reset_input_buffer(self):
        pass

    @property
    def in_waiting(self):
        return 0

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        pass

    def readline(self):
        return next(self.responses, b"")

    def close(self):
        self.is_open = False


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        FakeSerial.instances = []

    @patch("interface.time.sleep", return_value=None)
    @patch("interface.serial.Serial", FakeSerial)
    @patch("interface.list_ports.comports")
    def test_finds_device_by_firmware_id(self, comports, _sleep):
        comports.return_value = [
            SimpleNamespace(device="usb-a-wrong", vid=0x1234),
            SimpleNamespace(device="usb-b-shutter", vid=0x2341),
        ]
        FakeSerial.responses_by_port = {
            "usb-a-wrong": [b"NOT_THE_SHUTTER\n"],
            "usb-b-shutter": [b"AUTO_SHUTTER_V1\r\n"],
        }

        connection = interface.open_shutter(startup_delay=0, probe_timeout=0.01)

        self.assertEqual(connection.port, "usb-b-shutter")
        self.assertTrue(connection.is_open)
        self.assertEqual(connection.writes, [b"ID\n"])
        self.assertFalse(FakeSerial.instances[0].is_open)

    @patch("interface.time.sleep", return_value=None)
    def test_speed_retries_after_dropped_windows_command(self, _sleep):
        connection = FakeSerial("COM5", interface.BAUD_RATE, 1, 1)
        connection.responses = iter([b"", b"SPEED SET\r\n"])
        shutter = interface.AutoShutter(connection)

        response = shutter.set_speed(100)

        self.assertEqual(response, "SPEED SET")
        self.assertEqual(connection.writes, [b"SPEED 100\n", b"SPEED 100\n"])

    def test_speed_rejects_values_outside_firmware_range(self):
        connection = FakeSerial("COM5", interface.BAUD_RATE, 1, 1)
        shutter = interface.AutoShutter(connection)

        with self.assertRaisesRegex(ValueError, "between 50 and 2000"):
            shutter.set_speed(10)

    def test_negative_angle_is_sent_with_minus_sign(self):
        connection = FakeSerial("COM5", interface.BAUD_RATE, 1, 1)
        connection.responses = iter([b"MOVING\n"])
        shutter = interface.AutoShutter(connection)

        self.assertEqual(shutter.move(-90), "MOVING")
        self.assertEqual(connection.writes, [b"MOVE -90\n"])

    @patch("interface.time.sleep", return_value=None)
    def test_runs_command_script_on_one_connection(self, sleep):
        connection = FakeSerial("COM5", interface.BAUD_RATE, 1, 1)
        connection.responses = iter([b"SPEED SET\n", b"MOVING\n", b"STOPPED\n"])
        shutter = interface.AutoShutter(connection)

        interface.run_script(
            shutter,
            ["# preset\n", "SPEED 100\n", "MOVE 90\n", "WAIT 2.5\n", "STOP\n"],
        )

        self.assertEqual(
            connection.writes,
            [b"SPEED 100\n", b"MOVE 90\n", b"STOP\n"],
        )
        sleep.assert_called_once_with(2.5)

    @patch("interface.time.sleep", return_value=None)
    def test_script_loop_repeats_only_indented_block(self, sleep):
        connection = FakeSerial("COM5", interface.BAUD_RATE, 1, 1)
        connection.responses = iter(
            [b"SPEED SET\n", b"MOVING\n", b"MOVING\n", b"MOVING\n"]
        )
        shutter = interface.AutoShutter(connection)

        interface.run_script(
            shutter,
            [
                "SPEED 250\n",
                "LOOP 2\n",
                "\tMOVE 90\n",
                "\tWAIT 5\n",
                "MOVE -90\n",
            ],
        )

        self.assertEqual(
            connection.writes,
            [b"SPEED 250\n", b"MOVE 90\n", b"MOVE 90\n", b"MOVE -90\n"],
        )
        self.assertEqual(sleep.call_count, 2)

    def test_script_loop_requires_indented_block(self):
        connection = FakeSerial("COM5", interface.BAUD_RATE, 1, 1)
        shutter = interface.AutoShutter(connection)

        with self.assertRaisesRegex(ValueError, "script line 1.*indented block"):
            interface.run_script(shutter, ["LOOP 2\n", "MOVE 90\n"])

    def test_script_reports_bad_line_number(self):
        connection = FakeSerial("COM5", interface.BAUD_RATE, 1, 1)
        shutter = interface.AutoShutter(connection)

        with self.assertRaisesRegex(ValueError, "script line 2"):
            interface.run_script(shutter, ["# preset\n", "OPEN\n"])

    @patch("interface.time.sleep", return_value=None)
    @patch("interface.serial.Serial", FakeSerial)
    def test_explicit_port_still_requires_matching_id(self, _sleep):
        FakeSerial.responses_by_port = {"COM9": [b"SOME_OTHER_DEVICE\n"]}

        with self.assertRaises(interface.ShutterNotFoundError):
            interface.open_shutter("COM9", startup_delay=0, probe_timeout=0.01)

        self.assertFalse(FakeSerial.instances[0].is_open)


if __name__ == "__main__":
    unittest.main()
