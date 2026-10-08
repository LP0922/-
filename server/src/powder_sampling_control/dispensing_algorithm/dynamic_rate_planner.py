"""Acceleration-aware frequency planner for continuous powder dispensing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RateStage(str, Enum):
    COARSE = "COARSE"
    SLOW = "SLOW"
    FINE = "FINE"


@dataclass(frozen=True)
class RatePlannerSettings:
    coarse_end_mg: float = 420.0
    slow_end_mg: float = 470.0
    coarse_target_mg_s: float = 10.0
    slow_target_mg_s: float = 7.0
    fine_target_mg_s: float = 5.0
    min_frequency_hz: int = 10
    max_frequency_hz: int = 80
    tracking_deadband_mg_s: float = 0.75
    overspeed_multiple: float = 2.0
    frequency_step_hz: int = 1
    acceleration_guard_mg_s2: float = 2.0
    jerk_guard_mg_s3: float = 12.0
    post_adjustment_settle_s: float = 0.75
    severe_error_mg_s: float = 8.0
    medium_error_mg_s: float = 4.0
    small_error_mg_s: float = 2.0
    severe_update_interval_s: float = 0.5
    medium_update_interval_s: float = 1.0
    small_update_interval_s: float = 1.5
    near_target_update_interval_s: float = 2.5

    def __post_init__(self) -> None:
        if not 0 < self.coarse_end_mg < self.slow_end_mg:
            raise ValueError("mass stage boundaries must be positive and increasing")
        if min(self.coarse_target_mg_s, self.slow_target_mg_s, self.fine_target_mg_s) <= 0:
            raise ValueError("rate targets must be positive")
        if not 0 < self.min_frequency_hz <= self.max_frequency_hz:
            raise ValueError("frequency limits are invalid")
        if self.tracking_deadband_mg_s < 0:
            raise ValueError("controller deadband is invalid")
        if self.overspeed_multiple <= 1:
            raise ValueError("overspeed_multiple must be greater than one")
        if self.frequency_step_hz != 1:
            raise ValueError("continuous controller frequency_step_hz must be exactly 1")
        if min(
            self.acceleration_guard_mg_s2,
            self.jerk_guard_mg_s3,
            self.post_adjustment_settle_s,
        ) <= 0:
            raise ValueError("motion guards must be positive")
        if not 0 < self.small_error_mg_s < self.medium_error_mg_s < self.severe_error_mg_s:
            raise ValueError("rate-error thresholds must be positive and increasing")
        if not (
            0 < self.severe_update_interval_s
            <= self.medium_update_interval_s
            <= self.small_update_interval_s
            <= self.near_target_update_interval_s
        ):
            raise ValueError("frequency-update intervals must be positive and increasing")


@dataclass(frozen=True)
class RatePlanDecision:
    stage: RateStage
    target_rate_mg_s: float
    measured_rate_mg_s: float
    predicted_rate_mg_s: float
    acceleration_mg_s2: float
    jerk_mg_s3: float
    control_mass_mg: float
    current_frequency_hz: int
    next_frequency_hz: int
    rate_error_mg_s: float
    next_update_interval_s: float
    reason: str

    @property
    def frequency_changed(self) -> bool:
        return self.next_frequency_hz != self.current_frequency_hz


class DynamicRatePlanner:
    """Select a one-hertz frequency step from estimated powder-flow state."""

    def __init__(self, settings: RatePlannerSettings | None = None) -> None:
        self.settings = settings or RatePlannerSettings()

    def stage_for_mass(self, filtered_mass_mg: float) -> RateStage:
        if filtered_mass_mg < 0:
            raise ValueError("filtered_mass_mg must be non-negative")
        if filtered_mass_mg < self.settings.coarse_end_mg:
            return RateStage.COARSE
        if filtered_mass_mg < self.settings.slow_end_mg:
            return RateStage.SLOW
        return RateStage.FINE

    def update_interval_for_error(self, rate_error_mg_s: float) -> float:
        magnitude = abs(rate_error_mg_s)
        settings = self.settings
        if magnitude >= settings.severe_error_mg_s:
            return settings.severe_update_interval_s
        if magnitude >= settings.medium_error_mg_s:
            return settings.medium_update_interval_s
        if magnitude >= settings.small_error_mg_s:
            return settings.small_update_interval_s
        return settings.near_target_update_interval_s

    def decide(
        self,
        *,
        filtered_mass_mg: float,
        measured_rate_mg_s: float,
        current_frequency_hz: int,
        acceleration_mg_s2: float = 0.0,
        jerk_mg_s3: float = 0.0,
        predicted_mass_mg: float | None = None,
        predicted_rate_mg_s: float | None = None,
        seconds_since_frequency_change: float | None = None,
        rate_valid: bool = True,
    ) -> RatePlanDecision:
        if measured_rate_mg_s < 0:
            raise ValueError("measured_rate_mg_s must be non-negative")
        settings = self.settings
        if not settings.min_frequency_hz <= current_frequency_hz <= settings.max_frequency_hz:
            raise ValueError("current_frequency_hz is outside planner limits")

        predicted_rate = (
            measured_rate_mg_s
            if predicted_rate_mg_s is None
            else max(0.0, predicted_rate_mg_s)
        )
        control_mass = max(
            filtered_mass_mg,
            filtered_mass_mg if predicted_mass_mg is None else predicted_mass_mg,
        )
        stage = self.stage_for_mass(control_mass)
        target = {
            RateStage.COARSE: settings.coarse_target_mg_s,
            RateStage.SLOW: settings.slow_target_mg_s,
            RateStage.FINE: settings.fine_target_mg_s,
        }[stage]
        predictive_error = target - predicted_rate
        update_interval_s = self.update_interval_for_error(predictive_error)

        def decision(
            next_frequency_hz: int,
            reason: str,
            *,
            interval_s: float | None = None,
        ) -> RatePlanDecision:
            return RatePlanDecision(
                stage=stage,
                target_rate_mg_s=target,
                measured_rate_mg_s=measured_rate_mg_s,
                predicted_rate_mg_s=predicted_rate,
                acceleration_mg_s2=acceleration_mg_s2,
                jerk_mg_s3=jerk_mg_s3,
                control_mass_mg=control_mass,
                current_frequency_hz=current_frequency_hz,
                next_frequency_hz=next_frequency_hz,
                rate_error_mg_s=predictive_error,
                next_update_interval_s=update_interval_s if interval_s is None else interval_s,
                reason=reason,
            )

        if not rate_valid:
            return decision(
                current_frequency_hz,
                "waiting for the mass-motion estimate to become valid",
                interval_s=settings.near_target_update_interval_s,
            )

        frequency_down = max(
            settings.min_frequency_hz,
            current_frequency_hz - settings.frequency_step_hz,
        )
        frequency_up = min(
            settings.max_frequency_hz,
            current_frequency_hz + settings.frequency_step_hz,
        )
        emergency_overspeed = (
            measured_rate_mg_s > target * settings.overspeed_multiple
            or predicted_rate > target * settings.overspeed_multiple
        )
        if emergency_overspeed:
            reason = "predicted flow exceeds twice the target; reducing frequency by 1 Hz"
            if frequency_down == current_frequency_hz:
                reason = "minimum frequency reached during predictive overspeed correction"
            return decision(frequency_down, reason)

        if (
            seconds_since_frequency_change is not None
            and seconds_since_frequency_change < settings.post_adjustment_settle_s
            and abs(jerk_mg_s3) >= settings.jerk_guard_mg_s3
        ):
            return decision(
                current_frequency_hz,
                "flow transient after the last frequency step; holding for observation",
            )

        # The coarse target is a minimum-throughput request.  Do not trim a
        # moderate coarse overspeed unless acceleration predicts the 2x guard.
        if stage is RateStage.COARSE and measured_rate_mg_s >= target:
            return decision(
                current_frequency_hz,
                "coarse flow has reached its minimum target; holding frequency",
            )

        if predicted_rate > target + settings.tracking_deadband_mg_s:
            reason = "predicted flow is above target; reducing frequency by 1 Hz"
            if acceleration_mg_s2 > settings.acceleration_guard_mg_s2:
                reason = "flow is above target and still accelerating; reducing frequency by 1 Hz"
            if frequency_down == current_frequency_hz:
                reason = "minimum frequency reached while correcting predicted flow"
            return decision(frequency_down, reason)

        if abs(predictive_error) <= settings.tracking_deadband_mg_s:
            return decision(
                current_frequency_hz,
                "predicted flow is inside the tracking deadband",
            )

        if predictive_error > 0:
            if acceleration_mg_s2 >= settings.acceleration_guard_mg_s2:
                return decision(
                    current_frequency_hz,
                    "flow is still accelerating toward target; suppressing an unnecessary increase",
                )
            if jerk_mg_s3 >= settings.jerk_guard_mg_s3:
                return decision(
                    current_frequency_hz,
                    "positive flow jerk detected; holding frequency until the transient settles",
                )
            reason = "predicted flow is below target; increasing frequency by 1 Hz"
            if frequency_up == current_frequency_hz:
                reason = "maximum frequency reached while correcting predicted flow"
            return decision(frequency_up, reason)

        reason = "predicted flow is above target; reducing frequency by 1 Hz"
        if frequency_down == current_frequency_hz:
            reason = "minimum frequency reached while correcting predicted flow"
        return decision(frequency_down, reason)
