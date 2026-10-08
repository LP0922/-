"""Preview the generic mass-feedback strategy without opening serial ports."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from powder_sampling_control.dispensing_algorithm import (  # noqa: E402
    ContinuousFeedbackController,
    FeedbackControllerSettings,
    FeedbackInitialParameters,
    FeedbackObservation,
)
from powder_sampling_control.dispensing_algorithm.feedback_profiles import (  # noqa: E402
    DISPENSE_ALLOWED_OVERWEIGHT_MG,
    DISPENSE_ALLOWED_UNDERWEIGHT_MG,
    DISPENSE_TARGET_PROFILES,
    dispense_plan,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target_mg", type=int, choices=tuple(DISPENSE_TARGET_PROFILES))
    parser.add_argument("current_mass_mg", type=float)
    parser.add_argument("--predicted-mass-mg", type=float, default=None)
    parser.add_argument("--rate-mg-s", type=float, default=0.0)
    parser.add_argument("--predicted-rate-mg-s", type=float, default=None)
    parser.add_argument("--frequency-hz", type=int, required=True)
    parser.add_argument("--duty-permyriad", type=int, required=True)
    parser.add_argument("--window-position-units", type=int, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    predicted_mass = args.current_mass_mg if args.predicted_mass_mg is None else args.predicted_mass_mg
    predicted_rate = args.rate_mg_s if args.predicted_rate_mg_s is None else args.predicted_rate_mg_s
    target_mg, profile = dispense_plan(args.target_mg)
    settings = FeedbackControllerSettings(
        coarse_rate_mg_s=profile["coarse_rate_mg_s"],
        fine_rate_mg_s=profile["fine_rate_mg_s"],
        precision_rate_mg_s=profile["precision_rate_mg_s"],
        maximum_flow_rate_mg_s=profile["maximum_flow_rate_mg_s"],
        min_window_position_units=100,
        max_window_position_units=750,
        allowed_underweight_mg=DISPENSE_ALLOWED_UNDERWEIGHT_MG,
        allowed_overweight_mg=DISPENSE_ALLOWED_OVERWEIGHT_MG,
        precision_start_remaining_mg=profile["precision_start_remaining_mg"],
        stop_prediction_horizon_s=1.0,
        fixed_tail_mass_mg=2.0,
        stop_target_offset_mg=5.0,
        position_feedback_enabled=False,
        tail_taper_enabled=True,
        tail_taper_start_remaining_mg=profile["tail_taper_start_remaining_mg"],
        tail_taper_end_remaining_mg=profile["tail_taper_end_remaining_mg"],
        tail_duty_reduction_permyriad=200,
        tail_window_reduction_units=50,
    )
    controller = ContinuousFeedbackController(
        target_mass_mg=target_mg,
        initial=FeedbackInitialParameters(
            frequency_hz=args.frequency_hz,
            duty_permyriad=args.duty_permyriad,
            window_position_units=args.window_position_units,
        ),
        settings=settings,
    )
    decision = controller.step(
        FeedbackObservation(
            mass_mg=args.current_mass_mg,
            predicted_mass_mg=predicted_mass,
            rate_mg_s=args.rate_mg_s,
            predicted_rate_mg_s=predicted_rate,
        ),
        timestamp_s=0.0,
    )
    result = asdict(decision)
    result["stage"] = decision.stage.value
    result["target_mg"] = target_mg
    result["coarse_fraction"] = controller.coarse_fraction()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"target={target_mg:.0f} mg, coarse={controller.coarse_threshold_mg():.1f} mg")
        print(f"stage={decision.stage.value}, rate error={decision.rate_error_mg_s:.2f} mg/s")
        print(
            f"frequency={decision.frequency_hz} Hz (locked), "
            f"duty={decision.duty_before_permyriad}->{decision.duty_after_permyriad}, "
            f"window={decision.window_before_units}->{decision.window_after_units}"
        )
        print(f"reason: {decision.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
