"""Calibrate and validate AT8811C raw counts with certified reference masses.

The default mode is preview-only.  ``--execute`` opens the balance serial port,
prompts the operator to place each reference mass, captures stable raw counts,
fits ``mass_mg = raw_count * scale + offset``, and writes a validated JSON file.
Do not run this script while the dashboard or another process owns the port.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import mean

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from powder_sampling_control.device_adapters import (
    AT8811CConfig,
    AT8811CModbusRTU,
    BalanceCalibrationPoint,
    fit_balance_calibration,
)


DEFAULT_OUTPUT = PROJECT_ROOT / "config" / "devices" / "at8811c-calibration.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="open the serial port and capture physical points")
    parser.add_argument("--port", default="COM9")
    parser.add_argument("--address", type=int, default=1)
    parser.add_argument("--device-id", default="balance_01")
    parser.add_argument(
        "--reference-mg",
        action="append",
        type=float,
        dest="reference_masses",
        help="certified reference mass in mg; repeat for every point (default: 0, 100, 500)",
    )
    parser.add_argument("--samples-per-point", type=int, default=5)
    parser.add_argument("--sample-interval-s", type=float, default=0.2)
    parser.add_argument("--stable-timeout-s", type=float, default=20.0)
    parser.add_argument("--maximum-spread-counts", type=float, default=2.0)
    parser.add_argument("--maximum-residual-mg", type=float, default=2.0)
    parser.add_argument("--minimum-r-squared", type=float, default=0.999)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.reference_masses = sorted(args.reference_masses or [0.0, 100.0, 500.0])
    if len(args.reference_masses) < 3 or 0.0 not in args.reference_masses:
        parser.error("provide at least zero plus two positive reference masses")
    if len(set(args.reference_masses)) != len(args.reference_masses):
        parser.error("reference masses must be unique")
    if args.samples_per_point < 3:
        parser.error("--samples-per-point must be at least 3")
    if min(args.sample_interval_s, args.stable_timeout_s, args.maximum_spread_counts) <= 0:
        parser.error("sampling intervals, timeout, and maximum spread must be positive")
    return args


def capture_stable_counts(
    balance: AT8811CModbusRTU,
    *,
    sample_count: int,
    sample_interval_s: float,
    timeout_s: float,
) -> list[int]:
    deadline = time.monotonic() + timeout_s
    captured: list[int] = []
    while time.monotonic() < deadline and len(captured) < sample_count:
        measurement = balance.read_measurement()
        if measurement.stable:
            captured.append(measurement.raw_count)
        else:
            captured.clear()
        if len(captured) < sample_count:
            time.sleep(sample_interval_s)
    if len(captured) < sample_count:
        raise TimeoutError(
            f"balance did not provide {sample_count} consecutive stable samples within {timeout_s:.1f} s"
        )
    return captured


def execute(args: argparse.Namespace) -> dict:
    balance = AT8811CModbusRTU(
        AT8811CConfig(
            port=args.port,
            slave_address=args.address,
            timeout_s=0.5,
            retries=1,
        )
    )
    points: list[BalanceCalibrationPoint] = []
    try:
        balance.connect()
        for index, reference_mg in enumerate(args.reference_masses):
            if reference_mg == 0:
                input("移除秤盘上的全部砝码，等待稳定后按 Enter 标零并采样：")
                balance.zero(authorized=True)
                time.sleep(1.0)
            else:
                input(f"放置 {reference_mg:g} mg 标准砝码，等待稳定后按 Enter 采样：")
            counts = capture_stable_counts(
                balance,
                sample_count=args.samples_per_point,
                sample_interval_s=args.sample_interval_s,
                timeout_s=args.stable_timeout_s,
            )
            spread = float(max(counts) - min(counts))
            if spread > args.maximum_spread_counts:
                raise RuntimeError(
                    f"{reference_mg:g} mg point spread {spread:g} counts exceeds "
                    f"limit {args.maximum_spread_counts:g}; check stability and repeat"
                )
            point = BalanceCalibrationPoint(
                reference_mg=reference_mg,
                raw_count=mean(counts),
                sample_count=len(counts),
                raw_count_spread=spread,
            )
            points.append(point)
            print(
                f"captured {reference_mg:g} mg: mean={point.raw_count:.3f} counts, "
                f"spread={point.raw_count_spread:.3f}"
            )
    finally:
        balance.close()

    calibration = fit_balance_calibration(
        points,
        device_id=args.device_id,
        maximum_allowed_residual_mg=args.maximum_residual_mg,
        minimum_r_squared=args.minimum_r_squared,
    )
    document = calibration.to_dict()
    if not calibration.valid:
        print(json.dumps(document, ensure_ascii=False, indent=2))
        raise RuntimeError(
            "calibration failed residual/R-squared validation; no runtime file was written"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**document, "output_path": str(args.output)}


def preview(args: argparse.Namespace) -> dict:
    return {
        "mode": "preview",
        "hardware_touched": False,
        "port": args.port,
        "reference_masses_mg": args.reference_masses,
        "samples_per_point": args.samples_per_point,
        "validation": {
            "maximum_spread_counts": args.maximum_spread_counts,
            "maximum_residual_mg": args.maximum_residual_mg,
            "minimum_r_squared": args.minimum_r_squared,
        },
        "output_path": str(args.output),
        "next_step": "rerun with --execute while no dashboard process owns the AT8811C port",
    }


def main() -> int:
    args = parse_args()
    result = execute(args) if args.execute else preview(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
