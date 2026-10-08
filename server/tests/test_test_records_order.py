import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import device_control_server as server


class TestRecordOrderingTests(unittest.TestCase):
    def test_cancelled_dispense_is_not_reported_as_passed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            logs = temp_root / "logs"
            logs.mkdir()
            (logs / "feedback_dispense_dispense-100mg-20260920_105830-test.json").write_text(
                json.dumps({
                    "run_id": "dispense-100mg-20260920_105830-test",
                    "test_type": "feedback_dispense",
                    "result": "cancelled",
                    "target_mass_mg": 100,
                    "final_mass_mg": None,
                }),
                encoding="utf-8",
            )
            original_root = server.PROJECT_ROOT
            server.PROJECT_ROOT = temp_root
            try:
                service = server.DeviceControlService.__new__(server.DeviceControlService)
                result = service.list_test_records(limit=200)
            finally:
                server.PROJECT_ROOT = original_root

        self.assertEqual(result["records"][0]["result"], "cancelled")
        self.assertEqual(result["records"][0]["status"], "cancelled")
        self.assertNotEqual(result["records"][0]["status"], "passed")

    def test_returns_latest_records_after_filtering_not_lexical_first_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            logs = temp_root / "logs"
            logs.mkdir()
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)

            for index in range(205):
                timestamp = start + timedelta(seconds=index)
                run_id = f"run-{timestamp.strftime('%Y%m%d_%H%M%S')}-{index:03d}"
                payload = {"run_id": run_id, "test_type": "feedback_dispense", "result": "completed"}
                # Deliberately reverse lexical filename priority: the newest
                # record must still be returned ahead of the older z-files.
                prefix = "aaa-newest" if index == 204 else f"zzz-old-{index:03d}"
                (logs / f"{prefix}.json").write_text(json.dumps(payload), encoding="utf-8")

            original_root = server.PROJECT_ROOT
            server.PROJECT_ROOT = temp_root
            try:
                service = server.DeviceControlService.__new__(server.DeviceControlService)
                result = service.list_test_records(limit=200)
            finally:
                server.PROJECT_ROOT = original_root

        records = result["records"]
        self.assertEqual(len(records), 200)
        self.assertEqual(records[0]["run_id"], "run-20260101_000324-204")
        self.assertEqual(records[-1]["run_id"], "run-20260101_000005-005")


if __name__ == "__main__":
    unittest.main()
