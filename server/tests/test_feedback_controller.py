import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from powder_sampling_control.dispensing_algorithm import (
    ContinuousFeedbackController,
    FeedbackControllerSettings,
    FeedbackInitialParameters,
    FeedbackObservation,
    FeedbackStage,
)


def observation(mass, predicted_mass, predicted_rate, acceleration=0.0, valid=True):
    return FeedbackObservation(
        mass_mg=mass,
        predicted_mass_mg=predicted_mass,
        rate_mg_s=predicted_rate,
        predicted_rate_mg_s=predicted_rate,
        acceleration_mg_s2=acceleration,
        valid=valid,
    )


class ContinuousFeedbackControllerTests(unittest.TestCase):
    def seed(self, target):
        return ContinuousFeedbackController(
            target_mass_mg=target,
            initial=FeedbackInitialParameters(
                frequency_hz=60,
                duty_permyriad=2000,
                window_position_units=500,
            ),
        )

    def test_coarse_fraction_is_target_mass_dependent(self):
        self.assertAlmostEqual(self.seed(99).coarse_threshold_mg(), 69.3)
        self.assertAlmostEqual(self.seed(100).coarse_threshold_mg(), 75.0)
        self.assertAlmostEqual(self.seed(500).coarse_threshold_mg(), 400.0)

    def test_feedback_moves_duty_without_changing_frequency(self):
        controller = self.seed(500)
        decision = controller.step(observation(100, 100, 2), timestamp_s=0.0)
        self.assertEqual(decision.stage, FeedbackStage.COARSE)
        self.assertGreater(decision.duty_after_permyriad, decision.duty_before_permyriad)
        self.assertEqual(decision.frequency_hz, 60)
        self.assertEqual(decision.rate_error_mg_s, 8.0)

    def test_predicted_overspeed_reduces_duty(self):
        controller = self.seed(500)
        decision = controller.step(observation(100, 100, 20), timestamp_s=0.0)
        self.assertLess(decision.duty_after_permyriad, decision.duty_before_permyriad)
        self.assertIn("overspeed", decision.reason)

    def test_fixed_prefeed_bypasses_the_rate_ceiling_and_overspeed_guard(self):
        controller = self.seed(2000)
        decision = controller.step(
            observation(100, 100, 100),
            timestamp_s=0.0,
            bypass_rate_control=True,
        )
        self.assertEqual(decision.duty_after_permyriad, decision.duty_before_permyriad)
        self.assertNotIn("overspeed", decision.reason)

    def test_controller_enters_fine_stage_at_coarse_threshold(self):
        decision = self.seed(500).step(observation(400, 401, 5), timestamp_s=0.0)
        self.assertEqual(decision.stage, FeedbackStage.FINE)
        self.assertEqual(decision.coarse_threshold_mg, 400.0)
        self.assertEqual(decision.target_rate_mg_s, 5.0)

    def test_precision_tail_uses_the_lower_rate_target(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(60, 2000, 500),
            settings=FeedbackControllerSettings(
                fine_rate_mg_s=12,
                precision_rate_mg_s=8,
                precision_start_remaining_mg=50,
            ),
        )
        decision = controller.step(observation(450, 450, 8), timestamp_s=0.0)
        self.assertEqual(decision.stage, FeedbackStage.FINE)
        self.assertEqual(decision.target_rate_mg_s, 8)

    def test_delay_compensated_tail_stops_before_measured_target(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(80, 2000, 200),
            settings=FeedbackControllerSettings(
                allowed_underweight_mg=10,
                stop_target_offset_mg=5,
                settle_confirmations=1,
                stop_prediction_horizon_s=1.0,
                fixed_tail_mass_mg=2.0,
            ),
        )
        decision = controller.step(
            observation(479, 482, 18.8, acceleration=1.0),
            timestamp_s=0.0,
        )
        self.assertTrue(decision.stop_requested)
        self.assertGreaterEqual(decision.projected_stop_mass_mg, 495)
        self.assertGreater(decision.estimated_tail_mg, 20)

    def test_persistent_error_trims_window_on_slow_loop(self):
        controller = self.seed(500)
        decisions = [
            controller.step(observation(100, 100, 0), timestamp_s=index * 0.5)
            for index in range(6)
        ]
        self.assertTrue(any(decision.window_changed for decision in decisions))
        self.assertEqual(decisions[-1].frequency_hz, 60)

    def test_target_reached_requires_two_confirmations(self):
        controller = self.seed(100)
        first = controller.step(observation(100, 100, 2), timestamp_s=0.0)
        second = controller.step(observation(100, 100, 2), timestamp_s=0.5)
        self.assertNotEqual(first.stage, FeedbackStage.SETTLE)
        self.assertEqual(second.stage, FeedbackStage.SETTLE)
        self.assertTrue(second.stop_requested)

    def test_predicted_target_can_authorize_early_stop_after_confirmation(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=100,
            initial=FeedbackInitialParameters(60, 2000, 500),
            settings=FeedbackControllerSettings(
                force_stop_max_mass_mg=98.5,
            ),
        )
        first = controller.step(observation(98, 101, 2), timestamp_s=0.0)
        second = controller.step(observation(99, 102, 2), timestamp_s=0.5)
        self.assertEqual(first.stage, FeedbackStage.FINE)
        self.assertEqual(second.stage, FeedbackStage.SETTLE)
        self.assertTrue(second.stop_requested)

    def test_predictive_stop_is_allowed_inside_configured_underweight_window(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(60, 2000, 500),
            settings=FeedbackControllerSettings(
                allowed_underweight_mg=10,
                allowed_overweight_mg=15,
            ),
        )
        first = controller.step(observation(490, 501, 5), timestamp_s=0.0)
        second = controller.step(observation(491, 502, 5), timestamp_s=0.5)
        self.assertFalse(first.stop_requested)
        self.assertTrue(second.stop_requested)
        self.assertEqual(second.stage, FeedbackStage.SETTLE)

    def test_predictive_stop_can_trigger_below_force_stop_threshold(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(60, 2000, 500),
            settings=FeedbackControllerSettings(
                allowed_underweight_mg=10,
                force_stop_max_mass_mg=495.0,
            ),
        )
        decisions = [
            controller.step(observation(489, 505, 5), timestamp_s=index * 0.5)
            for index in range(2)
        ]
        self.assertFalse(decisions[0].stop_requested)
        self.assertTrue(decisions[0].predictive_stop_candidate)
        self.assertEqual(decisions[0].stop_confirmation_count, 1)
        self.assertTrue(decisions[1].stop_requested)
        self.assertLess(489, controller.settings.force_stop_max_mass_mg)
        self.assertIn("predicted tail confirmed", decisions[1].reason)

    def test_force_stop_remains_immediate_without_predictive_confirmation(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(60, 2000, 500),
            settings=FeedbackControllerSettings(
                allowed_underweight_mg=10,
                force_stop_max_mass_mg=490.0,
                settle_confirmations=3,
            ),
        )

        decision = controller.step(observation(490, 490, 1), timestamp_s=0.0)

        self.assertTrue(decision.stop_requested)
        self.assertIn("force stop", decision.reason)
        self.assertFalse(decision.predictive_stop_candidate)

    def test_predictive_stop_confirmation_resets_after_transient_candidate(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(60, 2000, 500),
            settings=FeedbackControllerSettings(
                allowed_underweight_mg=10,
                force_stop_max_mass_mg=495.0,
                settle_confirmations=2,
            ),
        )

        first = controller.step(observation(480, 505, 5), timestamp_s=0.0)
        second = controller.step(observation(481, 481, 1), timestamp_s=0.5)
        third = controller.step(observation(482, 505, 5), timestamp_s=1.0)

        self.assertTrue(first.predictive_stop_candidate)
        self.assertFalse(second.predictive_stop_candidate)
        self.assertEqual(second.stop_confirmation_count, 0)
        self.assertTrue(third.predictive_stop_candidate)
        self.assertFalse(third.stop_requested)
        self.assertEqual(third.stop_confirmation_count, 1)

    def test_fast_predictive_stop_uses_one_confirmation_at_configured_rate(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(60, 2000, 500),
            settings=FeedbackControllerSettings(
                allowed_underweight_mg=10,
                fast_predictive_stop_enabled=True,
                fast_predictive_stop_rate_mg_s=20,
                fast_predictive_stop_confirmations=1,
            ),
        )

        decision = controller.step(observation(480, 500, 20), timestamp_s=0.0)

        self.assertTrue(decision.stop_requested)
        self.assertTrue(decision.predictive_stop_candidate)
        self.assertEqual(decision.stop_confirmation_count, 1)
        self.assertEqual(decision.stop_confirmation_required, 1)

    def test_fast_predictive_stop_keeps_two_confirmations_below_rate_threshold(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(60, 2000, 500),
            settings=FeedbackControllerSettings(
                allowed_underweight_mg=10,
                fast_predictive_stop_enabled=True,
                fast_predictive_stop_rate_mg_s=20,
                fast_predictive_stop_confirmations=1,
            ),
        )

        first = controller.step(observation(480, 500, 10), timestamp_s=0.0)
        second = controller.step(observation(480, 500, 10), timestamp_s=0.5)

        self.assertFalse(first.stop_requested)
        self.assertEqual(first.stop_confirmation_required, 2)
        self.assertTrue(second.stop_requested)

    def test_projected_safety_stop_is_immediate_near_the_target(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(60, 2000, 500),
            settings=FeedbackControllerSettings(
                allowed_underweight_mg=10,
                allowed_overweight_mg=10,
                settle_confirmations=3,
                projected_safety_stop_enabled=True,
                projected_safety_stop_offset_mg=5,
            ),
        )

        decision = controller.step(observation(480, 503, 5), timestamp_s=0.0)

        self.assertTrue(decision.stop_requested)
        self.assertIn("projected safety stop", decision.reason)
        self.assertEqual(decision.stop_confirmation_required, 1)

    def test_new_stop_modes_are_disabled_by_default(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(60, 2000, 500),
            settings=FeedbackControllerSettings(allowed_underweight_mg=10),
        )

        first = controller.step(observation(480, 503, 20), timestamp_s=0.0)

        self.assertFalse(first.stop_requested)
        self.assertEqual(first.stop_confirmation_required, 2)

    def test_stall_recovery_temporarily_opens_window_and_restores_on_flow(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=1000,
            initial=FeedbackInitialParameters(80, 2200, 350),
            settings=FeedbackControllerSettings(
                position_feedback_enabled=False,
                stall_recovery_enabled=True,
                stall_recovery_observation_window_s=3.0,
                stall_recovery_min_gain_mg=2.0,
                stall_recovery_rate_threshold_mg_s=1.0,
                stall_recovery_resume_rate_mg_s=2.0,
                stall_recovery_window_step_units=25,
                stall_recovery_max_window_position_units=400,
                stall_recovery_max_attempts=2,
                stall_recovery_disable_remaining_mg=50.0,
            ),
        )

        decisions = [
            controller.step(observation(100, 100, 0), timestamp_s=float(second))
            for second in range(4)
        ]

        self.assertFalse(any(item.window_changed for item in decisions[:3]))
        recovery = decisions[-1]
        self.assertTrue(recovery.window_changed)
        self.assertEqual(recovery.window_after_units, 375)
        self.assertLessEqual(recovery.duty_after_permyriad, 2200)
        self.assertTrue(recovery.stall_recovery_active)
        self.assertEqual(recovery.stall_recovery_attempt, 1)

        resumed = controller.step(observation(103, 103, 3), timestamp_s=3.5)

        self.assertTrue(resumed.window_changed)
        self.assertEqual(resumed.window_after_units, 350)
        self.assertFalse(resumed.stall_recovery_active)
        self.assertIn("flow resumed", resumed.reason)

        second_episode = [
            controller.step(observation(103, 103, 0), timestamp_s=timestamp_s)
            for timestamp_s in (4.5, 5.5, 6.5)
        ]

        self.assertFalse(second_episode[-1].stop_requested)
        self.assertTrue(second_episode[-1].stall_recovery_active)
        self.assertEqual(second_episode[-1].stall_recovery_attempt, 1)
        self.assertEqual(second_episode[-1].window_after_units, 375)

    def test_stall_recovery_uses_two_attempts_then_requests_stop(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=1000,
            initial=FeedbackInitialParameters(80, 2200, 350),
            settings=FeedbackControllerSettings(
                position_feedback_enabled=False,
                stall_recovery_enabled=True,
                stall_recovery_observation_window_s=3.0,
                stall_recovery_min_gain_mg=2.0,
                stall_recovery_rate_threshold_mg_s=1.0,
                stall_recovery_resume_rate_mg_s=2.0,
                stall_recovery_retry_s=3.0,
                stall_recovery_window_step_units=25,
                stall_recovery_max_window_position_units=400,
                stall_recovery_max_attempts=2,
                stall_recovery_disable_remaining_mg=50.0,
            ),
        )

        decisions = [
            controller.step(observation(100, 100, 0), timestamp_s=float(second))
            for second in range(12)
        ]

        self.assertEqual(decisions[3].window_after_units, 375)
        self.assertEqual(decisions[3].stall_recovery_attempt, 1)
        self.assertEqual(decisions[7].window_after_units, 400)
        self.assertEqual(decisions[7].stall_recovery_attempt, 2)
        self.assertTrue(decisions[11].stop_requested)
        self.assertIn("recovery exhausted", decisions[11].reason)

    def test_stall_recovery_never_opens_window_inside_final_50_mg(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=1000,
            initial=FeedbackInitialParameters(80, 2200, 350),
            settings=FeedbackControllerSettings(
                position_feedback_enabled=False,
                stall_recovery_enabled=True,
                stall_recovery_disable_remaining_mg=50.0,
            ),
        )

        decisions = [
            controller.step(observation(951, 951, 0), timestamp_s=float(second))
            for second in range(5)
        ]

        self.assertFalse(any(item.window_changed for item in decisions))
        self.assertFalse(any(item.stall_recovery_active for item in decisions))

    def test_predictive_stop_is_disabled_before_precision_tail(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(60, 2000, 500),
            settings=FeedbackControllerSettings(
                allowed_underweight_mg=10,
                stop_target_offset_mg=5,
                settle_confirmations=1,
            ),
        )
        decision = controller.step(observation(449, 550, 80), timestamp_s=0.0)
        self.assertFalse(decision.stop_requested)

    def test_absolute_30_mg_s_guard_uses_emergency_duty_step(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(60, 2200, 500),
            settings=FeedbackControllerSettings(
                coarse_rate_mg_s=30,
                maximum_flow_rate_mg_s=30,
                emergency_duty_step_per_update=200,
            ),
        )
        decision = controller.step(observation(200, 210, 45), timestamp_s=0.0)
        self.assertEqual(decision.control_rate_mg_s, 45)
        self.assertEqual(decision.duty_after_permyriad, 2050)
        self.assertIn("overspeed", decision.reason)

    def test_position_feedback_can_be_disabled_for_uninterrupted_weighing(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(60, 2000, 500),
            settings=FeedbackControllerSettings(
                position_feedback_enabled=False,
                position_update_interval_s=0.5,
                position_persistence_samples=1,
            ),
        )
        decisions = [
            controller.step(observation(100, 100, 0), timestamp_s=index * 0.5)
            for index in range(6)
        ]
        self.assertTrue(all(not decision.window_changed for decision in decisions))

    def test_tail_taper_reduces_duty_and_window_gradually(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(80, 2000, 300),
            settings=FeedbackControllerSettings(
                fine_rate_mg_s=15,
                tail_taper_enabled=True,
                tail_taper_start_remaining_mg=100,
                tail_taper_end_remaining_mg=10,
                tail_duty_reduction_permyriad=200,
                tail_window_reduction_units=50,
                position_update_interval_s=0.5,
                position_persistence_samples=1,
            ),
        )
        decision = controller.step(observation(460, 460, 15), timestamp_s=0.0)
        self.assertEqual(decision.frequency_hz, 80)
        self.assertLess(decision.duty_after_permyriad, 2000)
        self.assertGreaterEqual(decision.duty_after_permyriad, 1950)
        self.assertLess(decision.window_after_units, 300)
        self.assertGreaterEqual(decision.window_after_units, 275)

    def test_tail_taper_is_inactive_at_coarse_boundary(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=500,
            initial=FeedbackInitialParameters(80, 2000, 300),
            settings=FeedbackControllerSettings(
                fine_rate_mg_s=15,
                tail_taper_enabled=True,
            ),
        )
        decision = controller.step(observation(400, 400, 15), timestamp_s=0.0)
        self.assertEqual(decision.duty_after_permyriad, 2000)
        self.assertEqual(decision.window_after_units, 300)

    def test_invalid_motion_estimate_holds_actuators(self):
        controller = self.seed(500)
        decision = controller.step(observation(100, 100, 0, valid=False), timestamp_s=0.0)
        self.assertFalse(decision.duty_changed)
        self.assertFalse(decision.window_changed)
        self.assertEqual(decision.duty_after_permyriad, 2000)

    def test_light_powder_mass_gain_holds_duty_below_the_rate_target(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=1000,
            initial=FeedbackInitialParameters(80, 2200, 350),
            settings=FeedbackControllerSettings(
                coarse_rate_mg_s=15,
                fine_rate_mg_s=6,
                precision_rate_mg_s=3,
                max_duty_permyriad=3000,
                flow_hold_enabled=True,
                flow_hold_window_s=4,
                flow_hold_min_gain_mg=5,
                flow_response_check_s=4,
            ),
        )
        controller.step(observation(0, 0, 15), timestamp_s=0.0)
        decision = controller.step(observation(5, 5, 5), timestamp_s=1.0)
        self.assertEqual(decision.duty_after_permyriad, 2200)
        self.assertIn("hold duty", decision.reason)

    def test_trace_flow_below_profile_threshold_allows_a_duty_probe(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=1000,
            initial=FeedbackInitialParameters(80, 2200, 350),
            settings=FeedbackControllerSettings(
                coarse_rate_mg_s=15,
                fine_rate_mg_s=6,
                precision_rate_mg_s=3,
                duty_step_per_update=50,
                max_duty_permyriad=3000,
                flow_hold_enabled=True,
                flow_hold_window_s=4,
                flow_hold_min_gain_mg=20,
                flow_response_check_s=4,
            ),
        )

        observing = controller.step(observation(0, 0, 1), timestamp_s=0.0)
        probe = controller.step(observation(5, 5, 1), timestamp_s=4.0)

        self.assertEqual(observing.duty_after_permyriad, 2200)
        self.assertEqual(probe.duty_after_permyriad, 2250)
        self.assertIn("increase duty", probe.reason)

    def test_light_powder_duty_probe_waits_then_reverts_without_improvement(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=1000,
            initial=FeedbackInitialParameters(80, 2200, 350),
            settings=FeedbackControllerSettings(
                coarse_rate_mg_s=15,
                fine_rate_mg_s=6,
                precision_rate_mg_s=3,
                duty_step_per_update=30,
                max_duty_permyriad=3000,
                flow_hold_enabled=True,
                flow_hold_window_s=4,
                flow_hold_min_gain_mg=5,
                flow_response_check_s=4,
                flow_response_min_improvement_mg_s=1,
            ),
        )
        observing = controller.step(observation(0, 0, 5), timestamp_s=0.0)
        raised = controller.step(observation(0, 0, 5), timestamp_s=4.0)
        waiting = controller.step(observation(5, 5, 5), timestamp_s=5.0)
        controller.step(observation(10, 10, 5), timestamp_s=6.0)
        reverted = controller.step(observation(20, 20, 5), timestamp_s=8.1)
        self.assertEqual(observing.duty_after_permyriad, 2200)
        self.assertEqual(raised.duty_after_permyriad, 2230)
        self.assertEqual(waiting.duty_after_permyriad, 2230)
        self.assertEqual(reverted.duty_after_permyriad, 2200)
        self.assertIn("did not improve", reverted.reason)

    def test_light_powder_duty_never_exceeds_its_profile_ceiling(self):
        controller = ContinuousFeedbackController(
            target_mass_mg=1000,
            initial=FeedbackInitialParameters(80, 3000, 350),
            settings=FeedbackControllerSettings(
                coarse_rate_mg_s=15,
                fine_rate_mg_s=6,
                precision_rate_mg_s=3,
                max_duty_permyriad=3000,
                flow_hold_enabled=True,
            ),
        )
        decision = controller.step(observation(0, 0, 0), timestamp_s=0.0)
        self.assertEqual(decision.duty_after_permyriad, 3000)


if __name__ == "__main__":
    unittest.main()
