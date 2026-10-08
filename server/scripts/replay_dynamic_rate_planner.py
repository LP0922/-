"""Replay saved live-rate samples through the local frequency planner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from powder_sampling_control.dispensing_algorithm import (  # noqa: E402
    DynamicRatePlanner,
    MassMotionEstimator,
    RatePlannerSettings,
)


def replay(record: dict, initial_frequency_hz: int = 60) -> list[dict]:
    planner = DynamicRatePlanner(
        RatePlannerSettings(
            severe_update_interval_s=0.25,
            medium_update_interval_s=0.5,
            small_update_interval_s=1.0,
            near_target_update_interval_s=1.5,
        )
    )
    estimator = MassMotionEstimator()
    frequency_hz = initial_frequency_hz
    updates = []
    last_update_s = 0.0
    for sample in record.get("samples", []):
        elapsed_s = float(sample["elapsed_s"])
        motion = estimator.update(elapsed_s, max(0.0, float(sample["mass_mg"])))
        decision = planner.decide(
            filtered_mass_mg=motion.filtered_mass_mg,
            measured_rate_mg_s=motion.rate_mg_s,
            current_frequency_hz=frequency_hz,
            acceleration_mg_s2=motion.acceleration_mg_s2,
            jerk_mg_s3=motion.jerk_mg_s3,
            predicted_mass_mg=motion.predicted_mass_mg,
            predicted_rate_mg_s=motion.predicted_rate_mg_s,
            seconds_since_frequency_change=elapsed_s - last_update_s,
            rate_valid=motion.valid,
        )
        stage_changed = updates and decision.stage.value != updates[-1]["stage"]
        adjustment_due = (
            stage_changed
            or elapsed_s - last_update_s >= decision.next_update_interval_s
        )
        if adjustment_due and decision.frequency_changed:
            updates.append(
                {
                    "elapsed_s": elapsed_s,
                    "mass_mg": round(motion.filtered_mass_mg, 3),
                    "predicted_mass_mg": round(motion.predicted_mass_mg, 3),
                    "stage": decision.stage.value,
                    "measured_rate_mg_s": round(decision.measured_rate_mg_s, 3),
                    "predicted_rate_mg_s": round(decision.predicted_rate_mg_s, 3),
                    "acceleration_mg_s2": round(decision.acceleration_mg_s2, 3),
                    "jerk_mg_s3": round(decision.jerk_mg_s3, 3),
                    "target_rate_mg_s": decision.target_rate_mg_s,
                    "frequency_before_hz": frequency_hz,
                    "frequency_after_hz": decision.next_frequency_hz,
                    "reason": decision.reason,
                }
            )
            frequency_hz = decision.next_frequency_hz
            last_update_s = elapsed_s
    return updates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path, help="saved continuous-run JSON")
    parser.add_argument("--initial-frequency-hz", type=int, default=60)
    args = parser.parse_args()
    record = json.loads(args.record.read_text(encoding="utf-8"))
    print(json.dumps(replay(record, args.initial_frequency_hz), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
