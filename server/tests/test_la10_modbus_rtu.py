import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from powder_sampling_control.device_adapters.la10_modbus_rtu import (
    LA10CommunicationError,
    LA10Config,
    LA10FaultError,
    LA10ModbusRTU,
    _append_crc,
    modbus_crc16,
)


class FakeSerial:
    def __init__(self, responses):
        self.responses = list(responses)
        self.buffer = b""
        self.writes = []

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
        pass


class OSErrorSerial(FakeSerial):
    def write(self, _data):
        raise OSError(22, "Invalid argument")


def response(function, payload):
    return _append_crc(bytes((1, function)) + payload)


class LA10ModbusRTUTests(unittest.TestCase):
    def test_crc_matches_documented_motion_request(self):
        frame = bytes.fromhex("01 10 00 01 00 04 08 00 01 00 FA 00 64 00 01")
        self.assertEqual(modbus_crc16(frame), 0x7203)
        self.assertEqual(_append_crc(frame), bytes.fromhex("01 10 00 01 00 04 08 00 01 00 FA 00 64 00 01 03 72"))

    def test_enable_writes_documented_control_command(self):
        serial = FakeSerial([response(0x06, bytes.fromhex("00 00 00 01"))])
        driver = LA10ModbusRTU(LA10Config(port="COM9"), serial_port=serial)

        driver.enable()

        self.assertEqual(serial.writes[0], bytes.fromhex("01 06 00 00 00 01 48 0A"))

    def test_move_relative_writes_all_motion_registers_atomically(self):
        no_fault_status = response(0x03, bytes((14,)) + bytes(14))
        motion_ack = response(0x10, bytes.fromhex("00 01 00 04"))
        serial = FakeSerial([no_fault_status, motion_ack])
        driver = LA10ModbusRTU(LA10Config(port="COM9"), serial_port=serial)

        driver.move_relative(extend=True, distance_mm=2.5, speed_mm_s=1.0)

        self.assertEqual(
            serial.writes[1],
            bytes.fromhex("01 10 00 01 00 04 08 00 01 00 FA 00 64 00 01 03 72"),
        )

    def test_status_decodes_motion_and_fault_fields(self):
        payload = bytes.fromhex("0E 00 0D AC FF FB 01 F4 00 09 00 01 00 00")
        driver = LA10ModbusRTU(
            LA10Config(port="COM9"), serial_port=FakeSerial([response(0x03, bytes((14,)) + payload)])
        )

        status = driver.read_status()

        self.assertEqual(status.position_units, 3584)
        self.assertAlmostEqual(status.position_mm, 17.92)
        self.assertEqual(status.temperature_c, -5)
        self.assertEqual(status.current_ma, 500)
        self.assertTrue(status.is_running)
        self.assertEqual(status.fault_names, ("stall", "motor_fault"))

    def test_move_is_rejected_when_fault_is_active(self):
        fault_status = response(0x03, bytes((14,)) + bytes.fromhex("00 00 00 00 00 00 00 00 00 01 00 00 00 00"))
        driver = LA10ModbusRTU(LA10Config(port="COM9"), serial_port=FakeSerial([fault_status]))

        with self.assertRaises(LA10FaultError):
            driver.move_relative(extend=False, distance_mm=1.0, speed_mm_s=1.0)

    def test_start_vibration_writes_frequency_duty_and_enable_atomically(self):
        enable_ack = response(0x06, bytes.fromhex("00 00 00 01"))
        vibration_ack = response(0x10, bytes.fromhex("00 0C 00 03"))
        serial = FakeSerial([enable_ack, vibration_ack])
        driver = LA10ModbusRTU(LA10Config(port="COM9"), serial_port=serial)

        driver.start_vibration(frequency_hz=60, duty_permyriad=1000)

        self.assertEqual(
            serial.writes[0], _append_crc(bytes.fromhex("01 06 00 00 00 01"))
        )
        self.assertEqual(
            serial.writes[1],
            _append_crc(bytes.fromhex("01 10 00 0C 00 03 06 00 3C 03 E8 00 01")),
        )

    def test_stop_vibration_writes_zero_to_enable_register(self):
        stop_ack = response(0x06, bytes.fromhex("00 0E 00 00"))
        serial = FakeSerial([stop_ack])
        driver = LA10ModbusRTU(LA10Config(port="COM9"), serial_port=serial)

        driver.stop_vibration()

        self.assertEqual(
            serial.writes[0], _append_crc(bytes.fromhex("01 06 00 0E 00 00"))
        )

    def test_update_vibration_parameters_does_not_write_enable_register(self):
        vibration_ack = response(0x10, bytes.fromhex("00 0C 00 02"))
        serial = FakeSerial([vibration_ack])
        driver = LA10ModbusRTU(LA10Config(port="COM9"), serial_port=serial)

        driver.update_vibration_parameters(frequency_hz=40, duty_permyriad=5000)

        self.assertEqual(
            serial.writes[0],
            _append_crc(bytes.fromhex("01 10 00 0C 00 02 04 00 28 13 88")),
        )

    def test_update_vibration_frequency_writes_only_register_12(self):
        frequency_ack = response(0x06, bytes.fromhex("00 0C 00 46"))
        serial = FakeSerial([frequency_ack])
        driver = LA10ModbusRTU(LA10Config(port="COM9"), serial_port=serial)

        driver.update_vibration_frequency(70)

        self.assertEqual(
            serial.writes[0], _append_crc(bytes.fromhex("01 06 00 0C 00 46"))
        )

    def test_update_vibration_duty_writes_only_register_13(self):
        duty_ack = response(0x06, bytes.fromhex("00 0D 0B B8"))
        serial = FakeSerial([duty_ack])
        driver = LA10ModbusRTU(LA10Config(port="COM9"), serial_port=serial)

        driver.update_vibration_duty(3000)

        self.assertEqual(
            serial.writes[0], _append_crc(bytes.fromhex("01 06 00 0D 0B B8"))
        )

    def test_manual_write_allows_documented_vibration_duty_register(self):
        duty_ack = response(0x06, bytes.fromhex("00 0D 07 D0"))
        serial = FakeSerial([duty_ack])
        driver = LA10ModbusRTU(LA10Config(port="COM9"), serial_port=serial)

        driver.write_manual_register(13, 2000)

        self.assertEqual(
            serial.writes[0], _append_crc(bytes.fromhex("01 06 00 0D 07 D0"))
        )

    def test_manual_write_rejects_status_register(self):
        driver = LA10ModbusRTU(LA10Config(port="COM9"), serial_port=FakeSerial([]))

        with self.assertRaises(ValueError):
            driver.write_manual_register(9, 0)

    def test_vibration_settings_enforce_documented_range(self):
        driver = LA10ModbusRTU(LA10Config(port="COM9"), serial_port=FakeSerial([]))

        with self.assertRaises(ValueError):
            driver.start_vibration(frequency_hz=9, duty_permyriad=1000)
        with self.assertRaises(ValueError):
            driver.start_vibration(frequency_hz=60, duty_permyriad=5001)

    def test_wait_can_require_a_running_transition(self):
        stopped = response(0x03, bytes((14,)) + bytes(14))
        running = response(0x03, bytes((14,)) + bytes.fromhex("00 00 00 00 00 00 00 00 00 00 00 01 00 00"))
        serial = FakeSerial([stopped, running, stopped])
        driver = LA10ModbusRTU(LA10Config(port="COM9"), serial_port=serial)

        status = driver.wait_until_stopped(
            timeout_s=1.0,
            poll_interval_s=0.001,
            require_running_transition=True,
        )

        self.assertFalse(status.is_running)

    def test_native_serial_oserror_is_wrapped_with_port_context(self):
        driver = LA10ModbusRTU(
            LA10Config(port="COM12", retries=0),
            serial_port=OSErrorSerial([]),
        )

        with self.assertRaisesRegex(LA10CommunicationError, "COM12.*Invalid argument"):
            driver.update_vibration_frequency(50)


if __name__ == "__main__":
    unittest.main()
