import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from powder_sampling_control.device_adapters.at8811c_modbus_rtu import (
    AT8811CConfig,
    AT8811CModbusRTU,
    CommunicationError,
    DeviceUnavailableError,
    ProtocolError,
    _append_crc,
    modbus_crc16,
)


class FakeSerial:
    def __init__(self, responses):
        self.responses = list(responses)
        self.buffer = b""
        self.writes = []
        self.closed = False

    def reset_input_buffer(self):
        self.buffer = b""

    def write(self, data):
        self.writes.append(data)
        self.buffer += self.responses.pop(0)
        return len(data)

    def flush(self):
        pass

    def read(self, size=1):
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data

    def close(self):
        self.closed = True


class OSErrorSerial(FakeSerial):
    def write(self, _data):
        raise OSError(22, "Invalid argument")


def response(function, payload):
    return _append_crc(bytes((1, function)) + payload)


class AT8811CModbusRTUTests(unittest.TestCase):
    def test_crc_matches_manual_read_weight_example(self):
        frame = bytes.fromhex("01 03 00 01 00 02")
        self.assertEqual(modbus_crc16(frame), 0xCB95)
        self.assertEqual(_append_crc(frame), bytes.fromhex("01 03 00 01 00 02 95 CB"))

    def test_reads_weight_and_stability(self):
        serial = FakeSerial(
            [
                response(0x03, bytes((4, 0, 0, 1, 0x62))),
                response(0x03, bytes((2, 0x03, 0x00))),
            ]
        )
        driver = AT8811CModbusRTU(
            AT8811CConfig(scale_mg_per_count=0.01), serial_port=serial
        )

        measurement = driver.read_measurement()

        self.assertEqual(measurement.raw_count, 354)
        self.assertAlmostEqual(measurement.mass_mg, 3.54)
        self.assertTrue(measurement.stable)
        self.assertTrue(measurement.in_zero_band)
        self.assertEqual(serial.writes[0], bytes.fromhex("01 03 00 01 00 02 95 CB"))
        self.assertEqual(serial.writes[1], bytes.fromhex("01 03 00 03 00 01 74 0A"))

    def test_rejects_bad_crc(self):
        invalid_response = bytes.fromhex("01 03 04 00 00 01 62 00 00")
        driver = AT8811CModbusRTU(
            AT8811CConfig(retries=0), serial_port=FakeSerial([invalid_response])
        )

        with self.assertRaises(ProtocolError):
            driver.read_raw_weight()

    def test_zero_requires_state_machine_authorization(self):
        serial = FakeSerial([response(0x10, bytes.fromhex("00 01 00 02"))])
        driver = AT8811CModbusRTU(AT8811CConfig(), serial_port=serial)

        with self.assertRaises(PermissionError):
            driver.zero()
        driver.zero(authorized=True)

        self.assertEqual(serial.writes[0], bytes.fromhex("01 10 00 01 00 02 04 00 00 00 00 32 63"))

    def test_reads_raw_holding_register_words_for_diagnostics(self):
        serial = FakeSerial([response(0x03, bytes((4, 0x12, 0x34, 0xAB, 0xCD)))])
        driver = AT8811CModbusRTU(AT8811CConfig(), serial_port=serial)

        words = driver.read_holding_registers(14, 2)

        self.assertEqual(words, (0x1234, 0xABCD))
        self.assertEqual(serial.writes[0], bytes.fromhex("01 03 00 0E 00 02 A5 C8"))

    def test_failure_limit_reopens_the_transport_on_the_next_request(self):
        recovered_serial = FakeSerial(
            [response(0x03, bytes((4, 0, 0, 0, 42)))]
        )
        driver = AT8811CModbusRTU(
            AT8811CConfig(retries=0, max_consecutive_failures=1),
            serial_port=FakeSerial([b""]),
            serial_factory=lambda **_kwargs: recovered_serial,
        )

        with self.assertRaises(DeviceUnavailableError):
            driver.read_raw_weight()
        self.assertEqual(driver.read_raw_weight(), 42)
        self.assertTrue(driver.healthy)

    def test_reset_connection_recovers_from_the_failure_limit(self):
        recovered_serial = FakeSerial(
            [response(0x03, bytes((4, 0, 0, 0, 42)))]
        )
        driver = AT8811CModbusRTU(
            AT8811CConfig(retries=0, max_consecutive_failures=1),
            serial_port=FakeSerial([b""]),
            serial_factory=lambda **_kwargs: recovered_serial,
        )

        with self.assertRaisesRegex(
            DeviceUnavailableError,
            "failure limit reached.*timed out",
        ):
            driver.read_raw_weight()

        driver.reset_connection()

        self.assertEqual(driver.read_raw_weight(), 42)
        self.assertTrue(driver.healthy)

    def test_native_serial_oserror_is_wrapped_with_port_context(self):
        driver = AT8811CModbusRTU(
            AT8811CConfig(port="COM11", retries=0),
            serial_port=OSErrorSerial([]),
        )

        with self.assertRaisesRegex(CommunicationError, "COM11.*Invalid argument"):
            driver.read_raw_weight()


if __name__ == "__main__":
    unittest.main()
