"""Continuous no-PID taper planner for the 500 mg dispensing tail.

The planner assumes vibration stays continuous. It does not chase flow rate with
PID. Instead it uses fixed stage parameters and predictive stop rules based on
measured mass, filtered mass, and short-horizon mass projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ContinuousTaperStage(str, Enum):
    COARSE = "coarse"
    TAPER = "taper"
    PRECISION = "precision"
    SETTLE = "settle"
    REVIEW = "review"


@dataclass(frozen=True)
class ContinuousAction:
    window_position_units: int
    frequency_hz: int
    duty_permyriad: int


@dataclass(frozen=True)
class ContinuousTaperConfig:
    target_mass_mg: float = 500.0
    hard_overweight_mg: float = 510.0
    coarse_end_mg: float = 420.0
    stop_raw_mg: float = 498.0
    stop_filtered_mg: float = 495.0
    stop_prediction_mg: float = 500.0
    min_raw_for_predictive_stop_mg: float = 485.0
    prediction_horizon_s: float = 0.75
    fixed_tail_mg: float = 2.0
    coarse: ContinuousAction = ContinuousAction(200, 80, 2000)
    # Last-80 mg mode deliberately lowers all actuation values once and then
    # holds them. It is not a rate controller; it is a low-energy trickle mode.
    taper: ContinuousAction = ContinuousAction(100, 65, 1600)
    precision: ContinuousAction = ContinuousAction(100, 65, 1600)


@dataclass(frozen=True)
class ContinuousTaperDecision:
    stage: ContinuousTaperStage
    command: str
    action: ContinuousAction | None
    raw_mass_mg: float
    filtered_mass_mg: float
    predicted_mass_mg: float
    remaining_predicted_mg: float
    reason: str


class ContinuousTaperPlanner:
    """Fixed-stage continuous planner with predictive tail stop."""

    def __init__(self, config: ContinuousTaperConfig | None = None) -> None:
        self.config = config or ContinuousTaperConfig()

    def decide(
        self,
        *,
        raw_mass_mg: float,
        filtered_mass_mg: float | None = None,
        rate_mg_s: float = 0.0,
        acceleration_mg_s2: float = 0.0,
        predicted_mass_mg: float | None = None,
        current_window_position_units: int | None = None,
        current_frequency_hz: int | None = None,
        current_duty_permyriad: int | None = None,
    ) -> ContinuousTaperDecision:
        if raw_mass_mg < 0:
            raise ValueError("raw_mass_mg must be non-negative")
        if filtered_mass_mg is not None and filtered_mass_mg < 0:
            raise ValueError("filtered_mass_mg must be non-negative")
        if rate_mg_s < 0:
            raise ValueError("rate_mg_s must be non-negative")

        cfg = self.config
        filtered = raw_mass_mg if filtered_mass_mg is None else filtered_mass_mg
        predicted = self._predict_mass(
            raw_mass_mg=raw_mass_mg,
            filtered_mass_mg=filtered,
            rate_mg_s=rate_mg_s,
            acceleration_mg_s2=acceleration_mg_s2,
            predicted_mass_mg=predicted_mass_mg,
        )

        if raw_mass_mg >= cfg.hard_overweight_mg:
            return self._stop(
                ContinuousTaperStage.REVIEW,
                raw_mass_mg,
                filtered,
                predicted,
                "hard overweight boundary reached",
            )
        if raw_mass_mg >= cfg.stop_raw_mg:
            return self._stop(
                ContinuousTaperStage.SETTLE,
                raw_mass_mg,
                filtered,
                predicted,
                "raw mass reached the continuous stop threshold",
            )
        if filtered >= cfg.stop_filtered_mg and raw_mass_mg >= cfg.min_raw_for_predictive_stop_mg:
            return self._stop(
                ContinuousTaperStage.SETTLE,
                raw_mass_mg,
                filtered,
                predicted,
                "filtered mass reached the continuous stop threshold",
            )
        if raw_mass_mg >= cfg.min_raw_for_predictive_stop_mg and predicted >= cfg.stop_prediction_mg:
            return self._stop(
                ContinuousTaperStage.SETTLE,
                raw_mass_mg,
                filtered,
                predicted,
                "predicted mass reaches target after tail and balance delay",
            )

        control_mass = max(raw_mass_mg, filtered)
        if control_mass < cfg.coarse_end_mg:
            stage = ContinuousTaperStage.COARSE
            action = cfg.coarse
            reason = "below coarse end; keep the stable initial feed"
        elif control_mass < cfg.target_mass_mg:
            stage = ContinuousTaperStage.TAPER
            action = cfg.taper
            reason = "last 80 mg; switch once to fixed low-energy continuous tail feed"
        else:
            stage = ContinuousTaperStage.PRECISION
            action = cfg.precision
            reason = "target range reached but stop guards have not voted yet"

        command = "KEEP"
        if (
            current_window_position_units is not None
            and current_frequency_hz is not None
            and current_duty_permyriad is not None
            and (
                current_window_position_units != action.window_position_units
                or current_frequency_hz != action.frequency_hz
                or current_duty_permyriad != action.duty_permyriad
            )
        ):
            command = "UPDATE"
        return ContinuousTaperDecision(
            stage=stage,
            command=command,
            action=action,
            raw_mass_mg=raw_mass_mg,
            filtered_mass_mg=filtered,
            predicted_mass_mg=predicted,
            remaining_predicted_mg=cfg.target_mass_mg - predicted,
            reason=reason,
        )

    def _predict_mass(
        self,
        *,
        raw_mass_mg: float,
        filtered_mass_mg: float,
        rate_mg_s: float,
        acceleration_mg_s2: float,
        predicted_mass_mg: float | None,
    ) -> float:
        cfg = self.config
        positive_acceleration = max(0.0, acceleration_mg_s2)
        projected = (
            filtered_mass_mg
            + rate_mg_s * cfg.prediction_horizon_s
            + 0.5 * positive_acceleration * cfg.prediction_horizon_s * cfg.prediction_horizon_s
            + cfg.fixed_tail_mg
        )
        if predicted_mass_mg is not None:
            projected = max(projected, predicted_mass_mg)
        return max(raw_mass_mg, filtered_mass_mg, projected)

    def _stop(
        self,
        stage: ContinuousTaperStage,
        raw_mass_mg: float,
        filtered_mass_mg: float,
        predicted_mass_mg: float,
        reason: str,
    ) -> ContinuousTaperDecision:
        return ContinuousTaperDecision(
            stage=stage,
            command="STOP",
            action=None,
            raw_mass_mg=raw_mass_mg,
            filtered_mass_mg=filtered_mass_mg,
            predicted_mass_mg=predicted_mass_mg,
            remaining_predicted_mg=self.config.target_mass_mg - predicted_mass_mg,
            reason=reason,
        )
