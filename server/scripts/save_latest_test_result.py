"""Save the device backend's latest in-memory test result as a JSON log."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
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


if __name__ == "__main__":
    raise SystemExit(main())
