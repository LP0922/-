"""Preview the production continuous-taper planner without using hardware."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from powder_sampling_control.dispensing_algorithm import (
    ContinuousTaperConfig,
    ContinuousTaperPlanner,
)


def decide(args):
    config = ContinuousTaperConfig(target_mass_mg=args.target_mg)
    decision = ContinuousTaperPlanner(config).decide(
        raw_mass_mg=args.raw_mass_mg,
        filtered_mass_mg=args.filtered_mass_mg,
        rate_mg_s=args.rate_mg_s,
        acceleration_mg_s2=args.acceleration_mg_s2,
        predicted_mass_mg=args.predicted_mass_mg,
        current_window_position_units=args.current_window,
        current_frequency_hz=args.current_frequency,
        current_duty_permyriad=args.current_duty,
    )
    return {
        "stage": decision.stage.value.upper(),
        "command": decision.command,
        "action": asdict(decision.action) if decision.action else None,
        "raw_mass_mg": decision.raw_mass_mg,
        "filtered_mass_mg": round(decision.filtered_mass_mg, 3),
        "predicted_mass_mg": round(decision.predicted_mass_mg, 3),
        "remaining_predicted_mg": round(decision.remaining_predicted_mg, 3),
        "reason": decision.reason,
        "rules": {
            "coarse": "mass < 420 mg -> 80 Hz / window 200 / duty 2000",
            "tail": "420 mg+ -> 65 Hz / window 100 / duty 1600, then hold continuously",
            "stop": "raw >= 498, or raw >= 485 and predicted >= 500, or filtered >= 495",
        },
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_mass_mg", type=float, help="latest balance mass in mg")
    parser.add_argument("--target-mg", type=float, default=500.0)
    parser.add_argument("--filtered-mass-mg", type=float, default=None)
    parser.add_argument("--rate-mg-s", type=float, default=0.0)
    parser.add_argument("--acceleration-mg-s2", type=float, default=0.0)
    parser.add_argument("--predicted-mass-mg", type=float, default=None)
    parser.add_argument("--current-window", type=int, default=None)
    parser.add_argument("--current-frequency", type=int, default=None)
    parser.add_argument("--current-duty", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    result = decide(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"stage: {result['stage']}")
    print(f"command: {result['command']}")
    print(f"raw_mass = {result['raw_mass_mg']:.1f} mg")
    print(f"filtered_mass = {result['filtered_mass_mg']:.1f} mg")
    print(f"predicted_mass = {result['predicted_mass_mg']:.1f} mg")
    print(f"predicted_remaining = {result['remaining_predicted_mg']:.1f} mg")
    print(f"reason: {result['reason']}")
    if result["action"] is not None:
        action = result["action"]
        print("continuous action:")
        print(f"  window_position_units = {action['window_position_units']}")
        print(f"  frequency_hz = {action['frequency_hz']}")
        print(f"  duty_permyriad = {action['duty_permyriad']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
