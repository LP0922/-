"""Submit the 80 Hz / 20% LA10 window-position calibration sweep to the device backend.

The backend owns COM9 and COM8, tares once, starts vibration once, then
moves through each position while vibration remains enabled. It writes a
timestamped JSON log under ``logs/``.
"""

from __future__ import annotations

import argparse
import json
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", default="http://127.0.0.1:8765")
    parser.add_argument("--start-position-units", type=int, default=100)
    parser.add_argument("--end-position-units", type=int, default=750)
    parser.add_argument("--step-units", type=int, default=50)
    parser.add_argument("--window-speed-mm-s", type=float, default=1.0)
    parser.add_argument("--window-timeout-s", type=float, default=20.0)
    parser.add_argument("--frequency-hz", type=int, default=80)
    parser.add_argument("--duty-permyriad", type=int, default=2000)
    parser.add_argument("--duration-s", type=float, default=10.0)
    return parser.parse_args()


def request_json(url, method="GET", payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def position_schedule(start, end, step):
    if step <= 0:
        raise ValueError("step-units must be positive")
    if start > end:
        raise ValueError("start-position-units must not exceed end-position-units")
    return list(range(start, end + 1, step))


def main():
    args = parse_args()
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
        accepted = request_json(f"{base}/api/window-position-sweep", "POST", payload)
    except URLError as error:
        raise SystemExit(f"Cannot reach the device backend: {error}")
    run_id = accepted["run_id"]
    print(f"window sweep accepted: {run_id}; positions={positions}")
    try:
        while True:
            snapshot = request_json(f"{base}/api/snapshot")
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
        request_json(f"{base}/api/vibration-test/cancel", "POST", {})
        print("\ncancel requested")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
