"""Record AT8811C drift, optionally while exercising an LA10 vibration module."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from powder_sampling_control.device_adapters import (
    AT8811CConfig,
    AT8811CModbusRTU,
    LA10Config,
    LA10ModbusRTU,
)


def linear_slope(samples: list[tuple[float, int]]) -> float:
    """Return least-squares raw-count drift in counts per second."""
    if len(samples) < 2:
        return 0.0
    mean_x = mean(item[0] for item in samples)
    mean_y = mean(item[1] for item in samples)
    denominator = sum((x - mean_x) ** 2 for x, _ in samples)
    if denominator == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in samples) / denominator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM9", help="AT8811C serial port")
    parser.add_argument("--duration-s", type=float, default=300.0, help="sampling duration")
    parser.add_argument("--interval-s", type=float, default=1.0, help="sampling interval")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "logs")
    parser.add_argument(
        "--skip-zero",
        action="store_true",
        help="do not send the authorized zero command before sampling",
    )
    parser.add_argument("--la10-port", help="LA10/ESP32 serial port; required for vibration")
    parser.add_argument("--la10-address", type=int, default=1, help="LA10 Modbus address")
    parser.add_argument("--vibration-frequency-hz", type=int, help="vibration frequency, 10-80 Hz")
    parser.add_argument(
        "--vibration-duty-permyriad",
        type=int,
        help="vibration duty register, 1000-5000 means 10%%-50%%",
    )
    arguments = parser.parse_args()
    if arguments.duration_s <= 0 or arguments.interval_s <= 0:
        parser.error("duration and interval must be positive")
    vibration_values = (arguments.vibration_frequency_hz, arguments.vibration_duty_permyriad)
    if any(value is not None for value in vibration_values):
        if not arguments.la10_port or any(value is None for value in vibration_values):
            parser.error(
                "vibration requires --la10-port, --vibration-frequency-hz, and "
                "--vibration-duty-permyriad"
            )
        if not 10 <= arguments.vibration_frequency_hz <= 80:
            parser.error("--vibration-frequency-hz must be in the range 10..80")
        if not 1000 <= arguments.vibration_duty_permyriad <= 5000:
            parser.error("--vibration-duty-permyriad must be in the range 1000..5000")
    return arguments


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = args.output_dir / f"at8811c_drift_{run_id}.csv"
    summary_path = args.output_dir / f"at8811c_drift_{run_id}.json"
    config = AT8811CConfig(port=args.port, timeout_s=0.5, retries=1)
    driver = AT8811CModbusRTU(config)
    vibration_driver = None
    vibration_enabled = args.vibration_frequency_hz is not None
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
            "drift_counts_per_s": linear_slope(samples),
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


if __name__ == "__main__":
    raise SystemExit(main())
