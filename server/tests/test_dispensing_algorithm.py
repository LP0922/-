import sys
import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from powder_sampling_control.dispensing_algorithm import (
    ActuationPolicy,
    ConstrainedILC,
    DispenseStage,
    FeedAction,
    FourStagePlanner,
    ILCSettings,
    L0Repository,
    LearningRecord,
    LocalYieldEstimator,
    MassObservation,
    PlannerContext,
    Recipe,
)


ROOT = Path(__file__).resolve().parents[1]
L0_PATH = ROOT / "config" / "algorithm" / "l0_profiles.example.json"


class DispensingAlgorithmTests(unittest.TestCase):
    def setUp(self):
        self.repository = L0Repository.from_json(L0_PATH)
        self.planner = FourStagePlanner()

    def profile(self, target_mass_mg):
        return self.repository.select(
            powder_type="reference_powder",
            powder_batch="reference_batch",
            feeder_head="la10_vibration_head",
            recipe_version="v1",
            target_mass_mg=target_mass_mg,
        )

    def recipe(self, target_mass_mg):
        return Recipe("reference", target_mass_mg, allowed_overweight_mg=target_mass_mg * 0.05)

    def test_100mg_starts_with_coarse_action(self):
        decision = self.planner.next_decision(
            PlannerContext(self.recipe(100), self.profile(100), MassObservation(0, True, True))
        )
        self.assertEqual(decision.stage, DispenseStage.COARSE)
        self.assertEqual(decision.action.window_position_units, 500)
        self.assertEqual(decision.action.frequency_hz, 30)
        self.assertEqual(decision.action.duty_permyriad, 3000)
        self.assertEqual(decision.action.duration_ms, 3000)

    def test_500mg_uses_its_own_higher_throughput_profile(self):
        decision = self.planner.next_decision(
            PlannerContext(self.recipe(500), self.profile(500), MassObservation(0, True, True))
        )
        self.assertEqual(decision.stage, DispenseStage.COARSE)
        self.assertEqual(decision.action.window_position_units, 550)
        self.assertEqual(decision.action.frequency_hz, 40)
        self.assertEqual(decision.action.duty_permyriad, 2200)
        self.assertEqual(decision.action.duration_ms, 8000)

    def test_fine_stage_uses_low_noise_small_pulse(self):
        profile = self.profile(100)
        decision = self.planner.next_decision(
            PlannerContext(self.recipe(100), profile, MassObservation(97, True, True))
        )
        self.assertEqual(decision.stage, DispenseStage.FINE)
        self.assertLessEqual(decision.action.frequency_hz, 10)
        self.assertLessEqual(decision.action.duty_permyriad, 1200)
        self.assertLessEqual(decision.expected_mass_mg, 1.5)

    def test_frequency_is_coupled_to_noise_limited_duty(self):
        action = ActuationPolicy().bound(FeedAction(500, 60, 3000, 1000))
        self.assertEqual(action.duty_permyriad, 1500)

    def test_interpolates_profile_for_intermediate_target(self):
        profile = self.profile(300)
        self.assertEqual(profile.target_mass_mg, 300)
        self.assertEqual(profile.coarse.window_position_units, 525)
        self.assertEqual(profile.coarse.frequency_hz, 35)

    def test_ilc_rejects_invalid_learning_sample(self):
        ilc = ConstrainedILC(ILCSettings(apply_to_hardware=False))
        recommendation = ilc.recommend(
            LearningRecord(100, 90, 3000, True, False, True, True),
            current_scale=1.0,
        )
        self.assertFalse(recommendation.eligible)
        self.assertEqual(recommendation.proposed_scale, 1.0)

    def test_ilc_limits_valid_update_to_five_percent(self):
        ilc = ConstrainedILC(ILCSettings(learning_gain=0.5, max_relative_step=0.05))
        recommendation = ilc.recommend(
            LearningRecord(100, 50, 3000, True, True, True, True),
            current_scale=1.0,
        )
        self.assertTrue(recommendation.eligible)
        self.assertFalse(recommendation.applied)
        self.assertAlmostEqual(recommendation.proposed_scale, 1.05)

    def test_loads_completed_physical_calibration_record(self):
        record = {
            "result": "completed",
            "stage": "coarse",
            "action": {
                "window_position_units": 500,
                "frequency_hz": 30,
                "duty_permyriad": 3000,
            },
            "actual_duration_s": 1.0,
            "stable_mass_delta_mg": 20,
            "mass_after": {"stable": True},
        }
        with TemporaryDirectory() as directory:
            Path(directory, "sample.json").write_text(json.dumps(record), encoding="utf-8")
            estimator = LocalYieldEstimator.from_directory(directory)
        self.assertEqual(estimator.sample_count, 1)
        self.assertEqual(
            estimator.estimate_mg_per_s(
                stage=DispenseStage.COARSE,
                action=FeedAction(500, 30, 3000, 1000),
                fallback_mg_per_s=1,
            ),
            20,
        )


if __name__ == "__main__":
    unittest.main()
