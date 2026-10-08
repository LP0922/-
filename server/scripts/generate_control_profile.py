"""Preview or write a draft runtime control profile from a powder workspace."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from powder_sampling_control.dispensing_algorithm.method_generator import (
    build_candidate_control_profile,
)


def _find_workspace(powder_id: str) -> Path:
    for path in (PROJECT_ROOT / "data" / "powder_library").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("powder_id") == powder_id:
            return path
    raise FileNotFoundError(f"powder workspace not found: {powder_id}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("powder_id")
    parser.add_argument(
        "--write",
        action="store_true",
        help="write data/control_profiles/{powder_id}.json instead of previewing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow replacing an existing draft control profile",
    )
    args = parser.parse_args()

    workspace_path = _find_workspace(args.powder_id)
    workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
    candidate = build_candidate_control_profile(workspace)
    rendered = json.dumps(candidate, ensure_ascii=False, indent=2) + "\n"

    if not args.write:
        print(rendered, end="")
        return 0

    output = PROJECT_ROOT / "data" / "control_profiles" / f"{args.powder_id}.json"
    if output.exists() and not args.force:
        raise FileExistsError(f"control profile already exists; use --force: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
