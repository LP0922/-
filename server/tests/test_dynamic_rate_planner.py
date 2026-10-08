import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from powder_sampling_control.dispensing_algorithm import DynamicRatePlanner, RateStage


class DynamicRatePlannerTests(unittest.TestCase):
    def setUp(self):
        self.planner = DynamicRatePlanner()

    def test_mass_selects_requested_rate_stage(self):
        self.assertEqual(self.planner.stage_for_mass(419.9), RateStage.COARSE)
        self.assertEqual(self.planner.stage_for_mass(420.0), RateStage.SLOW)
        self.assertEqual(self.planner.stage_for_mass(470.0), RateStage.FINE)

    def test_coarse_increases_frequency_when_flow_is_below_10_mg_s(self):
        decision = self.planner.decide(
            filtered_mass_mg=200.0, measured_rate_mg_s=2.0, current_frequency_hz=60
        )
        self.assertEqual(decision.target_rate_mg_s, 10.0)
        self.assertEqual(decision.next_frequency_hz, 61)

    def test_coarse_holds_between_target_and_twice_target(self):
        decision = self.planner.decide(
            filtered_mass_mg=200.0, measured_rate_mg_s=12.0, current_frequency_hz=70
        )
        self.assertEqual(decision.next_frequency_hz, 70)

    def test_coarse_gradually_reduces_above_twice_target(self):
        decision = self.planner.decide(
            filtered_mass_mg=200.0, measured_rate_mg_s=23.5, current_frequency_hz=73
        )
        self.assertEqual(decision.target_rate_mg_s, 10.0)
        self.assertEqual(decision.next_frequency_hz, 72)
        self.assertIn("twice", decision.reason)

    def test_exactly_twice_target_does_not_trigger_overspeed(self):
        decision = self.planner.decide(
            filtered_mass_mg=200.0, measured_rate_mg_s=20.0, current_frequency_hz=73
        )
        self.assertEqual(decision.next_frequency_hz, 73)

    def test_slow_and_fine_track_lower_targets(self):
        slow = self.planner.decide(
            filtered_mass_mg=430.0, measured_rate_mg_s=12.0, current_frequency_hz=70
        )
        fine = self.planner.decide(
            filtered_mass_mg=480.0, measured_rate_mg_s=1.0, current_frequency_hz=40
        )
        self.assertEqual(slow.target_rate_mg_s, 7.0)
        self.assertLess(slow.next_frequency_hz, 70)
        self.assertEqual(fine.target_rate_mg_s, 5.0)
        self.assertGreater(fine.next_frequency_hz, 40)

    def test_frequency_is_bounded_at_80_hz(self):
        decision = self.planner.decide(
            filtered_mass_mg=100.0, measured_rate_mg_s=0.0, current_frequency_hz=78
        )
        self.assertEqual(decision.next_frequency_hz, 79)

    def test_invalid_rate_history_holds_initial_ilc_frequency(self):
        decision = self.planner.decide(
            filtered_mass_mg=0.0,
            measured_rate_mg_s=0.0,
            current_frequency_hz=60,
            rate_valid=False,
        )
        self.assertEqual(decision.next_frequency_hz, 60)

    def test_update_interval_shortens_as_rate_error_grows(self):
        self.assertEqual(self.planner.update_interval_for_error(10.0), 0.5)
        self.assertEqual(self.planner.update_interval_for_error(-8.0), 0.5)
        self.assertEqual(self.planner.update_interval_for_error(5.0), 1.0)
        self.assertEqual(self.planner.update_interval_for_error(3.0), 1.5)
        self.assertEqual(self.planner.update_interval_for_error(1.0), 2.5)

    def test_decision_reports_rate_error_and_next_interval(self):
        decision = self.planner.decide(
            filtered_mass_mg=100.0, measured_rate_mg_s=0.0, current_frequency_hz=60
        )
        self.assertEqual(decision.rate_error_mg_s, 10.0)
        self.assertEqual(decision.next_update_interval_s, 0.5)

    def test_positive_acceleration_suppresses_unnecessary_increase(self):
        decision = self.planner.decide(
            filtered_mass_mg=200.0,
            measured_rate_mg_s=6.0,
            predicted_rate_mg_s=8.5,
            acceleration_mg_s2=5.0,
            current_frequency_hz=60,
        )
        self.assertEqual(decision.next_frequency_hz, 60)
        self.assertIn("accelerating", decision.reason)

    def test_predicted_overspeed_reduces_before_measured_rate_reaches_twice_target(self):
        decision = self.planner.decide(
            filtered_mass_mg=200.0,
            measured_rate_mg_s=15.0,
            predicted_rate_mg_s=21.0,
            acceleration_mg_s2=8.0,
            current_frequency_hz=69,
        )
        self.assertEqual(decision.next_frequency_hz, 68)

    def test_predicted_mass_enters_slow_stage_early(self):
        decision = self.planner.decide(
            filtered_mass_mg=410.0,
            predicted_mass_mg=425.0,
            measured_rate_mg_s=10.0,
            predicted_rate_mg_s=12.0,
            acceleration_mg_s2=2.0,
            current_frequency_hz=65,
        )
        self.assertEqual(decision.stage, RateStage.SLOW)
        self.assertEqual(decision.target_rate_mg_s, 7.0)
        self.assertEqual(decision.next_frequency_hz, 64)

    def test_frequency_change_is_always_one_hertz(self):
        scenarios = [
            dict(filtered_mass_mg=100.0, measured_rate_mg_s=0.0),
            dict(filtered_mass_mg=430.0, measured_rate_mg_s=20.0),
            dict(filtered_mass_mg=480.0, measured_rate_mg_s=1.0),
        ]
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                decision = self.planner.decide(current_frequency_hz=60, **scenario)
                self.assertLessEqual(abs(decision.next_frequency_hz - 60), 1)

    def test_jerk_guard_holds_during_post_adjustment_transient(self):
        decision = self.planner.decide(
            filtered_mass_mg=200.0,
            measured_rate_mg_s=4.0,
            predicted_rate_mg_s=5.0,
            jerk_mg_s3=20.0,
            seconds_since_frequency_change=0.25,
            current_frequency_hz=60,
        )
        self.assertEqual(decision.next_frequency_hz, 60)
        self.assertIn("transient", decision.reason)


if __name__ == "__main__":
    unittest.main()
