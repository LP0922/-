"""Submit a vibration feed test; the backend tares the AT8811C before motion."""

from __future__ import annotations

import argparse
import json
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", default="http://127.0.0.1:8765")
    parser.add_argument("--target-window-position-units", type=int, default=500)
    parser.add_argument("--window-speed-mm-s", type=float, default=1.0)
    parser.add_argument("--window-timeout-s", type=float, default=20.0)
    parser.add_argument("--frequency-hz", type=int, default=60)
    parser.add_argument("--duty-permyriad", type=int, default=3000)
    parser.add_argument("--duration-s", type=float, default=10.0)
    parser.add_argument(
        "--duty-sequence",
        default="",
        help="comma-separated duty values; vibration remains enabled while the sequence runs",
    )
    return parser.parse_args()


def request_json(url, method="GET", payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    args = parse_args()
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
        accepted = request_json(f"{base}/api/vibration-test", "POST", payload)
    except URLError as error:
        raise SystemExit(f"无法连接设备后台 {base}: {error}")
    run_id = accepted["run_id"]
    print(f"test accepted: {run_id}")
    try:
        while True:
            snapshot = request_json(f"{base}/api/snapshot")
            test = snapshot.get("test", {})
            if test.get("run_id") == run_id and test.get("status") != "running":
                print(json.dumps(test, ensure_ascii=False, indent=2))
                return 0 if test.get("status") == "completed" else 1
            time.sleep(0.25)
    except KeyboardInterrupt:
        request_json(f"{base}/api/vibration-test/cancel", "POST", {})
        print("cancel requested")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
