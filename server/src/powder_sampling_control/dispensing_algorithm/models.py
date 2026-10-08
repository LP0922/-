"""Typed contracts, product limits, calibration, and L0 lookup for the
powder-dispensing algorithm.

Consolidates the former standalone modules:

    models.py             core dataclasses (DispenseStage, FeedAction, ...)
    product_requirements.py   central product limits (target/acceptance)
    calibration.py        LocalYieldEstimator from approved samples
    l0_repository.py      versioned L0 profile lookup + interpolation

These objects express a command plan only. Hardware actuation remains owned by
the task state machine and device adapters.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REQUIREMENTS_PATH = PROJECT_ROOT / "config" / "product_requirements.json"


class DispenseStage(str, Enum):
    COARSE = "coarse"
    SLOW = "slow"
    FINE = "fine"
    SETTLE = "settle"


@dataclass(frozen=True)
class FeedAction:
    """One bounded LA10 window/vibration command."""

    window_position_units: int
    frequency_hz: int
    duty_permyriad: int
    duration_ms: int


@dataclass(frozen=True)
class ActuationLimits:
    """Approved operating envelope for the current feeder and powder head."""

    min_window_position_units: int = 350
    max_window_position_units: int = 800
    min_frequency_hz: int = 10
    max_frequency_hz: int = 80
    min_duty_permyriad: int = 1000
    max_duty_permyriad: int = 5000
    noise_budget_hz_permyriad: int = 90000
    min_duration_ms: int = 80
    max_duration_ms: int = 8000


@dataclass(frozen=True)
class StageParameters:
    """L0 action shape and reference yield for one dispensing stage."""

    window_position_units: int
    frequency_hz: int
    duty_permyriad: int
    reference_mg_per_s: float
    min_duration_ms: int
    max_duration_ms: int


@dataclass(frozen=True)
class L0Profile:
    """A calibrated, versioned starting point for one target-mass bin."""

    profile_id: str
    powder_type: str
    powder_batch: str
    feeder_head: str
    recipe_version: str
    target_mass_mg: float
    slow_entry_margin_mg: float
    fine_entry_margin_mg: float
    hard_overweight_margin_mg: float
    coarse: StageParameters
    slow: StageParameters
    fine: StageParameters


@dataclass(frozen=True)
class Recipe:
    """Task-specific acceptance and safety requirements."""

    recipe_id: str
    target_mass_mg: float
    allowed_overweight_mg: float
    forbid_underweight: bool = True


@dataclass(frozen=True)
class MassObservation:
    """A stable mass value supplied by the weighing layer."""

    mass_mg: float
    stable: bool
    communication_ok: bool


@dataclass(frozen=True)
class PlanDecision:
    """The next action proposal and its safety-relevant reasoning fields."""

    stage: DispenseStage
    action: FeedAction | None
    remaining_predicted_mg: float
    expected_mass_mg: float
    reason: str


# ── product requirements (was product_requirements.py) ──────────────────────


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


# ── local yield estimation (was calibration.py) ─────────────────────────────


@dataclass(frozen=True)
class CalibrationSample:
    stage: DispenseStage
    action: FeedAction
    stable_mass_delta_mg: float
    communication_ok: bool
    stable: bool
    alarm_free: bool

    @property
    def eligible(self) -> bool:
        return (
            self.action.duration_ms > 0
            and self.stable_mass_delta_mg > 0
            and self.communication_ok
            and self.stable
            and self.alarm_free
        )

    @property
    def mg_per_s(self) -> float:
        return self.stable_mass_delta_mg / (self.action.duration_ms / 1000.0)


class LocalYieldEstimator:
    """Inverse-distance estimate; deliberately simpler than GPR for phase one."""

    def __init__(self, samples: list[CalibrationSample] | None = None) -> None:
        self._samples = list(samples or [])

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def add(self, sample: CalibrationSample) -> None:
        self._samples.append(sample)

    @classmethod
    def from_directory(cls, path: str | Path) -> "LocalYieldEstimator":
        """Load completed physical calibration records written by the collection script."""
        samples = []
        for record_path in Path(path).glob("*.json"):
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
                if record.get("result") != "completed" or not record.get("approved_for_planner", True):
                    continue
                action = record["action"]
                mass_after = record["mass_after"]
                samples.append(
                    CalibrationSample(
                        stage=DispenseStage(record.get("stage", DispenseStage.COARSE.value)),
                        action=FeedAction(
                            window_position_units=int(action["window_position_units"]),
                            frequency_hz=int(action["frequency_hz"]),
                            duty_permyriad=int(action["duty_permyriad"]),
                            duration_ms=round(float(record["actual_duration_s"]) * 1000),
                        ),
                        stable_mass_delta_mg=float(record["stable_mass_delta_mg"]),
                        communication_ok=True,
                        stable=bool(mass_after["stable"]),
                        alarm_free=not bool(record.get("alarm_trace")),
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return cls(samples)

    def estimate_mg_per_s(
        self,
        *,
        stage: DispenseStage,
        action: FeedAction,
        fallback_mg_per_s: float,
    ) -> float:
        eligible = [sample for sample in self._samples if sample.stage == stage and sample.eligible]
        if not eligible:
            return fallback_mg_per_s

        weighted_total = 0.0
        weight_sum = 0.0
        for sample in eligible:
            distance = (
                abs(sample.action.window_position_units - action.window_position_units) / 200.0
                + abs(sample.action.frequency_hz - action.frequency_hz) / 20.0
                + abs(sample.action.duty_permyriad - action.duty_permyriad) / 1000.0
            )
            weight = 1.0 / (0.25 + distance)
            weighted_total += sample.mg_per_s * weight
            weight_sum += weight
        return weighted_total / weight_sum


# ── L0 repository (was l0_repository.py) ─────────────────────────────────────


def _stage_from_mapping(data: dict[str, Any]) -> StageParameters:
    return StageParameters(
        window_position_units=int(data["window_position_units"]),
        frequency_hz=int(data["frequency_hz"]),
        duty_permyriad=int(data["duty_permyriad"]),
        reference_mg_per_s=float(data["reference_mg_per_s"]),
        min_duration_ms=int(data["min_duration_ms"]),
        max_duration_ms=int(data["max_duration_ms"]),
    )


def _profile_from_mapping(data: dict[str, Any]) -> L0Profile:
    return L0Profile(
        profile_id=str(data["profile_id"]),
        powder_type=str(data["powder_type"]),
        powder_batch=str(data["powder_batch"]),
        feeder_head=str(data["feeder_head"]),
        recipe_version=str(data["recipe_version"]),
        target_mass_mg=float(data["target_mass_mg"]),
        slow_entry_margin_mg=float(data["slow_entry_margin_mg"]),
        fine_entry_margin_mg=float(data["fine_entry_margin_mg"]),
        hard_overweight_margin_mg=float(data["hard_overweight_margin_mg"]),
        coarse=_stage_from_mapping(data["coarse"]),
        slow=_stage_from_mapping(data["slow"]),
        fine=_stage_from_mapping(data["fine"]),
    )


def _interpolate_stage(low: StageParameters, high: StageParameters, ratio: float) -> StageParameters:
    def blend(name: str) -> float:
        return getattr(low, name) + (getattr(high, name) - getattr(low, name)) * ratio

    return StageParameters(
        window_position_units=round(blend("window_position_units")),
        frequency_hz=round(blend("frequency_hz")),
        duty_permyriad=round(blend("duty_permyriad")),
        reference_mg_per_s=blend("reference_mg_per_s"),
        min_duration_ms=round(blend("min_duration_ms")),
        max_duration_ms=round(blend("max_duration_ms")),
    )


class L0Repository:
    """Selects an approved L0 row, interpolating only between matching rows."""

    def __init__(self, profiles: list[L0Profile]) -> None:
        if not profiles:
            raise ValueError("at least one L0 profile is required")
        self._profiles = profiles

    @classmethod
    def from_json(cls, path: str | Path) -> "L0Repository":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([_profile_from_mapping(item) for item in data["profiles"]])

    def select(
        self,
        *,
        powder_type: str,
        powder_batch: str,
        feeder_head: str,
        recipe_version: str,
        target_mass_mg: float,
    ) -> L0Profile:
        candidates = [
            profile
            for profile in self._profiles
            if (
                profile.powder_type == powder_type
                and profile.powder_batch == powder_batch
                and profile.feeder_head == feeder_head
                and profile.recipe_version == recipe_version
            )
        ]
        if not candidates:
            raise LookupError("no approved L0 profile matches powder, head, batch, and recipe version")
        candidates.sort(key=lambda profile: profile.target_mass_mg)
        if target_mass_mg <= candidates[0].target_mass_mg:
            return candidates[0]
        if target_mass_mg >= candidates[-1].target_mass_mg:
            return candidates[-1]
        high_index = next(index for index, item in enumerate(candidates) if item.target_mass_mg >= target_mass_mg)
        low, high = candidates[high_index - 1], candidates[high_index]
        ratio = (target_mass_mg - low.target_mass_mg) / (high.target_mass_mg - low.target_mass_mg)
        return replace(
            low,
            profile_id=f"interpolated:{low.profile_id}:{high.profile_id}:{target_mass_mg:g}mg",
            target_mass_mg=target_mass_mg,
            slow_entry_margin_mg=low.slow_entry_margin_mg + (high.slow_entry_margin_mg - low.slow_entry_margin_mg) * ratio,
            fine_entry_margin_mg=low.fine_entry_margin_mg + (high.fine_entry_margin_mg - low.fine_entry_margin_mg) * ratio,
            hard_overweight_margin_mg=low.hard_overweight_margin_mg + (high.hard_overweight_margin_mg - low.hard_overweight_margin_mg) * ratio,
            coarse=_interpolate_stage(low.coarse, high.coarse, ratio),
            slow=_interpolate_stage(low.slow, high.slow, ratio),
            fine=_interpolate_stage(low.fine, high.fine, ratio),
        )
