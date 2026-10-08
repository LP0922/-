"""Plan a window-position feed action with feedforward plus PID trim."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from powder_sampling_control.dispensing_algorithm.window_pid_planner import (  # noqa: E402
    WindowPidConfig,
    WindowPidPlanner,
    WindowPidState,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current_mass_mg", type=float, help="latest cumulative mass in mg")
    parser.add_argument("--target-mg", type=float, default=500.0, help="target cumulative mass in mg")
    parser.add_argument("--rate-mg-s", type=float, default=None, help="recent flow rate in mg/s")
    parser.add_argument("--dt-s", type=float, default=1.0, help="time span used by the rate estimate")
    parser.add_argument("--integral-error", type=float, default=0.0, help="PID integral state from previous output")
    parser.add_argument("--previous-error-mg-s", type=float, default=0.0, help="PID previous error from previous output")
    parser.add_argument("--no-flow-seconds", type=float, default=0.0, help="no-flow state from previous output")
    parser.add_argument("--json", action="store_true", help="print JSON")
    return parser.parse_args()


def action_to_dict(action):
    if action is None:
        return None
    return asdict(action)


def main() -> int:
    args = parse_args()
    config = replace(WindowPidConfig(), target_mass_mg=args.target_mg)
    planner = WindowPidPlanner(config)
    state = WindowPidState(
        integral_error=args.integral_error,
        previous_error_mg_s=args.previous_error_mg_s,
        no_flow_seconds=args.no_flow_seconds,
    )
    decision = planner.next_decision(
        current_mass_mg=args.current_mass_mg,
        observed_rate_mg_s=args.rate_mg_s,
        state=state,
        dt_s=args.dt_s,
    )
    output = {
        "stage": decision.stage.value.upper(),
        "decision": "FEED" if decision.action is not None else "STOP",
        "action": action_to_dict(decision.action),
        "current_mass_mg": args.current_mass_mg,
        "target_mass_mg": args.target_mg,
        "remaining_mg": round(decision.remaining_mg, 3),
        "predicted_tail_mg": round(decision.predicted_tail_mg, 3),
        "target_rate_mg_s": round(decision.target_rate_mg_s, 3),
        "observed_rate_mg_s": decision.observed_rate_mg_s,
        "expected_mass_mg": round(decision.expected_mass_mg, 3),
        "stop_mass_mg": round(decision.stop_mass_mg, 3),
        "pid_adjust_units": decision.pid_adjust_units,
        "next_state": asdict(decision.next_state),
        "reason": decision.reason,
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    print(f"当前重量: {args.current_mass_mg:.1f} mg")
    print(f"目标重量: {args.target_mg:.1f} mg")
    if args.rate_mg_s is not None:
        print(f"最近速度: {args.rate_mg_s:.2f} mg/s")
        print(f"预测尾粉: {decision.predicted_tail_mg:.2f} mg")
    print(f"状态: {output['stage']}")
    print(f"决策: {output['decision']}")
    print(f"预测剩余: {decision.remaining_mg:.2f} mg")
    print(f"目标速度: {decision.target_rate_mg_s:.2f} mg/s")
    print(f"本次计划加粉: {decision.expected_mass_mg:.2f} mg")
    print(f"本次动作停止重量: {decision.stop_mass_mg:.2f} mg")
    print(f"PID window 修正: {decision.pid_adjust_units:+d} units")
    print(f"原因: {decision.reason}")
    if decision.action is not None:
        action = decision.action
        print("下一步动作:")
        print(f"  window_position_units = {action.window_position_units}")
        print(f"  frequency_hz = {action.frequency_hz}")
        print(f"  duty_permyriad = {action.duty_permyriad}")
        print(f"  duration_ms = {action.duration_ms}")
        print(f"  duration_s = {action.duration_ms / 1000:.3f}")
    print("下一轮 PID 状态:")
    print(f"  --integral-error {decision.next_state.integral_error:.3f}")
    print(f"  --previous-error-mg-s {decision.next_state.previous_error_mg_s:.3f}")
    print(f"  --no-flow-seconds {decision.next_state.no_flow_seconds:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

