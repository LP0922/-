"""Experiment Orchestrator — auto-generate and execute parameter-grid experiments.

Replaces hand-crafted batch JSON with a declarative grid specification.
The orchestrator expands a parameter grid into all valid combinations,
queues them through the existing batch infrastructure, and returns
structured results that can feed directly into the powder_library.
"""

from __future__ import annotations

import itertools
import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class GridDimension:
    """One sweep axis in an experiment grid."""

    name: str  # "frequency_hz" | "duty_permyriad" | "window_position_units"
    values: list[int | float]

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError(f"dimension {self.name!r} must have at least one value")
        allowed = {"frequency_hz", "duty_permyriad", "window_position_units", "duration_s"}
        if self.name not in allowed:
            raise ValueError(
                f"unknown dimension {self.name!r}; allowed: {sorted(allowed)}"
            )


@dataclass
class GridConstraint:
    """A hardware or safety constraint that filters the grid.

    Built-in constraint types:
      - ``noise_budget``: frequency_hz × duty_permyriad ≤ max_value
    """

    type: str
    max_value: float | int

    def __post_init__(self) -> None:
        if self.type not in ("noise_budget",):
            raise ValueError(f"unknown constraint type {self.type!r}")

    def check(self, params: dict[str, int | float]) -> bool:
        if self.type == "noise_budget":
            freq = params.get("frequency_hz", 0)
            duty = params.get("duty_permyriad", 0)
            return (freq * duty) <= self.max_value
        return True  # unreachable


@dataclass
class GridSpec:
    """Complete specification for one automated experiment sweep."""

    experiment_id: str  # short slug, e.g. "starch-freq-scan"
    powder_name: str  # human-readable, for labelling
    powder_id: str  # matches powder_library/{powder_id}.json
    experiment_type: str = "constant_rate"  # "constant_rate" | "dispense"
    dimensions: list[GridDimension] = field(default_factory=list)
    fixed_params: dict[str, int | float] = field(default_factory=dict)
    constraints: list[GridConstraint] = field(default_factory=list)
    duration_s: float = 15.0
    repeat_count: int = 1
    tare_between_sets: bool = True
    target_rate_mg_s: float = 10.0
    # dispense-specific
    target_mg: int = 0
    preset_id: str = ""

    def __post_init__(self) -> None:
        if not self.dimensions:
            raise ValueError("at least one dimension is required")
        if self.experiment_type == "constant_rate" and self.duration_s <= 0:
            raise ValueError("duration_s must be positive for constant_rate")
        if self.experiment_type == "dispense" and self.target_mg <= 0:
            raise ValueError("target_mg must be positive for dispense experiments")
        if self.repeat_count < 1:
            raise ValueError("repeat_count must be >= 1")


# ---------------------------------------------------------------------------
# Grid expansion
# ---------------------------------------------------------------------------

# Hardware range limits (mirrors device_control_server validation).
_HARDWARE_LIMITS = {
    "frequency_hz": (10, 80),
    "duty_permyriad": (1000, 5000),
    "window_position_units": (100, 750),
    "duration_s": (1, 120),
}


def expand_grid(spec: GridSpec) -> tuple[list[dict[str, Any]], list[str]]:
    """Expand *spec* into a flat list of parameter dicts and a list of warnings.

    Returns ``(valid_sets, warnings)``.  Sets that fail a constraint are
    dropped with a descriptive warning explaining why.
    """
    # Build the Cartesian product
    dim_names = [d.name for d in spec.dimensions]
    value_lists = [d.values for d in spec.dimensions]
    product = list(itertools.product(*value_lists))

    # Check hardware limits
    warnings: list[str] = []

    def _in_range(name: str, value: int | float) -> bool:
        lo, hi = _HARDWARE_LIMITS.get(name, (-math.inf, math.inf))
        ok = lo <= value <= hi
        if not ok:
            warnings.append(
                f"Skip {name}={value}: out of hardware range [{lo}, {hi}]"
            )
        return ok

    expanded: list[dict[str, Any]] = []
    for combo in product:
        params: dict[str, int | float] = dict(zip(dim_names, combo))
        # Merge fixed params
        params.update(spec.fixed_params)

        # Hardware range check
        if not all(_in_range(k, v) for k, v in params.items() if k in _HARDWARE_LIMITS):
            continue

        # Constraint checks
        failed = False
        for constraint in spec.constraints:
            if not constraint.check(params):
                warnings.append(
                    f"Skip {params}: violates {constraint.type} "
                    f"(max {constraint.max_value})"
                )
                failed = True
                break
        if failed:
            continue

        # Build a batch-set entry compatible with existing batch endpoints
        entry: dict[str, Any] = {
            "frequency_hz": int(params["frequency_hz"]),
            "duty_permyriad": int(params["duty_permyriad"]),
            "window_position_units": int(params["window_position_units"]),
            "duration_s": spec.duration_s,
            "repeat_count": spec.repeat_count,
        }
        if spec.experiment_type == "dispense":
            entry["target_mg"] = spec.target_mg
            entry["preset_id"] = spec.preset_id or "fast-80hz-p200"
        expanded.append(entry)

    return expanded, warnings


# ---------------------------------------------------------------------------
# Result collection → powder_library integration
# ---------------------------------------------------------------------------


def _load_powder_library(library_path: str) -> tuple[dict[str, dict], dict[str, str]]:
    """Load all powder workspace files from *library_path*.

    Returns ``(data_by_id, filename_by_id)`` so callers can write back
    to the original file regardless of whether it was named with Chinese
    or English characters.
    """
    data_by_id: dict[str, dict] = {}
    fname_by_id: dict[str, str] = {}
    if not os.path.isdir(library_path):
        return data_by_id, fname_by_id
    for fname in os.listdir(library_path):
        if fname.endswith(".json") and fname != "README.md":
            fpath = os.path.join(library_path, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                pid = data.get("powder_id", fname.replace(".json", ""))
                data_by_id[pid] = data
                fname_by_id[pid] = fname
            except (json.JSONDecodeError, OSError):
                continue
    return data_by_id, fname_by_id


def collect_scan_results(
    batch_result: dict,
    powder_id: str,
    library_path: str = "data/powder_library",
) -> dict:
    """Update a powder workspace ``scan_grid`` from batch results.

    Reads the existing workspace file for *powder_id*, adds or replaces
    scan-grid entries using the per-set summaries from *batch_result*,
    bumps ``updated_at``, and writes back.

    Returns the updated workspace dict (also saved to disk).
    """
    library, fname_by_id = _load_powder_library(library_path)
    workspace = library.get(powder_id)
    if workspace is None:
        raise FileNotFoundError(
            f"powder_id {powder_id!r} not found in {library_path}"
        )

    existing_grid = {_grid_key(e): e for e in workspace.get("scan_grid", [])}
    set_results = batch_result.get("set_results", [])

    for entry in set_results:
        summary = entry.get("summary") or {}
        freq = entry.get("frequency_hz")
        duty = entry.get("duty_permyriad")
        window = entry.get("window_position_units")
        if freq is None or duty is None:
            continue

        key = _grid_key({"frequency_hz": freq, "duty_permyriad": duty,
                          "window_position_units": window})
        mean_rate = summary.get("overall_mean_rate_mg_s")
        cv_pct = summary.get("overall_cv_pct")
        is_stable = bool(summary.get("overall_passed"))
        startup = entry.get("startup_delay_s")

        grid_entry = {
            "frequency_hz": freq,
            "duty_permyriad": duty,
            "window_position_units": window or 250,
            "status": "constant_rate",
            "mean_rate_mg_s": round(mean_rate, 1) if mean_rate is not None else None,
            "cv_pct": round(cv_pct, 1) if cv_pct is not None else None,
            "startup_delay_s": round(startup, 3) if startup is not None else None,
            "is_stable": is_stable,
            "batch_run_id": batch_result.get("run_id", ""),
            "notes": f"auto-collected from experiment {batch_result.get('run_id', '')}",
        }
        existing_grid[key] = grid_entry

    workspace["scan_grid"] = sorted(
        existing_grid.values(),
        key=lambda e: (e.get("frequency_hz", 0), e.get("duty_permyriad", 0)),
    )
    workspace["updated_at"] = datetime.now(timezone.utc).isoformat()

    # Write back to the original file (preserves Chinese/English naming)
    fname = fname_by_id.get(powder_id, f"{powder_id}.json")
    fpath = os.path.join(library_path, fname)
    os.makedirs(library_path, exist_ok=True)
    with open(fpath, "w", encoding="utf-8") as fh:
        json.dump(workspace, fh, ensure_ascii=False, indent=2)

    return workspace


def _grid_key(entry: dict) -> str:
    freq = entry.get("frequency_hz", 0)
    duty = entry.get("duty_permyriad", 0)
    window = entry.get("window_position_units", 0)
    return f"{freq}-{duty}-{window}"


# ---------------------------------------------------------------------------
# Pre-defined experiment templates for the 4 reference powders
# ---------------------------------------------------------------------------

REFERENCE_POWDER_SCANS: dict[str, GridSpec] = {
    "baking_soda_low_freq": GridSpec(
        experiment_id="baking-soda-low-freq-scan",
        powder_name="小苏打",
        powder_id="baking_soda",
        experiment_type="constant_rate",
        dimensions=[
            GridDimension("frequency_hz", [15, 20, 25, 30]),
            GridDimension("duty_permyriad", [1000, 1200]),
            GridDimension("window_position_units", [250]),
        ],
        constraints=[GridConstraint("noise_budget", 90000)],
        duration_s=20.0,
        repeat_count=3,
        tare_between_sets=True,
    ),
    "bentonite_mid_freq": GridSpec(
        experiment_id="bentonite-mid-freq-scan",
        powder_name="膨润土",
        powder_id="bentonite",
        experiment_type="constant_rate",
        dimensions=[
            GridDimension("frequency_hz", [40, 65]),
            GridDimension("duty_permyriad", [2000, 2400, 2800]),
            GridDimension("window_position_units", [250]),
        ],
        constraints=[GridConstraint("noise_budget", 200000)],
        duration_s=20.0,
        repeat_count=3,
        tare_between_sets=True,
    ),
    "slaked_lime_mid_freq": GridSpec(
        experiment_id="slaked-lime-mid-freq-scan",
        powder_name="熟石灰",
        powder_id="slaked_lime",
        experiment_type="constant_rate",
        dimensions=[
            GridDimension("frequency_hz", [40, 55, 65]),
            GridDimension("duty_permyriad", [1600, 2000]),
            GridDimension("window_position_units", [250]),
        ],
        constraints=[GridConstraint("noise_budget", 90000)],
        duration_s=20.0,
        repeat_count=3,
        tare_between_sets=True,
    ),
    "corn_starch_high_freq": GridSpec(
        experiment_id="corn-starch-high-freq-scan",
        powder_name="玉米淀粉",
        powder_id="corn_starch",
        experiment_type="constant_rate",
        dimensions=[
            GridDimension("frequency_hz", [50, 55, 60, 65, 70, 75]),
            GridDimension("duty_permyriad", [2000]),
            GridDimension("window_position_units", [250]),
        ],
        constraints=[GridConstraint("noise_budget", 90000)],
        duration_s=15.0,
        repeat_count=3,
        tare_between_sets=True,
    ),
    "corn_starch_duty_sweep": GridSpec(
        experiment_id="corn-starch-duty-sweep",
        powder_name="玉米淀粉",
        powder_id="corn_starch",
        experiment_type="constant_rate",
        dimensions=[
            GridDimension("frequency_hz", [70]),
            GridDimension("duty_permyriad", [1600, 2400]),
            GridDimension("window_position_units", [250]),
        ],
        constraints=[GridConstraint("noise_budget", 90000)],
        duration_s=15.0,
        repeat_count=3,
        tare_between_sets=True,
    ),
}
