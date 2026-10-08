"""Collect one tare-to-stable mass-yield calibration sample for the LA10 feeder.

Run without --execute to preview the request. The execute mode owns COM9 and
COM8 for the duration of the run; do not run the dashboard at the same time.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from powder_sampling_control.device_adapters import (
    AT8811CConfig,
    AT8811CModbusRTU,
    LA10Config,
    LA10ModbusRTU,
    load_balance_calibration,
)


POSITION_UNITS_PER_MM = 200
MOTION_UNITS_PER_MM = 100
POSITION_TOLERANCE_UNITS = 100


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="allow physical tare, movement, and vibration")
    parser.add_argument("--at-port", default="COM9")
    parser.add_argument(
        "--balance-calibration",
        type=Path,
        default=PROJECT_ROOT / "config" / "devices" / "at8811c-calibration.json",
        help="validated AT8811C count-to-mg calibration JSON",
    )
    parser.add_argument("--la10-port", default="COM8")
    parser.add_argument("--window-position-units", type=int, default=500)
    parser.add_argument("--frequency-hz", type=int, default=10)
    parser.add_argument("--duty-permyriad", type=int, default=1000)
    parser.add_argument("--duration-s", type=float, default=1.0)
    parser.add_argument("--settle-timeout-s", type=float, default=10.0)
    parser.add_argument("--window-timeout-s", type=float, default=20.0)
    parser.add_argument("--tag", default="unclassified")
    parser.add_argument("--stage", choices=("coarse", "slow", "fine"), default="coarse")
    return parser.parse_args()


def measurement_record(measurement):
    record = asdict(measurement)
    record["captured_at"] = measurement.captured_at.isoformat()
    return record


def wait_for_stable(balance: AT8811CModbusRTU, timeout_s: float):
    deadline = time.monotonic() + timeout_s
    latest = None
    while time.monotonic() < deadline:
        latest = balance.read_measurement()
        if latest.stable:
            return latest
        time.sleep(0.25)
    raise TimeoutError(f"balance did not become stable within {timeout_s:.1f} s; last={latest}")


def move_window(la10: LA10ModbusRTU, target_units: int, timeout_s: float):
    before = la10.read_status()
    if before.fault_bits:
        raise RuntimeError(f"LA10 fault bits: 0x{before.fault_bits:04X}")
    if before.is_running:
        raise RuntimeError("LA10 window is already moving")
    position_error = abs(target_units - before.position_units)
    distance_register = round(
        position_error / POSITION_UNITS_PER_MM * MOTION_UNITS_PER_MM
    )
    # The feeder may begin dispensing once the physical window is within the
    # approved position tolerance; avoid a tiny, unnecessary corrective move.
    if position_error > POSITION_TOLERANCE_UNITS:
        la10.enable()
        la10.move_relative(
            extend=target_units > before.position_units,
            distance_mm=distance_register / MOTION_UNITS_PER_MM,
            speed_mm_s=1.0,
        )
        after = la10.wait_until_stopped(timeout_s=timeout_s, require_running_transition=True)
    else:
        distance_register = 0
        after = before
    if abs(after.position_units - target_units) > POSITION_TOLERANCE_UNITS:
        raise RuntimeError(
            f"window out of tolerance: actual={after.position_units}, target={target_units}, "
            f"tolerance={POSITION_TOLERANCE_UNITS}"
        )
    return before, after, distance_register


def preview(args):
    return {
        "mode": "preview",
        "warning": "No hardware was touched. Add --execute to collect a physical sample.",
        "action": {
            "window_position_units": args.window_position_units,
            "frequency_hz": args.frequency_hz,
            "duty_permyriad": args.duty_permyriad,
            "duration_s": args.duration_s,
        },
    }


def execute(args):
    if not 0 <= args.window_position_units <= 2000:
        raise ValueError("window_position_units must be in 0..2000")
    if not 10 <= args.frequency_hz <= 80:
        raise ValueError("frequency_hz must be in 10..80")
    if not 1000 <= args.duty_permyriad <= 5000:
        raise ValueError("duty_permyriad must be in 1000..5000")
    if not 0 < args.duration_s <= 10:
        raise ValueError("duration_s must be in (0, 10]")

    calibration = load_balance_calibration(args.balance_calibration)
    balance = AT8811CModbusRTU(
        AT8811CConfig(
            port=args.at_port,
            scale_mg_per_count=calibration.scale_mg_per_count,
            offset_mg=calibration.offset_mg,
            timeout_s=1.0,
            retries=1,
        )
    )
    la10 = LA10ModbusRTU(LA10Config(port=args.la10_port, timeout_s=1.0, retries=1))
    vibration_started = False
    failure = None
    result = {
        "run_id": f"calibration-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "tag": args.tag,
        "stage": args.stage,
        "balance_calibration_id": calibration.calibration_id,
        "action": {
            "window_position_units": args.window_position_units,
            "frequency_hz": args.frequency_hz,
            "duty_permyriad": args.duty_permyriad,
            "duration_s": args.duration_s,
        },
    }
    try:
        vibration = la10.read_vibration_settings()
        if vibration.enabled:
            la10.stop_vibration()
            raise RuntimeError("vibration was enabled and has been stopped; inspect before retrying")
        balance.zero(authorized=True)
        result["tare_after"] = measurement_record(wait_for_stable(balance, args.settle_timeout_s))
        window_before, window_after, distance_register = move_window(
            la10, args.window_position_units, args.window_timeout_s
        )
        # Addresses 9 and 11 are part of the movement acceptance record.
        # move_relative() writes addresses 1-4 in one Modbus function 0x10 request.
        result["window_before"] = asdict(window_before)
        result["window_after"] = asdict(window_after)
        result["window_distance_register"] = distance_register
        result["window_motion_write_function"] = "0x10"
        result["pre_motion_fault_bits"] = window_before.fault_bits
        result["post_motion_fault_bits"] = window_after.fault_bits
        result["post_motion_last_result"] = window_after.last_result
        result["mass_before"] = measurement_record(wait_for_stable(balance, args.settle_timeout_s))

        la10.start_vibration(
            frequency_hz=args.frequency_hz,
            duty_permyriad=args.duty_permyriad,
        )
        vibration_started = True
        started = time.monotonic()
        time.sleep(args.duration_s)
        la10.stop_vibration()
        vibration_started = False
        result["actual_duration_s"] = round(time.monotonic() - started, 3)
        result["mass_after"] = measurement_record(wait_for_stable(balance, args.settle_timeout_s))
        result["stable_mass_delta_mg"] = result["mass_after"]["raw_count"] - result["mass_before"]["raw_count"]
        result["estimated_mg_per_s"] = round(result["stable_mass_delta_mg"] / result["actual_duration_s"], 6)
        result["result"] = "completed"
    except Exception as error:
        result["result"] = "failed"
        result["error"] = str(error)
        failure = error
    finally:
        if vibration_started:
            try:
                la10.stop_vibration()
            except Exception as error:
                result["stop_error"] = str(error)
        try:
            after = la10.read_vibration_settings()
            result["vibration_after"] = asdict(after)
        except Exception as error:
            result["vibration_readback_error"] = str(error)
        result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        balance.close()
        la10.close()

    output_dir = PROJECT_ROOT / "data" / "calibration"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{result['run_id']}.json"
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_path"] = str(output_path)
    except OSError as error:
        # Never hide a physical calibration result because its log directory is unavailable.
        result["output_error"] = str(error)
    if failure is not None:
        raise failure
    return result


def main():
    args = parse_args()
    result = execute(args) if args.execute else preview(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
