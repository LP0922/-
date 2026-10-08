"""Preview the next 500 mg continuous-control parameter set.

This helper does not open serial ports or command hardware. It wraps the
existing FourStagePlanner with the current 500 mg calibration profile. The
returned duration is a yield-model reference only; the hardware executor keeps
vibration enabled and changes frequency/duty from live weighing feedback.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from powder_sampling_control.dispensing_algorithm import (  # noqa: E402
    ActuationLimits,
    ActuationPolicy,
    FourStagePlanner,
    L0Profile,
    MassObservation,
    PlannerContext,
    Recipe,
    StageParameters,
)


TARGET_MG = 500.0


def calibration_profile() -> L0Profile:
    """Return the current measured 500 mg candidate profile.

    Coarse is based mainly on the completed 500 mg run:
    1200 / 60 Hz / duty 2000 / 8.594 s -> +362 mg (~42.12 mg/s).

    Only the initial coarse setting is applied directly. Slow/fine frequency
    values are open-loop seeds; the hardware executor keeps duty fixed at 20%
    and replaces those guesses with live 10/7/5 mg/s rate feedback.
    """

    return L0Profile(
        profile_id="stage1-500mg-window1200-dynamic-rate-candidate-v4",
        powder_type="unknown_from_a_data",
        powder_batch="unknown_from_a_data",
        feeder_head="la10_vibration_head",
        recipe_version="stage1-v0",
        target_mass_mg=TARGET_MG,
        # The hardware executor uses this profile only for its ILC/L0 initial
        # frequency and fixed duty. Live mass flow selects 10/7/5 mg/s targets.
        slow_entry_margin_mg=80.0,
        fine_entry_margin_mg=30.0,
        hard_overweight_margin_mg=10.0,
        coarse=StageParameters(
            window_position_units=1200,
            frequency_hz=60,
            duty_permyriad=2000,
            reference_mg_per_s=42.12,
            min_duration_ms=2500,
            max_duration_ms=8_500,
        ),
        slow=StageParameters(
            window_position_units=1200,
            frequency_hz=55,
            duty_permyriad=2000,
            reference_mg_per_s=7.82,
            min_duration_ms=1000,
            max_duration_ms=8_000,
        ),
        fine=StageParameters(
            window_position_units=1200,
            frequency_hz=40,
            duty_permyriad=2000,
            reference_mg_per_s=1.493978,
            min_duration_ms=500,
            max_duration_ms=12_000,
        ),
    )


def planner() -> FourStagePlanner:
    # Current calibration intentionally uses window 1200 and high duty values.
    # Keep these bounds local to this offline helper; production safety limits
    # should still be reviewed before machine release.
    limits = ActuationLimits(
        min_window_position_units=350,
        max_window_position_units=1300,
        min_frequency_hz=10,
        max_frequency_hz=80,
        min_duty_permyriad=1000,
        max_duty_permyriad=5000,
        noise_budget_hz_permyriad=1_000_000,
        min_duration_ms=80,
        max_duration_ms=12_000,
    )
    return FourStagePlanner(policy=ActuationPolicy(limits))


def decide(current_mass_mg: float, predicted_tail_mg: float = 0.0) -> dict:
    if current_mass_mg < 0:
        raise ValueError("current_mass_mg must be non-negative")
    if predicted_tail_mg < 0:
        raise ValueError("predicted_tail_mg must be non-negative")

    recipe = Recipe(
        recipe_id="stage1-500mg-preview",
        target_mass_mg=TARGET_MG,
        allowed_overweight_mg=10.0,
    )
    profile = calibration_profile()
    decision = planner().next_decision(
        PlannerContext(
            recipe=recipe,
            profile=profile,
            observation=MassObservation(current_mass_mg, stable=True, communication_ok=True),
            predicted_tail_mg=predicted_tail_mg,
        )
    )
    action = asdict(decision.action) if decision.action is not None else None
    return {
        "state": decision.stage.value.upper(),
        "decision": "FEED" if action is not None else "STOP",
        "action": action,
        "remaining_predicted_mg": decision.remaining_predicted_mg,
        "expected_mass_mg": decision.expected_mass_mg,
        "reason": decision.reason,
        "algorithm_thresholds": {
            "coarse_when_remaining_gt_mg": profile.slow_entry_margin_mg,
            "slow_when_remaining_gt_mg": profile.fine_entry_margin_mg,
            "fine_when_remaining_lte_mg": profile.fine_entry_margin_mg,
            "settle_when_remaining_lte_mg": 0.0,
            "hard_overweight_boundary_mg": TARGET_MG + min(recipe.allowed_overweight_mg, profile.hard_overweight_margin_mg),
        },
        "profile_id": profile.profile_id,
        "next_instruction": "保持振动使能和20%固定占空比，仅根据实时称重更新频率。" if action else "达到停机判据后关闭振动并等待最终稳定。",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current_mass_mg", type=float, help="latest stable mass in mg")
    parser.add_argument(
        "--predicted-tail-mg",
        type=float,
        default=0.0,
        help="optional predicted falling tail mass in mg",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print machine-readable JSON instead of Chinese text",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = decide(args.current_mass_mg, args.predicted_tail_mg)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"当前稳定重量: {args.current_mass_mg:.1f} mg")
    print(f"状态: {result['state']}")
    print(f"决策: {result['decision']}")
    print(f"原因: {result['reason']}")
    if "remaining_predicted_mg" in result:
        print(f"预测剩余: {result['remaining_predicted_mg']:.1f} mg")
        print(f"本次计划加粉: {result['expected_mass_mg']:.1f} mg")
        thresholds = result["algorithm_thresholds"]
        print("算法判断阈值:")
        print(f"  remaining > {thresholds['coarse_when_remaining_gt_mg']:.1f} mg -> COARSE")
        print(
            f"  {thresholds['fine_when_remaining_lte_mg']:.1f} mg < remaining <= "
            f"{thresholds['coarse_when_remaining_gt_mg']:.1f} mg -> SLOW"
        )
        print(f"  0 < remaining <= {thresholds['fine_when_remaining_lte_mg']:.1f} mg -> FINE")
        print(f"  remaining <= 0 或达到硬超量边界 {thresholds['hard_overweight_boundary_mg']:.1f} mg -> SETTLE")
    if result["action"] is not None:
        action = result["action"]
        print("下一步动作:")
        print(f"  window_position_units = {action['window_position_units']}")
        print(f"  frequency_hz = {action['frequency_hz']}")
        print(f"  duty_permyriad = {action['duty_permyriad']}")
        print(f"  duration_ms = {action['duration_ms']}")
        print(f"  duration_s = {action['duration_ms'] / 1000:.3f}")
    print(f"执行说明: {result['next_instruction']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
