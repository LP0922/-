"""Constrained, task-to-task ILC for the coarse-stage duration only."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ILCSettings:
    learning_gain: float = 0.3
    max_relative_step: float = 0.05
    minimum_scale: float = 0.7
    maximum_scale: float = 1.3
    apply_to_hardware: bool = False


@dataclass(frozen=True)
class LearningRecord:
    target_mass_mg: float
    final_mass_mg: float
    coarse_duration_ms: int
    communication_ok: bool
    stable: bool
    accepted: bool
    alarm_free: bool
    manual_intervention: bool = False


@dataclass(frozen=True)
class ILCRecommendation:
    current_scale: float
    proposed_scale: float
    eligible: bool
    applied: bool
    reason: str


class ConstrainedILC:
    """Updates only after a valid task; default operation is shadow mode."""

    def __init__(self, settings: ILCSettings | None = None) -> None:
        self.settings = settings or ILCSettings()

    def recommend(self, record: LearningRecord, current_scale: float) -> ILCRecommendation:
        if not self._eligible(record):
            return ILCRecommendation(current_scale, current_scale, False, False, "task is not eligible for ILC")
        if record.coarse_duration_ms <= 0:
            return ILCRecommendation(current_scale, current_scale, False, False, "coarse duration is unavailable")

        error_mg = record.target_mass_mg - record.final_mass_mg
        observed_gain = record.final_mass_mg / (record.coarse_duration_ms / 1000.0)
        if observed_gain <= 0:
            return ILCRecommendation(current_scale, current_scale, False, False, "observed gain is not positive")
        raw_delta = self.settings.learning_gain * error_mg / observed_gain
        relative_delta = raw_delta / (record.coarse_duration_ms / 1000.0)
        bounded_delta = min(max(relative_delta, -self.settings.max_relative_step), self.settings.max_relative_step)
        proposed = min(
            max(current_scale * (1.0 + bounded_delta), self.settings.minimum_scale),
            self.settings.maximum_scale,
        )
        return ILCRecommendation(
            current_scale=current_scale,
            proposed_scale=proposed,
            eligible=True,
            applied=self.settings.apply_to_hardware,
            reason="bounded shadow recommendation" if not self.settings.apply_to_hardware else "bounded recommendation enabled",
        )

    @staticmethod
    def _eligible(record: LearningRecord) -> bool:
        return (
            record.communication_ok
            and record.stable
            and record.accepted
            and record.alarm_free
            and not record.manual_intervention
        )
