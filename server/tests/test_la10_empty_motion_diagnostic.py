"""Pure simulation safety checks; no serial ports are opened."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from diagnose_la10_empty_motion import diagnose
from powder_sampling_control.device_adapters.la10_modbus_rtu import LA10Status, VibrationSettings


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Device:
    def __init__(self, *, code_after_move=0, initial_code=0, move=True, running=False):
        self.position = 350
        self.target = 350
        self.moves = []
        self.code_after_move = code_after_move
        self.initial_code = initial_code
        self.move = move
        self.running = running
        self.stops = 0

    def read_status(self):
        return LA10Status(self.position, self.target, 25, 0, 0, self.running,
                          self.code_after_move if self.moves else self.initial_code)

    def read_vibration_settings(self):
        return VibrationSettings(80, 1000, False)

    def enable(self):
        pass

    def move_relative(self, **kwargs):
        self.moves.append(kwargs)
        self.target = self.position + round(kwargs["distance_mm"] * 200) * (1 if kwargs["extend"] else -1)
        if self.move:
            self.position = self.target

    def stop_vibration(self):
        self.stops += 1

    def emergency_stop(self):
        self.stops += 1
        self.running = False


class EmptyMotionDiagnosticTests(unittest.TestCase):
    def test_normal_path_has_exactly_two_small_moves_and_no_vibration(self):
        device = Device()
        report = diagnose(device, clock=Clock())
        self.assertEqual(report["result"], "position_round_trip_completed")
        self.assertEqual(len(device.moves), 2)
        self.assertEqual(device.position, 350)
        self.assertTrue(report["stopped_confirmed"])
        self.assertEqual(report["vibration_start_commands"], 0)
        self.assertTrue(all(m["distance_mm"] <= 0.2 for m in device.moves))

    def test_nonzero_code_after_move_prevents_a_return_or_correction(self):
        device = Device(code_after_move=2)
        report = diagnose(device, clock=Clock())
        self.assertEqual(report["result"], "result_code_anomaly")
        self.assertEqual(len(device.moves), 1)
        self.assertTrue(report["stopped_confirmed"])

    def test_nonzero_final_baseline_aborts_before_motion(self):
        device = Device(initial_code=2)
        report = diagnose(device, clock=Clock())
        self.assertEqual(report["result"], "aborted")
        self.assertEqual(device.moves, [])

    def test_off_target_does_not_retry(self):
        device = Device(move=False)
        report = diagnose(device, clock=Clock())
        self.assertEqual(report["result"], "aborted")
        self.assertIn("off target", report["error"])
        self.assertEqual(len(device.moves), 1)

    def test_running_initial_state_is_stopped_without_diagnostic_motion(self):
        device = Device(running=True)
        report = diagnose(device, clock=Clock())
        self.assertEqual(report["result"], "aborted")
        self.assertEqual(device.moves, [])
        self.assertGreater(device.stops, 0)
        self.assertTrue(report["stopped_confirmed"])


if __name__ == "__main__":
    unittest.main()
