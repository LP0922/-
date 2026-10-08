import importlib.util
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "device_maintenance.py"
SPEC = importlib.util.spec_from_file_location("device_maintenance", SCRIPT_PATH)
low_rate_scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(low_rate_scan)


class LowRateStartupScanTests(unittest.TestCase):
    def test_summary_accepts_a_stable_low_rate_candidate(self):
        candidate = {"candidate_id": "S-test", "frequency_hz": 55, "duty_permyriad": 1400}
        result = {
            "run_id": "feed-test",
            "result": "completed",
            "actual_duration_s": 20.0,
            "samples": [
                {"elapsed_s": 0.0, "mass_mg": 0.0},
                {"elapsed_s": 2.0, "mass_mg": 6.0},
                {"elapsed_s": 10.0, "mass_mg": 40.0},
                {"elapsed_s": 20.0, "mass_mg": 100.0},
            ],
        }

        summary = low_rate_scan.summarize_run(candidate, result, safety_stop_requested=False)

        self.assertTrue(summary["accepted_seed"])
        self.assertEqual(summary["mass_gain_mg"], 100.0)
        self.assertEqual(summary["average_rate_mg_s"], 5.0)
        self.assertEqual(summary["startup_delay_s"], 2.0)

    def test_summary_rejects_a_safety_cancelled_high_flow_candidate(self):
        candidate = {"candidate_id": "S-fast", "frequency_hz": 65, "duty_permyriad": 1600}
        result = {
            "run_id": "feed-fast",
            "result": "cancelled",
            "actual_duration_s": 5.0,
            "samples": [
                {"elapsed_s": 0.0, "mass_mg": 0.0},
                {"elapsed_s": 2.0, "mass_mg": 80.0},
                {"elapsed_s": 5.0, "mass_mg": 250.0},
            ],
        }

        summary = low_rate_scan.summarize_run(candidate, result, safety_stop_requested=True)

        self.assertFalse(summary["accepted_seed"])
        self.assertTrue(summary["safety_stop_requested"])


if __name__ == "__main__":
    unittest.main()
