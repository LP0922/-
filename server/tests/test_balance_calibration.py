import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from powder_sampling_control.device_adapters import (
    BalanceCalibrationPoint,
    fit_balance_calibration,
    load_balance_calibration,
)


class BalanceCalibrationTests(unittest.TestCase):
    def test_fits_count_to_milligram_conversion(self):
        calibration = fit_balance_calibration(
            [
                BalanceCalibrationPoint(0, 5),
                BalanceCalibrationPoint(100, 205),
                BalanceCalibrationPoint(500, 1005),
            ],
            calibration_id="test-calibration",
            created_at_utc="2026-08-17T00:00:00+00:00",
        )

        self.assertTrue(calibration.valid)
        self.assertAlmostEqual(calibration.scale_mg_per_count, 0.5)
        self.assertAlmostEqual(calibration.offset_mg, -2.5)
        self.assertAlmostEqual(calibration.mass_mg(405), 200.0)

    def test_rejects_missing_zero_point(self):
        with self.assertRaisesRegex(ValueError, "zero-mass"):
            fit_balance_calibration(
                [
                    BalanceCalibrationPoint(100, 100),
                    BalanceCalibrationPoint(200, 200),
                    BalanceCalibrationPoint(500, 500),
                ]
            )

    def test_marks_nonlinear_points_invalid(self):
        calibration = fit_balance_calibration(
            [
                BalanceCalibrationPoint(0, 0),
                BalanceCalibrationPoint(100, 100),
                BalanceCalibrationPoint(500, 300),
            ],
            maximum_allowed_residual_mg=2.0,
        )

        self.assertFalse(calibration.valid)
        self.assertGreater(calibration.max_abs_residual_mg, 2.0)

    def test_round_trips_validated_json(self):
        calibration = fit_balance_calibration(
            [
                BalanceCalibrationPoint(0, 0),
                BalanceCalibrationPoint(100, 100),
                BalanceCalibrationPoint(500, 500),
            ],
            calibration_id="round-trip",
            created_at_utc="2026-08-17T00:00:00+00:00",
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text(json.dumps(calibration.to_dict()), encoding="utf-8")
            loaded = load_balance_calibration(path)

        self.assertEqual(loaded.calibration_id, "round-trip")
        self.assertEqual(loaded.scale_mg_per_count, calibration.scale_mg_per_count)

    def test_rejects_conversion_tampered_after_validation(self):
        calibration = fit_balance_calibration(
            [
                BalanceCalibrationPoint(0, 0),
                BalanceCalibrationPoint(100, 100),
                BalanceCalibrationPoint(500, 500),
            ],
            calibration_id="tampered",
            created_at_utc="2026-08-17T00:00:00+00:00",
        )
        document = calibration.to_dict()
        document["conversion"]["scale_mg_per_count"] = 2.0
        with TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match its points"):
                load_balance_calibration(path)


if __name__ == "__main__":
    unittest.main()
