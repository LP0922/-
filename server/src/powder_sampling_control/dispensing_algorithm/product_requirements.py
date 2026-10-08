"""Central product limits shared by planning, APIs, and result evaluation."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REQUIREMENTS_PATH = PROJECT_ROOT / "config" / "product_requirements.json"


@lru_cache(maxsize=1)
def load_product_requirements() -> dict[str, Any]:
    data = json.loads(DEFAULT_REQUIREMENTS_PATH.read_text(encoding="utf-8"))
    target = data.get("target_mass", {})
    acceptance = data.get("acceptance", {})
    minimum = target.get("minimum_mg")
    maximum = target.get("maximum_mg")
    if not isinstance(minimum, int) or not isinstance(maximum, int) or minimum >= maximum:
        raise ValueError("product target_mass limits must be increasing integers")
    if target.get("integer_only") is not True:
        raise ValueError("this product requires integer target masses")
    for key in ("minimum_offset_mg", "maximum_offset_mg"):
        if not isinstance(acceptance.get(key), (int, float)):
            raise ValueError(f"acceptance.{key} must be numeric")
    return data


def validate_target_mass(target_mg: Any) -> int:
    """Return a valid integer target in the configured 100-1000 mg range."""
    requirements = load_product_requirements()
    limits = requirements["target_mass"]
    if isinstance(target_mg, bool) or not isinstance(target_mg, int):
        raise ValueError(
            f"target_mg must be an integer between {limits['minimum_mg']} "
            f"and {limits['maximum_mg']}"
        )
    if not limits["minimum_mg"] <= target_mg <= limits["maximum_mg"]:
        raise ValueError(
            f"target_mg must be between {limits['minimum_mg']} and "
            f"{limits['maximum_mg']}, got {target_mg}"
        )
    return target_mg


def acceptance_limits(target_mg: Any) -> tuple[float, float]:
    """Return the inclusive Target +/- 10 mg acceptance window."""
    target = validate_target_mass(target_mg)
    acceptance = load_product_requirements()["acceptance"]
    return (
        target + float(acceptance["minimum_offset_mg"]),
        target + float(acceptance["maximum_offset_mg"]),
    )
