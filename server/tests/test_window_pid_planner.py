import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from powder_sampling_control.dispensing_algorithm import (
    WindowPidConfig,
    WindowPidPlanner,
    WindowPidStage,
    WindowPidState,
)


class WindowPidPlannerTests(unittest.TestCase):
    def test_coarse_feedforward_uses_high_window_and_reserves_tail(self):
        decision = WindowPidPlanner().next_decision(current_mass_mg=0.0)
        self.assertEqual(decision.stage, WindowPidStage.COARSE)
        self.assertEqual(decision.action.window_position_units, 650)
        self.assertEqual(decision.action.frequency_hz, 80)
        self.assertEqual(decision.expected_mass_mg, 220.0)
        self.assertEqual(decision.stop_mass_mg, 220.0)

    def test_pid_reduces_window_when_observed_rate_is_above_stage_target(self):
        decision = WindowPidPlanner().next_decision(
            current_mass_mg=350.0,
            observed_rate_mg_s=40.0,
            dt_s=1.0,
        )
        self.assertEqual(decision.stage, WindowPidStage.SLOW)
        self.assertLess(decision.pid_adjust_units, 0)
        self.assertLess(decision.action.window_position_units, 200)

    def test_pid_increases_window_when_observed_rate_is_below_target(self):
        decision = WindowPidPlanner().next_decision(
            current_mass_mg=350.0,
            observed_rate_mg_s=5.0,
            dt_s=1.0,
        )
        self.assertGreater(decision.pid_adjust_units, 0)
        self.assertGreaterEqual(decision.action.window_position_units, 200)

    def test_tail_prediction_can_stop_before_target(self):
        decision = WindowPidPlanner().next_decision(
            current_mass_mg=497.0,
            observed_rate_mg_s=30.0,
        )
        self.assertEqual(decision.stage, WindowPidStage.SETTLE)
        self.assertIsNone(decision.action)
        self.assertGreater(decision.predicted_tail_mg, 0)

    def test_no_flow_enters_recovery_after_timeout(self):
        planner = WindowPidPlanner()
        state = WindowPidState()
        decision = planner.next_decision(
            current_mass_mg=200.0,
            observed_rate_mg_s=0.0,
            state=state,
            dt_s=1.0,
        )
        self.assertNotEqual(decision.stage, WindowPidStage.RECOVERY)
        decision = planner.next_decision(
            current_mass_mg=200.0,
            observed_rate_mg_s=0.0,
            state=decision.next_state,
            dt_s=1.0,
        )
        self.assertEqual(decision.stage, WindowPidStage.RECOVERY)
        self.assertEqual(decision.action.window_position_units, 650)

    def test_action_window_is_bounded(self):
        planner = WindowPidPlanner(WindowPidConfig(min_window_position_units=100, max_window_position_units=700))
        decision = planner.next_decision(current_mass_mg=350.0, observed_rate_mg_s=0.0)
        self.assertGreaterEqual(decision.action.window_position_units, 100)
        self.assertLessEqual(decision.action.window_position_units, 700)


if __name__ == "__main__":
    unittest.main()
