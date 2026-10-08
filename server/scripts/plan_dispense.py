"""Preview a four-stage LA10 dispensing decision without accessing hardware."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from powder_sampling_control.dispensing_algorithm import (
    FourStagePlanner,
    L0Repository,
    LocalYieldEstimator,
    MassObservation,
    PlannerContext,
    Recipe,
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-mg", type=float, required=True)
    parser.add_argument("--observed-mg", type=float, default=0.0)
    parser.add_argument("--predicted-tail-mg", type=float, default=0.0)
    parser.add_argument("--allowed-overweight-mg", type=float, default=5.0)
    parser.add_argument("--powder-type", default="reference_powder")
    parser.add_argument("--powder-batch", default="reference_batch")
    parser.add_argument("--feeder-head", default="la10_vibration_head")
    parser.add_argument("--recipe-version", default="v1")
    parser.add_argument(
        "--l0-path",
        type=Path,
        default=PROJECT_ROOT / "config" / "algorithm" / "l0_profiles.example.json",
    )
    parser.add_argument(
        "--calibration-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "calibration",
        help="completed physical calibration JSON directory",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    repository = L0Repository.from_json(args.l0_path)
    profile = repository.select(
        powder_type=args.powder_type,
        powder_batch=args.powder_batch,
        feeder_head=args.feeder_head,
        recipe_version=args.recipe_version,
        target_mass_mg=args.target_mg,
    )
    recipe = Recipe("preview", args.target_mg, args.allowed_overweight_mg)
    estimator = LocalYieldEstimator.from_directory(args.calibration_dir)
    decision = FourStagePlanner(yield_estimator=estimator).next_decision(
        PlannerContext(
            recipe=recipe,
            profile=profile,
            observation=MassObservation(args.observed_mg, stable=True, communication_ok=True),
            predicted_tail_mg=args.predicted_tail_mg,
        )
    )
    payload = {
        "profile_id": profile.profile_id,
        "calibration_sample_count": estimator.sample_count,
        "decision": asdict(decision),
    }
    payload["decision"]["stage"] = decision.stage.value
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
