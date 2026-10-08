import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from powder_sampling_control.dispensing_algorithm import MassMotionEstimator


class MassMotionEstimatorTests(unittest.TestCase):
    def test_rate_and_prediction_use_500_mg_s_limit(self):
        estimator = MassMotionEstimator()
        state = None
        for index in range(101):
            timestamp = index * 0.25
            state = estimator.update(timestamp, round(200.0 * timestamp))
        self.assertTrue(state.valid)
        self.assertGreater(state.rate_mg_s, 100.0)
        self.assertLessEqual(state.rate_mg_s, 500.0)
        self.assertLessEqual(state.predicted_rate_mg_s, 500.0)

    def test_tracks_constant_rate_with_quantized_mass(self):
        estimator = MassMotionEstimator()
        state = None
        for index in range(41):
            timestamp = index * 0.25
            mass = round(5.0 * timestamp)
            state = estimator.update(timestamp, mass)
        self.assertTrue(state.valid)
        self.assertAlmostEqual(state.rate_mg_s, 5.0, delta=1.0)
        self.assertAlmostEqual(state.acceleration_mg_s2, 0.0, delta=1.5)

    def test_positive_acceleration_raises_predicted_rate(self):
        estimator = MassMotionEstimator()
        state = None
        for index in range(41):
            timestamp = index * 0.25
            mass = round(0.5 * 2.0 * timestamp * timestamp)
            state = estimator.update(timestamp, mass)
        self.assertTrue(state.valid)
        self.assertGreater(state.acceleration_mg_s2, 0.0)
        self.assertGreater(state.predicted_rate_mg_s, state.rate_mg_s)
        self.assertGreaterEqual(state.predicted_mass_mg, state.filtered_mass_mg)

    def test_rejects_non_increasing_timestamp(self):
        estimator = MassMotionEstimator()
        estimator.update(1.0, 0.0)
        with self.assertRaises(ValueError):
            estimator.update(1.0, 1.0)

    def test_filtered_jerk_settles_for_constant_quantized_rate(self):
        estimator = MassMotionEstimator()
        state = None
        for index in range(81):
            timestamp = index * 0.25
            state = estimator.update(timestamp, round(7.0 * timestamp))
        self.assertTrue(state.valid)
        self.assertLess(abs(state.jerk_mg_s3), 2.0)


if __name__ == "__main__":
    unittest.main()
