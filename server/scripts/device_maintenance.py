"""Hardware calibration, diagnostics, and backend test CLI for the LA10 + AT8811C rig.

Consolidates the former standalone scripts into one entry point:

    python device_maintenance.py calibrate-scale   ...  (was calibrate_at8811c_scale.py)
    python device_maintenance.py calibrate-yield   ...  (was calibrate_feed_yield.py)
    python device_maintenance.py monitor-drift     ...  (was monitor_at8811c_drift.py)
    python device_maintenance.py diagnose-empty    ...  (was diagnose_la10_empty_motion.py)
    python device_maintenance.py scan-startup      ...  (was scan_low_rate_startup.py)
    python device_maintenance.py vibration-test    ...  (was test_vibration_feed.py)
    python device_maintenance.py window-sweep      ...  (was test_window_position_sweep.py)
    python device_maintenance.py save-result       ...  (was save_latest_test_result.py)

Serial-port rules are unchanged: close the dashboard/service before any
subcommand that opens COM8/COM9 directly (calibrate-scale, calibrate-yield,
monitor-drift, diagnose-empty). vibration-test / window-sweep / scan-startup /
save-result talk to the device backend over HTTP instead.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from powder_sampling_control.device_adapters import (  # noqa: E402
    AT8811CConfig,
    AT8811CModbusRTU,
    BalanceCalibrationPoint,
    LA10Config,
    LA10ModbusRTU,
    fit_balance_calibration,
    load_balance_calibration,
)
from powder_sampling_control.device_adapters.la10_modbus_rtu import (  # noqa: E402
    LA10Config as _LA10ConfigDirect,
    LA10ModbusRTU as _LA10ModbusRTUDirect,
)

DEFAULT_BACKEND_URL = "http://127.0.0.1:8765"


def _request_json(url: str, method: str = "GET", payload: dict | None = None, timeout: float = 5) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, method=method, headers={"Content-Type": "application/json"} if payload is not None else {})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


# ── calibrate-scale (was calibrate_at8811c_scale.py) ─────────────────────────

CAL_SCALE_DEFAULT_OUTPUT = PROJECT_ROOT / "config" / "devices" / "at8811c-calibration.json"


def _capture_stable_counts(
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


def cmd_calibrate_scale(args: argparse.Namespace) -> int:
    if args.reference_masses is not None:
        args.reference_masses = sorted(args.reference_masses)
    else:
        args.reference_masses = [0.0, 100.0, 500.0]
    if len(args.reference_masses) < 3 or 0.0 not in args.reference_masses:
        raise SystemExit("provide at least zero plus two positive reference masses")
    if len(set(args.reference_masses)) != len(args.reference_masses):
        raise SystemExit("reference masses must be unique")
    if args.samples_per_point < 3:
        raise SystemExit("--samples-per-point must be at least 3")
    if min(args.sample_interval_s, args.stable_timeout_s, args.maximum_spread_counts) <= 0:
        raise SystemExit("sampling intervals, timeout, and maximum spread must be positive")

    if not args.execute:
        result = {
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
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

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
        for reference_mg in args.reference_masses:
            if reference_mg == 0:
                input("移除秤盘上的全部砝码，等待稳定后按 Enter 标零并采样：")
                balance.zero(authorized=True)
                time.sleep(1.0)
            else:
                input(f"放置 {reference_mg:g} mg 标准砝码，等待稳定后按 Enter 采样：")
            counts = _capture_stable_counts(
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
    print(json.dumps({**document, "output_path": str(args.output)}, ensure_ascii=False, indent=2))
    return 0


def add_calibrate_scale_parser(sub) -> None:
    p = sub.add_parser(
        "calibrate-scale",
        help="calibrate and validate AT8811C raw counts with certified reference masses",
    )
    p.add_argument("--execute", action="store_true", help="open the serial port and capture physical points")
    p.add_argument("--port", default="COM9")
    p.add_argument("--address", type=int, default=1)
    p.add_argument("--device-id", default="balance_01")
    p.add_argument(
        "--reference-mg",
        action="append",
        type=float,
        dest="reference_masses",
        help="certified reference mass in mg; repeat for every point (default: 0, 100, 500)",
    )
    p.add_argument("--samples-per-point", type=int, default=5)
    p.add_argument("--sample-interval-s", type=float, default=0.2)
    p.add_argument("--stable-timeout-s", type=float, default=20.0)
    p.add_argument("--maximum-spread-counts", type=float, default=2.0)
    p.add_argument("--maximum-residual-mg", type=float, default=2.0)
    p.add_argument("--minimum-r-squared", type=float, default=0.999)
    p.add_argument("--output", type=Path, default=CAL_SCALE_DEFAULT_OUTPUT)
    p.set_defaults(func=cmd_calibrate_scale)


# ── calibrate-yield (was calibrate_feed_yield.py) ────────────────────────────

POSITION_UNITS_PER_MM = 200
MOTION_UNITS_PER_MM = 100
POSITION_TOLERANCE_UNITS = 100


def _measurement_record(measurement):
    record = asdict(measurement)
    record["captured_at"] = measurement.captured_at.isoformat()
    return record


def _wait_for_stable(balance: AT8811CModbusRTU, timeout_s: float):
    deadline = time.monotonic() + timeout_s
    latest = None
    while time.monotonic() < deadline:
        latest = balance.read_measurement()
        if latest.stable:
            return latest
        time.sleep(0.25)
    raise TimeoutError(f"balance did not become stable within {timeout_s:.1f} s; last={latest}")


def _move_window(la10: LA10ModbusRTU, target_units: int, timeout_s: float):
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


def cmd_calibrate_yield(args: argparse.Namespace) -> int:
    if not args.execute:
        result = {
            "mode": "preview",
            "warning": "No hardware was touched. Add --execute to collect a physical sample.",
            "action": {
                "window_position_units": args.window_position_units,
                "frequency_hz": args.frequency_hz,
                "duty_permyriad": args.duty_permyriad,
                "duration_s": args.duration_s,
            },
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

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
        result["tare_after"] = _measurement_record(_wait_for_stable(balance, args.settle_timeout_s))
        window_before, window_after, distance_register = _move_window(
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
        result["mass_before"] = _measurement_record(_wait_for_stable(balance, args.settle_timeout_s))

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
        result["mass_after"] = _measurement_record(_wait_for_stable(balance, args.settle_timeout_s))
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
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def add_calibrate_yield_parser(sub) -> None:
    p = sub.add_parser(
        "calibrate-yield",
        help="collect one tare-to-stable mass-yield calibration sample for the LA10 feeder",
    )
    p.add_argument("--execute", action="store_true", help="allow physical tare, movement, and vibration")
    p.add_argument("--at-port", default="COM9")
    p.add_argument(
        "--balance-calibration",
        type=Path,
        default=PROJECT_ROOT / "config" / "devices" / "at8811c-calibration.json",
        help="validated AT8811C count-to-mg calibration JSON",
    )
    p.add_argument("--la10-port", default="COM8")
    p.add_argument("--window-position-units", type=int, default=500)
    p.add_argument("--frequency-hz", type=int, default=10)
    p.add_argument("--duty-permyriad", type=int, default=1000)
    p.add_argument("--duration-s", type=float, default=1.0)
    p.add_argument("--settle-timeout-s", type=float, default=10.0)
    p.add_argument("--window-timeout-s", type=float, default=20.0)
    p.add_argument("--tag", default="unclassified")
    p.add_argument("--stage", choices=("coarse", "slow", "fine"), default="coarse")
    p.set_defaults(func=cmd_calibrate_yield)


# ── monitor-drift (was monitor_at8811c_drift.py) ─────────────────────────────


def _linear_slope(samples: list[tuple[float, int]]) -> float:
    """Return least-squares raw-count drift in counts per second."""
    if len(samples) < 2:
        return 0.0
    mean_x = mean(item[0] for item in samples)
    mean_y = mean(item[1] for item in samples)
    denominator = sum((x - mean_x) ** 2 for x, _ in samples)
    if denominator == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in samples) / denominator


def cmd_monitor_drift(args: argparse.Namespace) -> int:
    if args.duration_s <= 0 or args.interval_s <= 0:
        raise SystemExit("duration and interval must be positive")
    vibration_values = (args.vibration_frequency_hz, args.vibration_duty_permyriad)
    vibration_enabled = args.vibration_frequency_hz is not None
    if any(value is not None for value in vibration_values):
        if not args.la10_port or any(value is None for value in vibration_values):
            raise SystemExit(
                "vibration requires --la10-port, --vibration-frequency-hz, and --vibration-duty-permyriad"
            )
        if not 10 <= args.vibration_frequency_hz <= 80:
            raise SystemExit("--vibration-frequency-hz must be in the range 10..80")
        if not 1000 <= args.vibration_duty_permyriad <= 5000:
            raise SystemExit("--vibration-duty-permyriad must be in the range 1000..5000")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = args.output_dir / f"at8811c_drift_{run_id}.csv"
    summary_path = args.output_dir / f"at8811c_drift_{run_id}.json"
    config = AT8811CConfig(port=args.port, timeout_s=0.5, retries=1)
    driver = AT8811CModbusRTU(config)
    vibration_driver = None
    samples: list[tuple[float, int]] = []

    try:
        driver.connect()
        if not args.skip_zero:
            driver.zero(authorized=True)
            print("zero command acknowledged")
        if vibration_enabled:
            vibration_driver = LA10ModbusRTU(
                LA10Config(port=args.la10_port, slave_address=args.la10_address)
            )
            vibration_driver.connect()
            vibration_driver.start_vibration(
                frequency_hz=args.vibration_frequency_hz,
                duty_permyriad=args.vibration_duty_permyriad,
            )
            print(
                "vibration started: "
                f"{args.vibration_frequency_hz} Hz, "
                f"duty {args.vibration_duty_permyriad}"
            )

        started_monotonic = time.monotonic()
        deadline = started_monotonic + args.duration_s
        next_sample_at = started_monotonic
        with csv_path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(
                output,
                fieldnames=(
                    "timestamp_utc",
                    "elapsed_s",
                    "raw_count",
                    "mass_mg",
                    "status_word_hex",
                    "stable",
                    "in_zero_band",
                    "vibration_enabled",
                    "vibration_frequency_hz",
                    "vibration_duty_permyriad",
                ),
            )
            writer.writeheader()
            while True:
                now = time.monotonic()
                if now >= deadline:
                    break
                if now < next_sample_at:
                    time.sleep(min(next_sample_at - now, 0.1))
                    continue

                measurement = driver.read_measurement()
                elapsed_s = time.monotonic() - started_monotonic
                samples.append((elapsed_s, measurement.raw_count))
                writer.writerow(
                    {
                        "timestamp_utc": measurement.captured_at.isoformat(),
                        "elapsed_s": f"{elapsed_s:.3f}",
                        "raw_count": measurement.raw_count,
                        "mass_mg": measurement.mass_mg,
                        "status_word_hex": f"0x{measurement.status_word:04X}",
                        "stable": measurement.stable,
                        "in_zero_band": measurement.in_zero_band,
                        "vibration_enabled": vibration_enabled,
                        "vibration_frequency_hz": args.vibration_frequency_hz,
                        "vibration_duty_permyriad": args.vibration_duty_permyriad,
                    }
                )
                output.flush()
                next_sample_at += args.interval_s

        raw_counts = [value for _, value in samples]
        summary = {
            "run_id": run_id,
            "device": "AT8811C",
            "port": args.port,
            "zero_command_sent": not args.skip_zero,
            "vibration_enabled": vibration_enabled,
            "vibration_frequency_hz": args.vibration_frequency_hz,
            "vibration_duty_permyriad": args.vibration_duty_permyriad,
            "requested_duration_s": args.duration_s,
            "sampling_interval_s": args.interval_s,
            "sample_count": len(samples),
            "actual_duration_s": round(samples[-1][0], 3) if samples else 0.0,
            "raw_count_min": min(raw_counts) if raw_counts else None,
            "raw_count_max": max(raw_counts) if raw_counts else None,
            "raw_count_mean": mean(raw_counts) if raw_counts else None,
            "raw_count_first": raw_counts[0] if raw_counts else None,
            "raw_count_last": raw_counts[-1] if raw_counts else None,
            "drift_counts_per_s": _linear_slope(samples),
            "stable_sample_count": None,
            "zero_band_sample_count": None,
            "csv_log": str(csv_path),
        }
        with csv_path.open("r", encoding="utf-8", newline="") as input_file:
            rows = list(csv.DictReader(input_file))
        summary["stable_sample_count"] = sum(row["stable"] == "True" for row in rows)
        summary["zero_band_sample_count"] = sum(row["in_zero_band"] == "True" for row in rows)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        if vibration_driver is not None:
            try:
                vibration_driver.stop_vibration()
                print("vibration stopped")
            finally:
                vibration_driver.close()
        driver.close()


def add_monitor_drift_parser(sub) -> None:
    p = sub.add_parser("monitor-drift", help="record AT8811C drift, optionally while exercising LA10 vibration")
    p.add_argument("--port", default="COM9", help="AT8811C serial port")
    p.add_argument("--duration-s", type=float, default=300.0, help="sampling duration")
    p.add_argument("--interval-s", type=float, default=1.0, help="sampling interval")
    p.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "logs")
    p.add_argument(
        "--skip-zero",
        action="store_true",
        help="do not send the authorized zero command before sampling",
    )
    p.add_argument("--la10-port", help="LA10/ESP32 serial port; required for vibration")
    p.add_argument("--la10-address", type=int, default=1, help="LA10 Modbus address")
    p.add_argument("--vibration-frequency-hz", type=int, help="vibration frequency, 10-80 Hz")
    p.add_argument(
        "--vibration-duty-permyriad",
        type=int,
        help="vibration duty register, 1000-5000 means 10%%-50%%",
    )
    p.set_defaults(func=cmd_monitor_drift)


# ── diagnose-empty (was diagnose_la10_empty_motion.py) ───────────────────────


def _diagnose_empty_motion(device, *, clock=time):
    started = clock.monotonic()
    report = {
        "test_type": "empty_window_diagnostic",
        "started_at": datetime.now().astimezone().isoformat(),
        "user_confirmed_empty": True,
        "targets": [350, 370, 350],
        "speed_mm_s": 1.0,
        "tolerance_units": 10,
        "serial_retries": 0,
        "motion_retries": 0,
        "vibration_start_commands": 0,
        "result": "running",
        "commands": [],
        "samples": [],
        "segments": [],
    }

    def read(phase):
        begin = clock.monotonic()
        status = device.read_status()
        report["samples"].append({
            "elapsed_s": round(clock.monotonic() - started, 4),
            "read_duration_s": round(clock.monotonic() - begin, 4),
            "phase": phase, **asdict(status),
        })
        if status.fault_bits:
            raise RuntimeError(f"fault bits 0x{status.fault_bits:04X}")
        if not 330 <= status.position_units <= 390:
            raise RuntimeError(f"outside diagnostic safety envelope: {status.position_units}")
        return status

    def observe(phase, seconds):
        deadline = clock.monotonic() + seconds
        offset = len(report["samples"])
        status = None
        while clock.monotonic() < deadline:
            status = read(phase)
            clock.sleep(0.1)
        return status, report["samples"][offset:]

    def require_stopped(status, samples, target=None):
        tail = samples[-3:]
        if len(tail) < 3 or any(s["is_running"] for s in tail):
            raise RuntimeError("window was not stopped at end of observation")
        if max(s["position_units"] for s in tail) - min(s["position_units"] for s in tail) > 3:
            raise RuntimeError("position was not stable at end of observation")
        if target is not None and abs(status.position_units - target) > 10:
            raise RuntimeError(f"off target: requested={target}, actual={status.position_units}")

    def record_write(kind, action, **details):
        item = {"kind": kind, "elapsed_s": round(clock.monotonic() - started, 4), **details}
        report["commands"].append(item)
        action()
        item["acknowledged"] = True

    try:
        initial = read("initial")
        vibration = device.read_vibration_settings()
        report["vibration_before"] = asdict(vibration)
        if initial.is_running or vibration.enabled:
            raise RuntimeError("device is not idle; no diagnostic motion permitted")
        status, baseline = observe("baseline", 2.0)
        require_stopped(status, baseline, 350)
        report["baseline_result_codes"] = sorted({s["last_result"] for s in baseline})
        if status.last_result != 0:
            raise RuntimeError("nonzero result at final baseline read; no motion issued")

        for index, target in enumerate(report["targets"]):
            segment = {"target": target, "before": status.position_units}
            report["segments"].append(segment)
            if abs(target - status.position_units) <= 10:
                segment.update({"skipped_within_tolerance": True, "after": status.position_units})
                continue
            # Recheck the actual device directly immediately before the ONLY command.
            status = read(f"pre_command_{index}")
            if status.is_running or status.last_result != 0:
                raise RuntimeError("running/nonzero result before command; no motion issued")
            if device.read_vibration_settings().enabled:
                raise RuntimeError("unexpected vibration before motion")
            delta = target - status.position_units
            distance_register = max(1, round(abs(delta) / 2))
            if distance_register > 20:
                raise RuntimeError("diagnostic relative travel exceeds 0.20 mm")
            record_write("enable", device.enable)
            record_write(
                "relative_motion_0x10",
                lambda: device.move_relative(
                    extend=delta > 0, distance_mm=distance_register / 100, speed_mm_s=1.0,
                ), target=target, from_position=status.position_units,
                distance_register=distance_register, extend=delta > 0,
            )
            status, samples = observe(f"move_to_{target}", 4.0)
            require_stopped(status, samples, target)
            codes = sorted({s["last_result"] for s in samples})
            segment.update({"after": status.position_units, "result_codes": codes,
                            "position_reached": True, "saw_running": any(s["is_running"] for s in samples)})
            if any(codes):
                report["result"] = "result_code_anomaly"
                report["reason"] = "nonzero code observed; no subsequent move/correction issued"
                break
        else:
            report["result"] = "position_round_trip_completed"
    except Exception as error:
        report["result"] = "aborted"
        report["error"] = str(error)
    finally:
        # Stop-only cleanup. Never attempt an automatic return/correction on failure.
        try:
            status = device.read_status()
            vibration = device.read_vibration_settings()
            if vibration.enabled:
                record_write("stop_vibration", device.stop_vibration)
            if status.is_running or report["result"] == "aborted":
                record_write("emergency_stop", device.emergency_stop)
            status, cleanup = observe("final_observation", 1.0)
            require_stopped(status, cleanup)
            vibration = device.read_vibration_settings()
            report["final_status"] = asdict(status)
            report["vibration_after"] = asdict(vibration)
            report["stopped_confirmed"] = not status.is_running and not vibration.enabled
        except Exception as error:
            report["cleanup_error"] = str(error)
            report["stopped_confirmed"] = False
            # Communication may have failed; make best-effort stop-only writes.
            for kind, action in (("stop_vibration", device.stop_vibration),
                                 ("emergency_stop", device.emergency_stop)):
                try:
                    record_write(kind, action)
                except Exception as stop_error:
                    report.setdefault("stop_errors", []).append(str(stop_error))
        report["elapsed_s"] = round(clock.monotonic() - started, 4)
        report["finished_at"] = datetime.now().astimezone().isoformat()
    return report


def cmd_diagnose_empty(args: argparse.Namespace) -> int:
    if not args.confirm_empty_and_clear:
        raise SystemExit("explicit empty feeder and clear motion area confirmation is required (--confirm-empty-and-clear)")
    device = _LA10ModbusRTUDirect(_LA10ConfigDirect(port=args.port, timeout_s=0.5, retries=0))
    try:
        report = _diagnose_empty_motion(device)
        report["port"] = args.port
        print(json.dumps(report, ensure_ascii=False))
    finally:
        device.close()
    return 0


def add_diagnose_empty_parser(sub) -> None:
    p = sub.add_parser(
        "diagnose-empty",
        help="one supervised empty-feeder diagnostic; never starts vibration or retries a move",
    )
    p.add_argument("--port", default="COM8")
    p.add_argument("--confirm-empty-and-clear", action="store_true")
    p.set_defaults(func=cmd_diagnose_empty)


# ── scan-startup (was scan_low_rate_startup.py) ──────────────────────────────

LOG_DIR = PROJECT_ROOT / "logs"
WINDOW_POSITION_UNITS = 100
TEST_DURATION_S = 20.0
SETTLE_WAIT_S = 20.0
SAFETY_MASS_MG = 250.0
POLL_INTERVAL_S = 0.25

# Low-amplitude screening only. They are deliberately below the historical
# 65 Hz / 16% reference, which entered a high-flow state in 500 mg trials.
DEFAULT_CANDIDATES = (
    {"candidate_id": "S1", "frequency_hz": 50, "duty_permyriad": 1400},
    {"candidate_id": "S2", "frequency_hz": 50, "duty_permyriad": 1600},
    {"candidate_id": "S3", "frequency_hz": 55, "duty_permyriad": 1200},
    {"candidate_id": "S4", "frequency_hz": 55, "duty_permyriad": 1400},
    {"candidate_id": "S5", "frequency_hz": 60, "duty_permyriad": 1200},
    {"candidate_id": "S6", "frequency_hz": 60, "duty_permyriad": 1400},
    {"candidate_id": "S7", "frequency_hz": 65, "duty_permyriad": 1100},
    {"candidate_id": "S8", "frequency_hz": 65, "duty_permyriad": 1300},
)


def _backend_request_json(base_url: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method="GET" if payload is None else "POST",
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body).get("error", body)
        except json.JSONDecodeError:
            detail = body
        raise RuntimeError(f"backend request {path} failed: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"cannot reach device backend at {base_url}: {error.reason}") from error


def _rolling_peak_rate(samples: list[dict], window_s: float = 2.0) -> float | None:
    peak = None
    for right, sample in enumerate(samples):
        elapsed = sample.get("elapsed_s")
        mass = sample.get("mass_mg")
        if not isinstance(elapsed, (int, float)) or not isinstance(mass, (int, float)):
            continue
        left = right
        while left > 0 and elapsed - samples[left].get("elapsed_s", elapsed) < window_s:
            left -= 1
        earlier = samples[left]
        earlier_time = earlier.get("elapsed_s")
        earlier_mass = earlier.get("mass_mg")
        if not isinstance(earlier_time, (int, float)) or not isinstance(earlier_mass, (int, float)):
            continue
        duration = elapsed - earlier_time
        if duration <= 0:
            continue
        rate = (mass - earlier_mass) / duration
        peak = rate if peak is None else max(peak, rate)
    return peak


def _summarize_run(candidate: dict, result: dict, *, safety_stop_requested: bool) -> dict:
    samples = result.get("samples", [])
    valid = [
        sample
        for sample in samples
        if isinstance(sample.get("elapsed_s"), (int, float))
        and isinstance(sample.get("mass_mg"), (int, float))
    ]
    first = valid[0] if valid else {}
    last = valid[-1] if valid else {}
    elapsed_s = float(last.get("elapsed_s", result.get("actual_duration_s", 0.0)) or 0.0)
    mass_gain_mg = float(last.get("mass_mg", 0.0) - first.get("mass_mg", 0.0)) if valid else 0.0
    first_flow = next((sample for sample in valid if sample["mass_mg"] >= 2.0), None)
    startup_delay_s = None if first_flow is None else float(first_flow["elapsed_s"] - first["elapsed_s"])
    average_rate = mass_gain_mg / elapsed_s if elapsed_s > 0 else 0.0
    peak_rate = _rolling_peak_rate(valid)
    accepted = (
        result.get("result") == "completed"
        and not safety_stop_requested
        and startup_delay_s is not None
        and startup_delay_s <= 5.0
        and 2.0 <= average_rate <= 8.0
        and (peak_rate is None or peak_rate <= 10.0)
    )
    return {
        "candidate_id": candidate["candidate_id"],
        "frequency_hz": candidate["frequency_hz"],
        "duty_permyriad": candidate["duty_permyriad"],
        "window_position_units": WINDOW_POSITION_UNITS,
        "backend_run_id": result.get("run_id"),
        "backend_result": result.get("result"),
        "backend_error": result.get("error") or result.get("stop_error"),
        "log_path": result.get("log_path"),
        "samples_csv_path": result.get("samples_csv_path"),
        "actual_duration_s": round(float(result.get("actual_duration_s", elapsed_s) or 0.0), 3),
        "mass_gain_mg": round(mass_gain_mg, 3),
        "average_rate_mg_s": round(average_rate, 3),
        "peak_2s_rate_mg_s": None if peak_rate is None else round(peak_rate, 3),
        "startup_delay_s": None if startup_delay_s is None else round(startup_delay_s, 3),
        "safety_stop_requested": safety_stop_requested,
        "accepted_seed": accepted,
    }


def _wait_for_run(base_url: str, run_id: str, safety_mass_mg: float) -> tuple[dict, bool]:
    safety_stop_requested = False
    while True:
        snapshot = _backend_request_json(base_url, "/api/snapshot")
        test = snapshot.get("test", {})
        if test.get("run_id") == run_id:
            sample = test.get("latest_sample") or {}
            mass_mg = sample.get("mass_mg")
            if (
                not safety_stop_requested
                and isinstance(mass_mg, (int, float))
                and mass_mg >= safety_mass_mg
                and test.get("status") == "running"
            ):
                _backend_request_json(base_url, "/api/vibration-test/cancel", {})
                safety_stop_requested = True
            if test.get("status") in {"completed", "failed", "cancelled"}:
                return test.get("result", {}), safety_stop_requested
        time.sleep(POLL_INTERVAL_S)


def _run_scan(
    base_url: str,
    candidates: tuple[dict, ...],
    amplitude_note: str,
    safety_mass_mg: float,
) -> list[dict]:
    summaries = []
    for index, candidate in enumerate(candidates, start=1):
        payload = {
            "target_window_position_units": WINDOW_POSITION_UNITS,
            "window_speed_mm_s": 1.0,
            "window_timeout_s": 20.0,
            "frequency_hz": candidate["frequency_hz"],
            "duty_permyriad": candidate["duty_permyriad"],
            "duration_s": TEST_DURATION_S,
        }
        response = _backend_request_json(base_url, "/api/vibration-test", payload)
        result, safety_stop_requested = _wait_for_run(
            base_url, response["run_id"], safety_mass_mg
        )
        summary = _summarize_run(candidate, result, safety_stop_requested=safety_stop_requested)
        summary["amplitude_note"] = amplitude_note
        summaries.append(summary)
        print(
            f"[{index}/{len(candidates)}] {candidate['candidate_id']}: "
            f"{summary['mass_gain_mg']:.1f} mg, "
            f"{summary['average_rate_mg_s']:.2f} mg/s, "
            f"accepted={summary['accepted_seed']}"
        )
        if index < len(candidates):
            time.sleep(SETTLE_WAIT_S)
    return summaries


def _write_report(
    summaries: list[dict], amplitude_note: str, safety_mass_mg: float
) -> tuple[Path, Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prefix = LOG_DIR / f"low_rate_startup_scan_{timestamp}"
    accepted = [item for item in summaries if item["accepted_seed"]]
    report = {
        "test_type": "low_rate_startup_scan",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "amplitude_note": amplitude_note,
        "window_position_units": WINDOW_POSITION_UNITS,
        "duration_per_candidate_s": TEST_DURATION_S,
        "settle_wait_between_candidates_s": SETTLE_WAIT_S,
        "safety_mass_mg": safety_mass_mg,
        "acceptance_rule": {
            "startup_delay_max_s": 5.0,
            "average_rate_range_mg_s": [2.0, 8.0],
            "peak_2s_rate_max_mg_s": 10.0,
        },
        "recommended_candidates": sorted(
            accepted,
            key=lambda item: (
                abs(item["average_rate_mg_s"] - 5.0),
                item["peak_2s_rate_mg_s"] or float("inf"),
            ),
        ),
        "summaries": summaries,
    }
    json_path = prefix.with_suffix(".json")
    csv_path = prefix.with_suffix(".csv")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]) if summaries else [])
        writer.writeheader()
        writer.writerows(summaries)
    return json_path, csv_path


def cmd_scan_startup(args: argparse.Namespace) -> int:
    candidates = DEFAULT_CANDIDATES
    if args.frequency is not None:
        if not 10 <= args.frequency <= 80:
            raise SystemExit("--frequency must be in 10..80 Hz")
        duty_values = (
            [int(value.strip()) for value in args.duties.split(",") if value.strip()]
            if args.duties
            else [1000, 1050, 1100, 1150, 1200, 1250, 1300, 1350]
        )
        if not duty_values or any(value < 1000 or value > 5000 for value in duty_values):
            raise SystemExit("every --duties value must be in 1000..5000")
        candidates = tuple(
            {
                "candidate_id": f"F{args.frequency}-D{duty}",
                "frequency_hz": args.frequency,
                "duty_permyriad": duty,
            }
            for duty in duty_values
        )
    if not args.execute:
        print("Dry run. Physical scan is not started. Candidates:")
        for candidate in candidates:
            print(
                f"{candidate['candidate_id']}: window {WINDOW_POSITION_UNITS}, "
                f"{candidate['frequency_hz']} Hz, {candidate['duty_permyriad'] / 100:.1f}%"
            )
        return 0
    summaries = _run_scan(args.base_url, candidates, args.amplitude_note, args.safety_mass_mg)
    json_path, csv_path = _write_report(summaries, args.amplitude_note, args.safety_mass_mg)
    accepted = [item for item in summaries if item["accepted_seed"]]
    print(f"Saved summary: {json_path}")
    print(f"Saved table: {csv_path}")
    print(f"Accepted low-rate seeds: {len(accepted)} / {len(summaries)}")
    return 0


def add_scan_startup_parser(sub) -> None:
    p = sub.add_parser(
        "scan-startup",
        help="run and analyze a guarded low-rate startup scan through the device backend",
    )
    p.add_argument("--base-url", default=DEFAULT_BACKEND_URL)
    p.add_argument(
        "--amplitude-note",
        default="operator-set low amplitude after standardized high-amplitude conditioning",
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help="run the physical scan; omit to print the candidate plan only",
    )
    p.add_argument("--frequency", type=int, default=None)
    p.add_argument(
        "--duties",
        default=None,
        help="comma-separated duty-permyriad values, for example 1000,1050,1100",
    )
    p.add_argument("--safety-mass-mg", type=float, default=SAFETY_MASS_MG)
    p.set_defaults(func=cmd_scan_startup)


# ── vibration-test (was test_vibration_feed.py) ──────────────────────────────


def cmd_vibration_test(args: argparse.Namespace) -> int:
    payload = {
        "target_window_position_units": args.target_window_position_units,
        "window_speed_mm_s": args.window_speed_mm_s,
        "window_timeout_s": args.window_timeout_s,
        "frequency_hz": args.frequency_hz,
        "duty_permyriad": args.duty_permyriad,
        "duration_s": args.duration_s,
    }
    if args.duty_sequence:
        payload["duty_schedule"] = [int(value.strip()) for value in args.duty_sequence.split(",")]
        payload["segment_duration_s"] = args.duration_s
    base = args.backend_url.rstrip("/")
    try:
        accepted = _request_json(f"{base}/api/vibration-test", "POST", payload)
    except URLError as error:
        raise SystemExit(f"无法连接设备后台 {base}: {error}")
    run_id = accepted["run_id"]
    print(f"test accepted: {run_id}")
    try:
        while True:
            snapshot = _request_json(f"{base}/api/snapshot")
            test = snapshot.get("test", {})
            if test.get("run_id") == run_id and test.get("status") != "running":
                print(json.dumps(test, ensure_ascii=False, indent=2))
                return 0 if test.get("status") == "completed" else 1
            time.sleep(0.25)
    except KeyboardInterrupt:
        _request_json(f"{base}/api/vibration-test/cancel", "POST", {})
        print("cancel requested")
        return 130


def add_vibration_test_parser(sub) -> None:
    p = sub.add_parser("vibration-test", help="submit a vibration feed test; the backend tares the AT8811C before motion")
    p.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    p.add_argument("--target-window-position-units", type=int, default=500)
    p.add_argument("--window-speed-mm-s", type=float, default=1.0)
    p.add_argument("--window-timeout-s", type=float, default=20.0)
    p.add_argument("--frequency-hz", type=int, default=60)
    p.add_argument("--duty-permyriad", type=int, default=3000)
    p.add_argument("--duration-s", type=float, default=10.0)
    p.add_argument(
        "--duty-sequence",
        default="",
        help="comma-separated duty values; vibration remains enabled while the sequence runs",
    )
    p.set_defaults(func=cmd_vibration_test)


# ── window-sweep (was test_window_position_sweep.py) ─────────────────────────


def position_schedule(start, end, step):
    """Shared helper (also imported by tests/test_window_position_sweep_api.py)."""
    if step <= 0:
        raise ValueError("step-units must be positive")
    if start > end:
        raise ValueError("start-position-units must not exceed end-position-units")
    return list(range(start, end + 1, step))


def cmd_window_sweep(args: argparse.Namespace) -> int:
    positions = position_schedule(args.start_position_units, args.end_position_units, args.step_units)
    payload = {
        "position_schedule": positions,
        "window_speed_mm_s": args.window_speed_mm_s,
        "window_timeout_s": args.window_timeout_s,
        "frequency_hz": args.frequency_hz,
        "duty_permyriad": args.duty_permyriad,
        "duration_s": args.duration_s,
    }
    base = args.backend_url.rstrip("/")
    try:
        accepted = _request_json(f"{base}/api/window-position-sweep", "POST", payload)
    except URLError as error:
        raise SystemExit(f"Cannot reach the device backend: {error}")
    run_id = accepted["run_id"]
    print(f"window sweep accepted: {run_id}; positions={positions}")
    try:
        while True:
            snapshot = _request_json(f"{base}/api/snapshot")
            test = snapshot.get("test", {})
            if test.get("run_id") == run_id:
                if test.get("status") != "running":
                    print(json.dumps(test, ensure_ascii=False, indent=2))
                    return 0 if test.get("status") == "completed" else 1
                sample = test.get("latest_sample", {})
                print(
                    "\rsegment {}/{} position={} mass={} mg rate={} mg/s".format(
                        test.get("segment_index", "-"),
                        test.get("segment_count", "-"),
                        test.get("target_window_position_units", "-"),
                        sample.get("mass_mg", "-"),
                        sample.get("rate_mg_s", "-"),
                    ),
                    end="",
                    flush=True,
                )
            time.sleep(0.25)
    except KeyboardInterrupt:
        _request_json(f"{base}/api/vibration-test/cancel", "POST", {})
        print("\ncancel requested")
        return 130


def add_window_sweep_parser(sub) -> None:
    p = sub.add_parser(
        "window-sweep",
        help="submit the LA10 window-position calibration sweep to the device backend",
    )
    p.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    p.add_argument("--start-position-units", type=int, default=100)
    p.add_argument("--end-position-units", type=int, default=750)
    p.add_argument("--step-units", type=int, default=50)
    p.add_argument("--window-speed-mm-s", type=float, default=1.0)
    p.add_argument("--window-timeout-s", type=float, default=20.0)
    p.add_argument("--frequency-hz", type=int, default=80)
    p.add_argument("--duty-permyriad", type=int, default=2000)
    p.add_argument("--duration-s", type=float, default=10.0)
    p.set_defaults(func=cmd_window_sweep)


# ── save-result (was save_latest_test_result.py) ─────────────────────────────


def cmd_save_result(args: argparse.Namespace) -> int:
    with urlopen(args.backend_url.rstrip("/") + "/api/snapshot", timeout=5) as response:
        snapshot = json.loads(response.read().decode("utf-8"))
    test = snapshot.get("test", {})
    result = test.get("result")
    if not isinstance(result, dict) or not result.get("run_id"):
        raise SystemExit("backend has no completed test result to save")
    prefix = "window_position_sweep" if result.get("test_type") == "window_position_sweep" else "recovered_test"
    output = PROJECT_ROOT / "logs" / f"{prefix}_{result['run_id']}_recovered.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    return 0


def add_save_result_parser(sub) -> None:
    p = sub.add_parser("save-result", help="save the device backend's latest in-memory test result as a JSON log")
    p.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    p.set_defaults(func=cmd_save_result)


# ── entry point ──────────────────────────────────────────────────────────────

# Public aliases kept for the unit tests that exercise these helpers directly.
diagnose = _diagnose_empty_motion
summarize_run = _summarize_run


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    add_calibrate_scale_parser(sub)
    add_calibrate_yield_parser(sub)
    add_monitor_drift_parser(sub)
    add_diagnose_empty_parser(sub)
    add_scan_startup_parser(sub)
    add_vibration_test_parser(sub)
    add_window_sweep_parser(sub)
    add_save_result_parser(sub)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
