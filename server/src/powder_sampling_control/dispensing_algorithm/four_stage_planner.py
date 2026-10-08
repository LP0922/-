"""Four-stage, model-assisted command planning for LA10 vibration feeding."""

from __future__ import annotations

from dataclasses import dataclass

from .calibration import LocalYieldEstimator
from .models import (
    ActuationLimits,
    DispenseStage,
    FeedAction,
    L0Profile,
    MassObservation,
    PlanDecision,
    Recipe,
    StageParameters,
)


class ActuationPolicy:
    """Applies hard bounds and the frequency/duty noise budget."""

    def __init__(self, limits: ActuationLimits | None = None) -> None:
        self.limits = limits or ActuationLimits()

    def bound(self, action: FeedAction) -> FeedAction:
        limits = self.limits
        position = min(max(action.window_position_units, limits.min_window_position_units), limits.max_window_position_units)
        frequency = min(max(action.frequency_hz, limits.min_frequency_hz), limits.max_frequency_hz)
        noise_limited_duty = limits.noise_budget_hz_permyriad // frequency
        duty = min(action.duty_permyriad, limits.max_duty_permyriad, noise_limited_duty)
        duty = max(duty, limits.min_duty_permyriad)
        duration = min(max(action.duration_ms, limits.min_duration_ms), limits.max_duration_ms)
        return FeedAction(position, frequency, duty, duration)


@dataclass(frozen=True)
class PlannerContext:
    recipe: Recipe
    profile: L0Profile
    observation: MassObservation
    predicted_tail_mg: float = 0.0
    ilc_coarse_duration_scale: float = 1.0


class FourStagePlanner:
    """Chooses the next bounded action; it never commands hardware directly."""

    def __init__(
        self,
        *,
        policy: ActuationPolicy | None = None,
        yield_estimator: LocalYieldEstimator | None = None,
    ) -> None:
        self._policy = policy or ActuationPolicy()
        self._yield_estimator = yield_estimator or LocalYieldEstimator()

    def next_decision(self, context: PlannerContext) -> PlanDecision:
        if not context.observation.communication_ok or not context.observation.stable:
            return PlanDecision(DispenseStage.SETTLE, None, 0.0, 0.0, "waiting for a valid stable weighing observation")

        remaining = context.recipe.target_mass_mg - context.observation.mass_mg - context.predicted_tail_mg
        hard_limit = context.recipe.target_mass_mg + min(
            context.recipe.allowed_overweight_mg,
            context.profile.hard_overweight_margin_mg,
        )
        if context.observation.mass_mg + context.predicted_tail_mg >= hard_limit:
            return PlanDecision(DispenseStage.SETTLE, None, remaining, 0.0, "hard overweight boundary reached")
        if remaining <= 0:
            return PlanDecision(DispenseStage.SETTLE, None, remaining, 0.0, "target reached; wait for final stability")

        if remaining > context.profile.slow_entry_margin_mg:
            expected = remaining - context.profile.slow_entry_margin_mg
            action = self._action_for_mass(
                DispenseStage.COARSE,
                context.profile.coarse,
                expected,
                duration_scale=context.ilc_coarse_duration_scale,
            )
            return PlanDecision(DispenseStage.COARSE, action, remaining, expected, "coarse feed preserves slow-stage reserve")

        if remaining > context.profile.fine_entry_margin_mg:
            expected = min(remaining - context.profile.fine_entry_margin_mg, self._pulse_mass(context.profile.slow))
            action = self._action_for_mass(DispenseStage.SLOW, context.profile.slow, expected)
            return PlanDecision(DispenseStage.SLOW, action, remaining, expected, "slow feed preserves fine-stage reserve")

        # Fine pulses deliberately target at most half the predicted remaining mass.
        expected = min(remaining * 0.5, self._pulse_mass(context.profile.fine))
        action = self._action_for_mass(DispenseStage.FINE, context.profile.fine, expected)
        return PlanDecision(DispenseStage.FINE, action, remaining, expected, "conservative fine pulse before re-weighing")

    def _action_for_mass(
        self,
        stage: DispenseStage,
        parameters: StageParameters,
        expected_mass_mg: float,
        *,
        duration_scale: float = 1.0,
    ) -> FeedAction:
        seed = FeedAction(
            parameters.window_position_units,
            parameters.frequency_hz,
            parameters.duty_permyriad,
            parameters.min_duration_ms,
        )
        bounded_seed = self._policy.bound(seed)
        rate = self._yield_estimator.estimate_mg_per_s(
            stage=stage,
            action=bounded_seed,
            fallback_mg_per_s=parameters.reference_mg_per_s,
        )
        if rate <= 0:
            raise ValueError("mass-yield estimate must be positive")
        duration_ms = round(expected_mass_mg / rate * 1000.0 * duration_scale)
        duration_ms = min(max(duration_ms, parameters.min_duration_ms), parameters.max_duration_ms)
        return self._policy.bound(
            FeedAction(
                bounded_seed.window_position_units,
                bounded_seed.frequency_hz,
                bounded_seed.duty_permyriad,
                duration_ms,
            )
        )

    @staticmethod
    def _pulse_mass(parameters: StageParameters) -> float:
        return parameters.reference_mg_per_s * parameters.max_duration_ms / 1000.0
