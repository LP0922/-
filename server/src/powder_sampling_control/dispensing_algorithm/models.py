"""Typed contracts for the powder-dispensing algorithm.

These objects express a command plan only. Hardware actuation remains owned by
the task state machine and device adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
