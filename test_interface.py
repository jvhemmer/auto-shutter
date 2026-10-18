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
        self.responses = iter(self.responses_by_port[port])
        self.writes = []
        self.instances.append(self)

    def reset_input_buffer(self):
        pass

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
    @patch("interface.serial.Serial", FakeSerial)
    def test_explicit_port_still_requires_matching_id(self, _sleep):
        FakeSerial.responses_by_port = {"COM9": [b"SOME_OTHER_DEVICE\n"]}

        with self.assertRaises(interface.ShutterNotFoundError):
            interface.open_shutter("COM9", startup_delay=0, probe_timeout=0.01)

        self.assertFalse(FakeSerial.instances[0].is_open)


if __name__ == "__main__":
    unittest.main()
