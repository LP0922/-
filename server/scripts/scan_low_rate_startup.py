"""Run and analyze a guarded low-rate startup scan through the device backend.

The operator must complete the same high-amplitude powder-conditioning step,
switch the hardware to low amplitude, and then invoke this script with
``--execute``. Every candidate is tared by the backend, vibrated for at most
20 seconds, then left undisturbed for 20 seconds before the next candidate.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
DEFAULT_BASE_URL = "http://127.0.0.1:8765"
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


def request_json(base_url: str, path: str, payload: dict | None = None) -> dict:
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


def rolling_peak_rate(samples: list[dict], window_s: float = 2.0) -> float | None:
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


def summarize_run(candidate: dict, result: dict, *, safety_stop_requested: bool) -> dict:
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
    peak_rate = rolling_peak_rate(valid)
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


def wait_for_run(base_url: str, run_id: str, safety_mass_mg: float) -> tuple[dict, bool]:
    safety_stop_requested = False
    while True:
        snapshot = request_json(base_url, "/api/snapshot")
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
                request_json(base_url, "/api/vibration-test/cancel", {})
                safety_stop_requested = True
            if test.get("status") in {"completed", "failed", "cancelled"}:
                return test.get("result", {}), safety_stop_requested
        time.sleep(POLL_INTERVAL_S)


def run_scan(
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
        response = request_json(base_url, "/api/vibration-test", payload)
        result, safety_stop_requested = wait_for_run(
            base_url, response["run_id"], safety_mass_mg
        )
        summary = summarize_run(candidate, result, safety_stop_requested=safety_stop_requested)
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


def write_report(
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


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--amplitude-note",
        default="operator-set low amplitude after standardized high-amplitude conditioning",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="run the physical scan; omit to print the candidate plan only",
    )
    parser.add_argument("--frequency", type=int, default=None)
    parser.add_argument(
        "--duties",
        default=None,
        help="comma-separated duty-permyriad values, for example 1000,1050,1100",
    )
    parser.add_argument("--safety-mass-mg", type=float, default=SAFETY_MASS_MG)
    return parser.parse_args()


def main():
    args = parse_args()
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
    summaries = run_scan(args.base_url, candidates, args.amplitude_note, args.safety_mass_mg)
    json_path, csv_path = write_report(summaries, args.amplitude_note, args.safety_mass_mg)
    accepted = [item for item in summaries if item["accepted_seed"]]
    print(f"Saved summary: {json_path}")
    print(f"Saved table: {csv_path}")
    print(f"Accepted low-rate seeds: {len(accepted)} / {len(summaries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
