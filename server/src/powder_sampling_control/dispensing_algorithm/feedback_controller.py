"""Target-mass independent feedback control for continuous dispensing.

This module is deliberately separate from ILC and from device adapters. ILC
may provide the initial frequency, duty, and window position, while this
controller uses live mass-motion observations to trim duty and window position
without changing frequency during a task.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import ceil
from time import monotonic


class FeedbackStage(str, Enum):
    COARSE = "coarse"
    FINE = "fine"
    SETTLE = "settle"


@dataclass(frozen=True)
class FeedbackInitialParameters:
    """The run-specific seed, normally selected by L0/ILC or an operator."""

    frequency_hz: int
    duty_permyriad: int
    window_position_units: int


@dataclass(frozen=True)
class FeedbackObservation:
    """One live observation from the balance and motion estimator."""

    mass_mg: float
    predicted_mass_mg: float
    rate_mg_s: float
    predicted_rate_mg_s: float
    acceleration_mg_s2: float = 0.0
    jerk_mg_s3: float = 0.0
    valid: bool = True


@dataclass(frozen=True)
class FeedbackControllerSettings:
    """Conservative defaults; tune these from recorded runs, not in hardware code."""

    low_target_limit_mg: float = 100.0
    high_target_limit_mg: float = 200.0
    low_coarse_fraction: float = 0.70
    default_coarse_fraction: float = 0.75
    high_coarse_fraction: float = 0.80
    coarse_rate_mg_s: float = 10.0
    fine_rate_mg_s: float = 5.0
    min_frequency_hz: int = 10
    max_frequency_hz: int = 80
    min_duty_permyriad: int = 1000
    max_duty_permyriad: int = 5000
    min_window_position_units: int = 100
    max_window_position_units: int = 2000
    duty_deadband_mg_s: float = 0.75
    position_deadband_mg_s: float = 2.0
    duty_gain_per_mg_s: float = 100.0
    duty_integral_gain_per_mg: float = 2.0
    duty_step_per_update: int = 50
    position_step_units: int = 25
    position_update_interval_s: float = 2.0
    duty_update_interval_s: float = 0.5
    position_persistence_samples: int = 4
    position_increases_flow_with_units: bool = True
    acceleration_guard_mg_s2: float = 2.0
    jerk_guard_mg_s3: float = 12.0
    overspeed_multiple: float = 1.5
    maximum_flow_rate_mg_s: float = 30.0
    emergency_duty_step_per_update: int = 200
    emergency_duty_update_interval_s: float = 0.25
    settle_confirmations: int = 2
    allowed_underweight_mg: float = 0.0
    allowed_overweight_mg: float = 0.0
    precision_start_remaining_mg: float = 50.0
    precision_rate_mg_s: float = 8.0
    stop_prediction_horizon_s: float = 1.0
    fixed_tail_mass_mg: float = 2.0
    stop_target_offset_mg: float = 0.0
    predictive_stop_enabled: bool = True
    fast_predictive_stop_enabled: bool = False
    fast_predictive_stop_rate_mg_s: float = 20.0
    fast_predictive_stop_confirmations: int = 1
    projected_safety_stop_enabled: bool = False
    projected_safety_stop_offset_mg: float = 5.0
    position_feedback_enabled: bool = True
    tail_taper_enabled: bool = False
    tail_taper_start_remaining_mg: float = 100.0
    tail_taper_end_remaining_mg: float = 10.0
    tail_duty_reduction_permyriad: int = 200
    tail_window_reduction_units: int = 50
    # ── Hard stop / continue boundaries ──
    force_stop_max_mass_mg: float = float("inf")
    force_continue_min_mass_mg: float = 0.0
    stall_rate_threshold_mg_s: float = 1.0
    stall_duration_s: float = 3.0
    # ── taper stall escape ──
    taper_stall_timeout_s: float = 3.0
    # ── light-powder flow hold / ineffective-duty rollback ──
    flow_hold_enabled: bool = False
    flow_hold_window_s: float = 4.0
    flow_hold_min_gain_mg: float = 5.0
    flow_response_check_s: float = 4.0
    flow_response_min_improvement_mg_s: float = 1.0
    # ── temporary-window recovery for powders that bridge at a fixed opening ──
    stall_recovery_enabled: bool = False
    stall_recovery_observation_window_s: float = 3.0
    stall_recovery_min_gain_mg: float = 2.0
    stall_recovery_rate_threshold_mg_s: float = 1.0
    stall_recovery_resume_rate_mg_s: float = 2.0
    stall_recovery_retry_s: float = 3.0
    stall_recovery_window_step_units: int = 25
    stall_recovery_max_window_position_units: int = 400
    stall_recovery_max_attempts: int = 2
    stall_recovery_disable_remaining_mg: float = 50.0

    def __post_init__(self) -> None:
        if not 0 < self.low_target_limit_mg < self.high_target_limit_mg:
            raise ValueError("target mass limits must be positive and increasing")
        if not 0 < self.low_coarse_fraction < self.default_coarse_fraction < self.high_coarse_fraction < 1:
            raise ValueError("coarse fractions must be increasing and below one")
        if min(self.coarse_rate_mg_s, self.fine_rate_mg_s, self.precision_rate_mg_s) <= 0:
            raise ValueError("rate targets must be positive")
        if not 0 < self.min_frequency_hz <= self.max_frequency_hz:
            raise ValueError("frequency limits are invalid")
        if not 1000 <= self.min_duty_permyriad <= self.max_duty_permyriad:
            raise ValueError("duty limits are invalid")
        if not 0 <= self.min_window_position_units < self.max_window_position_units:
            raise ValueError("window limits are invalid")
        if min(
            self.duty_deadband_mg_s,
            self.position_deadband_mg_s,
            self.duty_gain_per_mg_s,
            self.duty_integral_gain_per_mg,
            self.position_update_interval_s,
            self.duty_update_interval_s,
        ) <= 0:
            raise ValueError("controller gains, deadbands, and intervals must be positive")
        if self.duty_step_per_update < 1 or self.position_step_units < 1:
            raise ValueError("controller steps must be positive")
        if self.position_persistence_samples < 1 or self.settle_confirmations < 1:
            raise ValueError("controller sample counts must be positive")
        if self.overspeed_multiple <= 1:
            raise ValueError("overspeed_multiple must be greater than one")
        if self.maximum_flow_rate_mg_s <= 0:
            raise ValueError("maximum_flow_rate_mg_s must be positive")
        if self.emergency_duty_step_per_update < self.duty_step_per_update:
            raise ValueError("emergency duty step must be at least the normal duty step")
        if not 0 < self.emergency_duty_update_interval_s <= self.duty_update_interval_s:
            raise ValueError("emergency duty interval must be positive and no slower than the normal interval")
        if min(self.allowed_underweight_mg, self.allowed_overweight_mg) < 0:
            raise ValueError("acceptance tolerances must be non-negative")
        # The precision reserve is a mass amount, not a target-size fraction.
        # Large (1–10 g) runs deliberately reserve their final 500 mg for the
        # same closed-loop precision stage, so it may exceed the legacy 200 mg
        # high-target threshold.
        if self.precision_start_remaining_mg <= 0:
            raise ValueError("precision_start_remaining_mg is invalid")
        if self.stop_prediction_horizon_s <= 0 or self.fixed_tail_mass_mg < 0:
            raise ValueError("stop prediction settings are invalid")
        if not 0 <= self.stop_target_offset_mg <= self.allowed_underweight_mg:
            raise ValueError("stop target offset must fit inside the allowed underweight range")
        if self.fast_predictive_stop_rate_mg_s <= 0:
            raise ValueError("fast predictive stop rate must be positive")
        if not 1 <= self.fast_predictive_stop_confirmations <= self.settle_confirmations:
            raise ValueError(
                "fast predictive stop confirmations must be between 1 and settle_confirmations"
            )
        if self.projected_safety_stop_offset_mg < 0 or (
            self.projected_safety_stop_enabled
            and self.projected_safety_stop_offset_mg > self.allowed_overweight_mg
        ):
            raise ValueError(
                "projected safety stop offset must fit inside the allowed overweight range"
            )
        if not 0 <= self.tail_taper_end_remaining_mg < self.tail_taper_start_remaining_mg:
            raise ValueError("tail taper remaining-mass boundaries are invalid")
        if min(self.tail_duty_reduction_permyriad, self.tail_window_reduction_units) < 0:
            raise ValueError("tail taper reductions must be non-negative")
        if self.force_stop_max_mass_mg <= 0:
            raise ValueError("force_stop_max_mass_mg must be positive")
        if self.force_continue_min_mass_mg < 0:
            raise ValueError("force_continue_min_mass_mg must be non-negative")
        if self.force_continue_min_mass_mg >= self.force_stop_max_mass_mg:
            raise ValueError(
                "force_continue_min_mass_mg must be less than force_stop_max_mass_mg"
            )
        if self.stall_rate_threshold_mg_s <= 0 or self.stall_duration_s <= 0:
            raise ValueError("stall parameters must be positive")
        if self.taper_stall_timeout_s <= 0:
            raise ValueError("taper_stall_timeout_s must be positive")
        if min(
            self.flow_hold_window_s,
            self.flow_hold_min_gain_mg,
            self.flow_response_check_s,
        ) <= 0:
            raise ValueError("flow-hold windows and minimum gain must be positive")
        if self.flow_response_min_improvement_mg_s < 0:
            raise ValueError("flow response improvement must not be negative")
        if min(
            self.stall_recovery_observation_window_s,
            self.stall_recovery_rate_threshold_mg_s,
            self.stall_recovery_resume_rate_mg_s,
            self.stall_recovery_retry_s,
        ) <= 0:
            raise ValueError("stall recovery time and rate settings must be positive")
        if self.stall_recovery_min_gain_mg < 0:
            raise ValueError("stall recovery minimum gain must not be negative")
        if self.stall_recovery_resume_rate_mg_s <= self.stall_recovery_rate_threshold_mg_s:
            raise ValueError("stall recovery resume rate must exceed its stall threshold")
        if self.stall_recovery_window_step_units < 1 or self.stall_recovery_max_attempts < 1:
            raise ValueError("stall recovery window step and attempt count must be positive")
        if not (
            self.min_window_position_units
            <= self.stall_recovery_max_window_position_units
            <= self.max_window_position_units
        ):
            raise ValueError("stall recovery maximum window is outside controller limits")
        if self.stall_recovery_disable_remaining_mg < 0:
            raise ValueError("stall recovery tail exclusion must not be negative")


@dataclass(frozen=True)
class FeedbackDecision:
    stage: FeedbackStage
    coarse_threshold_mg: float
    target_rate_mg_s: float
    frequency_hz: int
    duty_before_permyriad: int
    duty_after_permyriad: int
    window_before_units: int
    window_after_units: int
    rate_error_mg_s: float
    control_rate_mg_s: float
    estimated_tail_mg: float
    projected_stop_mass_mg: float
    stop_requested: bool
    duty_changed: bool
    window_changed: bool
    reason: str
    predictive_stop_candidate: bool = False
    stop_confirmation_count: int = 0
    stop_confirmation_required: int = 0
    stall_recovery_active: bool = False
    stall_recovery_attempt: int = 0


class ContinuousFeedbackController:
    """Two-loop controller: fast duty trim and slow window-position trim.

    The frequency in :class:`FeedbackInitialParameters` is intentionally
    immutable. The caller owns physical writes and may reject a decision if a
    device interlock or state-machine rule is not satisfied.
    """

    def __init__(
        self,
        *,
        target_mass_mg: float,
        initial: FeedbackInitialParameters,
        settings: FeedbackControllerSettings | None = None,
    ) -> None:
        if target_mass_mg <= 0:
            raise ValueError("target_mass_mg must be positive")
        self.target_mass_mg = float(target_mass_mg)
        self.settings = settings or FeedbackControllerSettings()
        self._validate_initial(initial)
        if (
            self.settings.stall_recovery_enabled
            and initial.window_position_units
            >= self.settings.stall_recovery_max_window_position_units
        ):
            raise ValueError(
                "stall recovery maximum window must exceed the configured window"
            )
        self.frequency_hz = initial.frequency_hz
        self.duty_permyriad = initial.duty_permyriad
        self.window_position_units = initial.window_position_units
        self._initial_duty_permyriad = initial.duty_permyriad
        self._initial_window_position_units = initial.window_position_units
        self._integral_error_mg = 0.0
        self._last_timestamp_s: float | None = None
        self._last_duty_update_s: float | None = None
        self._last_position_update_s: float | None = None
        self._under_rate_samples = 0
        self._over_rate_samples = 0
        self._settle_samples = 0
        self._last_predictive_stop_candidate = False
        self._stall_start_s: float | None = None
        self._taper_stall_start_s: float | None = None
        self._flow_history: list[tuple[float, float, float]] = []
        self._flow_duty_probe: dict[str, float] | None = None
        self._flow_hold_started_s: float | None = None
        self._stall_recovery_history: list[tuple[float, float]] = []
        self._stall_recovery_active = False
        self._stall_recovery_attempts = 0
        self._stall_recovery_attempt_started_s: float | None = None
        self._stall_recovery_waiting_for_observation = False
        self._stall_recovery_start_mass_mg = 0.0

    def coarse_fraction(self) -> float:
        if self.target_mass_mg <= self.settings.low_target_limit_mg:
            return self.settings.low_coarse_fraction
        if self.target_mass_mg > self.settings.high_target_limit_mg:
            return self.settings.high_coarse_fraction
        return self.settings.default_coarse_fraction

    def coarse_threshold_mg(self) -> float:
        return self.target_mass_mg * self.coarse_fraction()

    def reset(self, initial: FeedbackInitialParameters | None = None) -> None:
        if initial is not None:
            self._validate_initial(initial)
            self.frequency_hz = initial.frequency_hz
            self.duty_permyriad = initial.duty_permyriad
            self.window_position_units = initial.window_position_units
            self._initial_duty_permyriad = initial.duty_permyriad
            self._initial_window_position_units = initial.window_position_units
        self._integral_error_mg = 0.0
        self._last_timestamp_s = None
        self._last_duty_update_s = None
        self._last_position_update_s = None
        self._under_rate_samples = 0
        self._over_rate_samples = 0
        self._settle_samples = 0
        self._last_predictive_stop_candidate = False
        self._stall_start_s = None
        self._taper_stall_start_s = None
        self._flow_history = []
        self._flow_duty_probe = None
        self._flow_hold_started_s = None
        self._stall_recovery_history = []
        self._stall_recovery_active = False
        self._stall_recovery_attempts = 0
        self._stall_recovery_attempt_started_s = None
        self._stall_recovery_waiting_for_observation = False
        self._stall_recovery_start_mass_mg = 0.0

    def step(
        self,
        observation: FeedbackObservation,
        timestamp_s: float | None = None,
        *,
        bypass_rate_control: bool = False,
    ) -> FeedbackDecision:
        self._validate_observation(observation)
        settings = self.settings
        now = monotonic() if timestamp_s is None else float(timestamp_s)
        if self._last_timestamp_s is not None and now <= self._last_timestamp_s:
            raise ValueError("controller timestamps must be strictly increasing")
        dt = 0.0 if self._last_timestamp_s is None else min(2.0, now - self._last_timestamp_s)
        self._last_timestamp_s = now

        threshold = self.coarse_threshold_mg()
        projected_mass = max(observation.mass_mg, observation.predicted_mass_mg)
        control_rate = max(observation.rate_mg_s, observation.predicted_rate_mg_s)
        flow_detected = False
        flow_average_rate = control_rate
        if settings.flow_hold_enabled and observation.valid:
            if self._flow_hold_started_s is None:
                self._flow_hold_started_s = now
            self._flow_history.append((now, observation.mass_mg, control_rate))
            history_horizon = max(
                settings.flow_hold_window_s,
                settings.flow_response_check_s,
            )
            cutoff = now - history_horizon
            self._flow_history = [
                point for point in self._flow_history if point[0] >= cutoff
            ]
            flow_window_cutoff = now - settings.flow_hold_window_s
            flow_window = [
                point for point in self._flow_history if point[0] >= flow_window_cutoff
            ]
            if flow_window:
                flow_gain_mg = observation.mass_mg - flow_window[0][1]
                flow_average_rate = sum(point[2] for point in flow_window) / len(
                    flow_window
                )
                flow_detected = flow_gain_mg >= settings.flow_hold_min_gain_mg
        estimated_tail, projected_stop_mass = self._stop_projection(observation, control_rate)
        self._last_predictive_stop_candidate = False

        prediction_enabled_mass = self.target_mass_mg - self.settings.precision_start_remaining_mg
        projected_safety_stop = (
            settings.projected_safety_stop_enabled
            and observation.valid
            and observation.mass_mg >= prediction_enabled_mass
            and observation.mass_mg >= settings.force_continue_min_mass_mg
            and projected_stop_mass
            >= self.target_mass_mg + settings.projected_safety_stop_offset_mg
        )
        if projected_safety_stop:
            self._last_predictive_stop_candidate = True
            return self._decision(
                FeedbackStage.SETTLE,
                threshold,
                0.0,
                self.duty_permyriad,
                self.window_position_units,
                False,
                False,
                True,
                "projected safety stop: predicted final mass "
                f"{projected_stop_mass:.1f} >= "
                f"{self.target_mass_mg + settings.projected_safety_stop_offset_mg:.0f} mg",
                control_rate_mg_s=control_rate,
                estimated_tail_mg=estimated_tail,
                projected_stop_mass_mg=projected_stop_mass,
                stop_confirmation_required=1,
            )

        # ── force stop: mass already exceeds the hard upper bound ──
        if observation.valid and observation.mass_mg >= settings.force_stop_max_mass_mg:
            return self._decision(
                FeedbackStage.SETTLE,
                threshold,
                0.0,
                self.duty_permyriad,
                self.window_position_units,
                False,
                False,
                True,
                f"force stop: mass {observation.mass_mg:.1f} >= "
                f"{settings.force_stop_max_mass_mg:.0f} mg",
                control_rate_mg_s=control_rate,
                estimated_tail_mg=estimated_tail,
                projected_stop_mass_mg=projected_stop_mass,
            )

        stall_recovery_decision = self._stall_recovery_step(
            observation=observation,
            timestamp_s=now,
            threshold_mg=threshold,
            projected_mass_mg=projected_mass,
            control_rate_mg_s=control_rate,
            estimated_tail_mg=estimated_tail,
            projected_stop_mass_mg=projected_stop_mass,
        )
        if stall_recovery_decision is not None:
            return stall_recovery_decision

        # ── stall detection: rate dead while still below the continue threshold ──
        if (
            observation.valid
            and observation.mass_mg < settings.force_continue_min_mass_mg
            and control_rate < settings.stall_rate_threshold_mg_s
        ):
            if self._stall_start_s is None:
                self._stall_start_s = now
            elif now - self._stall_start_s >= settings.stall_duration_s:
                return self._decision(
                    FeedbackStage.SETTLE,
                    threshold,
                    0.0,
                    self.duty_permyriad,
                    self.window_position_units,
                    False,
                    False,
                    True,
                    f"stall: rate < {settings.stall_rate_threshold_mg_s} mg/s "
                    f"for {settings.stall_duration_s:.0f} s "
                    f"below {settings.force_continue_min_mass_mg:.0f} mg",
                    control_rate_mg_s=control_rate,
                    estimated_tail_mg=estimated_tail,
                    projected_stop_mass_mg=projected_stop_mass,
                )
        else:
            self._stall_start_s = None

        lower_acceptance = self.target_mass_mg - self.settings.allowed_underweight_mg
        prediction_target = self.target_mass_mg - self.settings.stop_target_offset_mg
        predictive_stop = (
            self.settings.predictive_stop_enabled
            and observation.valid
            and observation.mass_mg >= prediction_enabled_mass
            and observation.mass_mg >= self.settings.force_continue_min_mass_mg
            and projected_stop_mass >= prediction_target
        )
        self._last_predictive_stop_candidate = predictive_stop
        stop_confirmation_required = settings.settle_confirmations
        if (
            predictive_stop
            and settings.fast_predictive_stop_enabled
            and control_rate >= settings.fast_predictive_stop_rate_mg_s
        ):
            stop_confirmation_required = settings.fast_predictive_stop_confirmations
        measured_stop = observation.mass_mg >= lower_acceptance
        if predictive_stop or measured_stop:
            self._settle_samples += 1
        else:
            self._settle_samples = 0
        stage = FeedbackStage.SETTLE if self._settle_samples >= stop_confirmation_required else (
            FeedbackStage.COARSE if projected_mass < threshold else FeedbackStage.FINE
        )
        remaining_mass = max(0.0, self.target_mass_mg - projected_mass)
        if stage is FeedbackStage.COARSE:
            target_rate = self.settings.coarse_rate_mg_s
        elif remaining_mass <= self.settings.precision_start_remaining_mg:
            target_rate = self.settings.precision_rate_mg_s
        else:
            target_rate = self.settings.fine_rate_mg_s
        if not bypass_rate_control:
            target_rate = min(target_rate, self.settings.maximum_flow_rate_mg_s)
        duty_before = self.duty_permyriad
        position_before = self.window_position_units
        if stage is FeedbackStage.SETTLE or not observation.valid:
            if stage is FeedbackStage.SETTLE and observation.valid:
                stop_reason = (
                    "predicted tail confirmed inside the acceptance window; "
                    "stop for final stable weighing"
                    if self._last_predictive_stop_candidate
                    else "measured mass confirmed inside the acceptance window; "
                    "stop for final stable weighing"
                )
                return self._decision(
                    stage,
                    threshold,
                    target_rate,
                    duty_before,
                    position_before,
                    False,
                    False,
                    True,
                    stop_reason,
                    control_rate_mg_s=control_rate,
                    estimated_tail_mg=estimated_tail,
                    projected_stop_mass_mg=projected_stop_mass,
                    stop_confirmation_required=stop_confirmation_required,
                )
            else:
                reason = "motion estimate not valid; hold seed parameters"
                return self._decision(
                    stage,
                    threshold,
                    target_rate,
                    duty_before,
                    position_before,
                    False,
                    False,
                    False,
                    reason,
                    control_rate_mg_s=control_rate,
                    estimated_tail_mg=estimated_tail,
                    projected_stop_mass_mg=projected_stop_mass,
                )

        # A fixed-duty pre-feed deliberately runs open-loop.  It still uses
        # the balance for safety/stop checks, but must not be rate-limited or
        # classified as overspeed until precision closed-loop takes over.
        error = 0.0 if bypass_rate_control else target_rate - control_rate
        if dt > 0:
            self._integral_error_mg = max(-20.0, min(20.0, self._integral_error_mg + error * dt))
        absolute_overspeed = (
            not bypass_rate_control
            and control_rate > self.settings.maximum_flow_rate_mg_s
        )
        severe_overspeed = not bypass_rate_control and (
            absolute_overspeed
            or control_rate >= target_rate * self.settings.overspeed_multiple
        )
        if severe_overspeed:
            overspeed = max(0.0, control_rate - target_rate)
            emergency_steps = max(1, ceil(overspeed / 5.0))
            duty_delta = -min(
                self.settings.emergency_duty_step_per_update,
                emergency_steps * self.settings.duty_step_per_update,
            )
            self._over_rate_samples += 1
            self._under_rate_samples = 0
            reason = "predicted flow is above the overspeed guard; reduce duty"
        elif abs(error) <= self.settings.duty_deadband_mg_s:
            duty_delta = 0
            self._under_rate_samples = self._over_rate_samples = 0
            reason = "predicted flow is inside the duty deadband"
        else:
            self._under_rate_samples = self._under_rate_samples + 1 if error > 0 else 0
            self._over_rate_samples = self._over_rate_samples + 1 if error < 0 else 0
            duty_delta = round(
                self.settings.duty_gain_per_mg_s * error
                + self.settings.duty_integral_gain_per_mg * self._integral_error_mg
            )
            duty_delta = max(-self.settings.duty_step_per_update, min(self.settings.duty_step_per_update, duty_delta))
            if error > 0 and observation.acceleration_mg_s2 > self.settings.acceleration_guard_mg_s2:
                duty_delta = min(0, duty_delta)
                reason = "flow is below target but still accelerating; suppress duty increase"
            elif error < 0:
                reason = "predicted flow is above target; reduce duty"
            else:
                reason = "predicted flow is below target; increase duty"

        if settings.flow_hold_enabled and duty_delta > 0:
            probe = self._flow_duty_probe
            if probe is not None:
                probe_elapsed_s = now - probe["started_s"]
                if probe_elapsed_s < settings.flow_response_check_s:
                    duty_delta = 0
                    reason = "waiting for light-powder response before another duty increase"
                else:
                    self._flow_duty_probe = None
                    improved = (
                        flow_average_rate
                        >= probe["baseline_rate_mg_s"]
                        + settings.flow_response_min_improvement_mg_s
                    )
                    if flow_detected and not improved:
                        duty_delta = int(probe["baseline_duty_permyriad"]) - duty_before
                        self._integral_error_mg = min(0.0, self._integral_error_mg)
                        reason = (
                            "duty increase did not improve light-powder flow; "
                            "revert to the previous duty"
                        )
                    elif flow_detected:
                        duty_delta = 0
                        self._integral_error_mg = min(0.0, self._integral_error_mg)
                        reason = "light powder is gaining mass; hold duty"
            elif flow_detected:
                duty_delta = 0
                self._integral_error_mg = min(0.0, self._integral_error_mg)
                reason = "light powder is gaining mass; hold duty"
            elif (
                self._flow_hold_started_s is not None
                and now - self._flow_hold_started_s < settings.flow_hold_window_s
            ):
                duty_delta = 0
                self._integral_error_mg = min(0.0, self._integral_error_mg)
                reason = "observe light-powder mass gain before increasing duty"

        duty_interval = (
            self.settings.emergency_duty_update_interval_s
            if severe_overspeed
            else self.settings.duty_update_interval_s
        )
        if self._last_duty_update_s is None or now - self._last_duty_update_s >= duty_interval:
            duty_before_update = self.duty_permyriad
            self.duty_permyriad = self._bounded_duty(self.duty_permyriad + duty_delta)
            self._last_duty_update_s = now
            if settings.flow_hold_enabled:
                if self.duty_permyriad > duty_before_update:
                    self._flow_duty_probe = {
                        "started_s": now,
                        "baseline_duty_permyriad": float(duty_before_update),
                        "baseline_rate_mg_s": float(flow_average_rate),
                    }
                elif self.duty_permyriad < duty_before_update:
                    self._flow_duty_probe = None

        taper_progress = self._tail_taper_progress(projected_mass)
        if taper_progress > 0:
            # Only skip the taper ceiling after a sustained stall inside the
            # taper band.  This lets the PI loop push duty higher to break
            # through bridging, then re-engages as soon as flow resumes.
            skip_ceiling = False
            if control_rate < settings.stall_rate_threshold_mg_s:
                if self._taper_stall_start_s is None:
                    self._taper_stall_start_s = now
                elif now - self._taper_stall_start_s >= settings.taper_stall_timeout_s:
                    skip_ceiling = True
            else:
                self._taper_stall_start_s = None

            if not skip_ceiling:
                duty_ceiling = round(
                    self._initial_duty_permyriad
                    - settings.tail_duty_reduction_permyriad * taper_progress
                )
                duty_ceiling = self._bounded_duty(duty_ceiling)
                if self.duty_permyriad > duty_ceiling:
                    self.duty_permyriad = max(
                        duty_ceiling,
                        duty_before - settings.duty_step_per_update,
                    )
                    reason += "; remaining mass is small, taper duty for loose-powder tail feed"

        # The position loop is intentionally slower and only trims after a
        # persistent rate error or when the duty loop reaches a hard limit.
        position_due = self._last_position_update_s is None or now - self._last_position_update_s >= self.settings.position_update_interval_s
        persistent_error = max(self._under_rate_samples, self._over_rate_samples) >= self.settings.position_persistence_samples
        duty_at_limit = self.duty_permyriad in (self.settings.min_duty_permyriad, self.settings.max_duty_permyriad)
        position_changed = False
        if (
            settings.position_feedback_enabled
            and position_due
            and persistent_error
            and (duty_at_limit or abs(error) >= self.settings.position_deadband_mg_s)
        ):
            direction = 1 if error > 0 else -1
            if not self.settings.position_increases_flow_with_units:
                direction *= -1
            self.window_position_units = max(
                self.settings.min_window_position_units,
                min(
                    self.settings.max_window_position_units,
                    self.window_position_units + direction * self.settings.position_step_units,
                ),
            )
            position_changed = self.window_position_units != position_before
            self._last_position_update_s = now
            if position_changed:
                reason += "; persistent error, trim window position"
        if settings.position_feedback_enabled and taper_progress > 0 and position_due:
            position_ceiling = round(
                self._initial_window_position_units
                - settings.tail_window_reduction_units * taper_progress
            )
            position_ceiling = max(settings.min_window_position_units, position_ceiling)
            if self.window_position_units > position_ceiling:
                self.window_position_units = max(
                    position_ceiling,
                    position_before - settings.position_step_units,
                )
                position_changed = self.window_position_units != position_before
                self._last_position_update_s = now
                if position_changed:
                    reason += "; taper window for loose-powder tail feed"

        return self._decision(
            stage,
            threshold,
            target_rate,
            duty_before,
            position_before,
            self.duty_permyriad != duty_before,
            position_changed,
            False,
            reason,
            rate_error_mg_s=error,
            control_rate_mg_s=control_rate,
            estimated_tail_mg=estimated_tail,
            projected_stop_mass_mg=projected_stop_mass,
        )

    def _decision(
        self,
        stage,
        threshold,
        target_rate,
        duty_before,
        position_before,
        duty_changed,
        position_changed,
        stop_requested,
        reason,
        *,
        rate_error_mg_s=0.0,
        control_rate_mg_s=0.0,
        estimated_tail_mg=0.0,
        projected_stop_mass_mg=0.0,
        stop_confirmation_required=None,
    ):
        return FeedbackDecision(
            stage=stage,
            coarse_threshold_mg=threshold,
            target_rate_mg_s=target_rate,
            frequency_hz=self.frequency_hz,
            duty_before_permyriad=duty_before,
            duty_after_permyriad=self.duty_permyriad,
            window_before_units=position_before,
            window_after_units=self.window_position_units,
            rate_error_mg_s=rate_error_mg_s,
            control_rate_mg_s=control_rate_mg_s,
            estimated_tail_mg=estimated_tail_mg,
            projected_stop_mass_mg=projected_stop_mass_mg,
            stop_requested=stop_requested,
            duty_changed=duty_changed,
            window_changed=position_changed,
            reason=reason,
            predictive_stop_candidate=self._last_predictive_stop_candidate,
            stop_confirmation_count=self._settle_samples,
            stop_confirmation_required=(
                self.settings.settle_confirmations
                if stop_confirmation_required is None
                else stop_confirmation_required
            ),
            stall_recovery_active=self._stall_recovery_active,
            stall_recovery_attempt=self._stall_recovery_attempts,
        )

    def _validate_initial(self, initial: FeedbackInitialParameters) -> None:
        settings = self.settings
        if not settings.min_frequency_hz <= initial.frequency_hz <= settings.max_frequency_hz:
            raise ValueError("initial frequency is outside controller limits")
        if not settings.min_duty_permyriad <= initial.duty_permyriad <= settings.max_duty_permyriad:
            raise ValueError("initial duty is outside controller limits")
        if not settings.min_window_position_units <= initial.window_position_units <= settings.max_window_position_units:
            raise ValueError("initial window position is outside controller limits")

    @staticmethod
    def _validate_observation(observation: FeedbackObservation) -> None:
        for name in ("mass_mg", "predicted_mass_mg", "rate_mg_s", "predicted_rate_mg_s"):
            if getattr(observation, name) < 0:
                raise ValueError(f"{name} must be non-negative")

    def _bounded_duty(self, value: int) -> int:
        return max(self.settings.min_duty_permyriad, min(self.settings.max_duty_permyriad, int(value)))

    def _stall_recovery_stage_and_rate(
        self,
        projected_mass_mg: float,
        threshold_mg: float,
    ) -> tuple[FeedbackStage, float]:
        stage = (
            FeedbackStage.COARSE
            if projected_mass_mg < threshold_mg
            else FeedbackStage.FINE
        )
        remaining_mass = max(0.0, self.target_mass_mg - projected_mass_mg)
        if stage is FeedbackStage.COARSE:
            target_rate = self.settings.coarse_rate_mg_s
        elif remaining_mass <= self.settings.precision_start_remaining_mg:
            target_rate = self.settings.precision_rate_mg_s
        else:
            target_rate = self.settings.fine_rate_mg_s
        return stage, min(target_rate, self.settings.maximum_flow_rate_mg_s)

    def _stall_recovery_step(
        self,
        *,
        observation: FeedbackObservation,
        timestamp_s: float,
        threshold_mg: float,
        projected_mass_mg: float,
        control_rate_mg_s: float,
        estimated_tail_mg: float,
        projected_stop_mass_mg: float,
    ) -> FeedbackDecision | None:
        """Temporarily open a bridged powder head, then return to its seed window."""
        settings = self.settings
        if not settings.stall_recovery_enabled:
            return None
        if not observation.valid:
            self._stall_recovery_history = []
            return None

        self._stall_recovery_history.append((timestamp_s, observation.mass_mg))
        cutoff_s = timestamp_s - settings.stall_recovery_observation_window_s
        while (
            len(self._stall_recovery_history) >= 2
            and self._stall_recovery_history[1][0] <= cutoff_s
        ):
            self._stall_recovery_history.pop(0)

        stage, target_rate = self._stall_recovery_stage_and_rate(
            projected_mass_mg,
            threshold_mg,
        )
        remaining_mass = self.target_mass_mg - observation.mass_mg
        tail_recovery_blocked = (
            remaining_mass <= settings.stall_recovery_disable_remaining_mg
        )

        if self._stall_recovery_active:
            duty_before = self.duty_permyriad
            window_before = self.window_position_units
            recovered = (
                control_rate_mg_s >= settings.stall_recovery_resume_rate_mg_s
                or observation.mass_mg - self._stall_recovery_start_mass_mg
                >= settings.stall_recovery_min_gain_mg
            )
            if recovered or tail_recovery_blocked:
                self.duty_permyriad = min(
                    self.duty_permyriad,
                    self._initial_duty_permyriad,
                )
                self.window_position_units = self._initial_window_position_units
                self._stall_recovery_active = False
                self._stall_recovery_attempt_started_s = None
                self._stall_recovery_waiting_for_observation = False
                self._stall_recovery_history = [(timestamp_s, observation.mass_mg)]
                self._last_duty_update_s = timestamp_s
                self._last_position_update_s = timestamp_s
                reason = (
                    "stall recovery flow resumed; restore the configured window"
                    if recovered
                    else "stall recovery reached the protected final "
                    f"{settings.stall_recovery_disable_remaining_mg:g} mg; "
                    "restore the configured window"
                )
                decision = self._decision(
                    stage,
                    threshold_mg,
                    target_rate,
                    duty_before,
                    window_before,
                    self.duty_permyriad != duty_before,
                    self.window_position_units != window_before,
                    False,
                    reason,
                    control_rate_mg_s=control_rate_mg_s,
                    estimated_tail_mg=estimated_tail_mg,
                    projected_stop_mass_mg=projected_stop_mass_mg,
                )
                # Attempts are scoped to one continuous stall episode.  Once
                # flow resumes, a later independent stall must receive a fresh
                # recovery budget instead of inheriting exhausted attempts.
                self._stall_recovery_attempts = 0
                return decision

            if self._stall_recovery_waiting_for_observation:
                self._stall_recovery_waiting_for_observation = False
                self._stall_recovery_attempt_started_s = timestamp_s
                return self._decision(
                    stage,
                    threshold_mg,
                    target_rate,
                    duty_before,
                    window_before,
                    False,
                    False,
                    False,
                    "stall recovery active; begin observing the temporary window",
                    control_rate_mg_s=control_rate_mg_s,
                    estimated_tail_mg=estimated_tail_mg,
                    projected_stop_mass_mg=projected_stop_mass_mg,
                )

            attempt_elapsed_s = timestamp_s - (
                self._stall_recovery_attempt_started_s or timestamp_s
            )
            if attempt_elapsed_s >= settings.stall_recovery_retry_s:
                if self._stall_recovery_attempts >= settings.stall_recovery_max_attempts:
                    self._stall_recovery_active = False
                    return self._decision(
                        FeedbackStage.SETTLE,
                        threshold_mg,
                        0.0,
                        duty_before,
                        window_before,
                        False,
                        False,
                        True,
                        "stall recovery exhausted after "
                        f"{self._stall_recovery_attempts} temporary-window attempts",
                        control_rate_mg_s=control_rate_mg_s,
                        estimated_tail_mg=estimated_tail_mg,
                        projected_stop_mass_mg=projected_stop_mass_mg,
                    )
                self._stall_recovery_attempts += 1
                requested_window = min(
                    self._initial_window_position_units
                    + settings.stall_recovery_window_step_units
                    * self._stall_recovery_attempts,
                    settings.stall_recovery_max_window_position_units,
                )
                self.window_position_units = requested_window
                self._stall_recovery_attempt_started_s = timestamp_s
                self._stall_recovery_waiting_for_observation = True
                self._stall_recovery_start_mass_mg = observation.mass_mg
                self._last_position_update_s = timestamp_s
                return self._decision(
                    stage,
                    threshold_mg,
                    target_rate,
                    duty_before,
                    window_before,
                    False,
                    self.window_position_units != window_before,
                    False,
                    "stall recovery attempt "
                    f"{self._stall_recovery_attempts}: keep duty frozen and open window to "
                    f"{self.window_position_units}",
                    control_rate_mg_s=control_rate_mg_s,
                    estimated_tail_mg=estimated_tail_mg,
                    projected_stop_mass_mg=projected_stop_mass_mg,
                )

            return self._decision(
                stage,
                threshold_mg,
                target_rate,
                duty_before,
                window_before,
                False,
                False,
                False,
                "stall recovery active; hold duty and temporary window",
                control_rate_mg_s=control_rate_mg_s,
                estimated_tail_mg=estimated_tail_mg,
                projected_stop_mass_mg=projected_stop_mass_mg,
            )

        if tail_recovery_blocked or len(self._stall_recovery_history) < 2:
            return None
        observed_span_s = (
            timestamp_s - self._stall_recovery_history[0][0]
        )
        if observed_span_s < settings.stall_recovery_observation_window_s:
            return None
        observed_gain_mg = (
            observation.mass_mg - self._stall_recovery_history[0][1]
        )
        stalled = (
            observed_gain_mg <= settings.stall_recovery_min_gain_mg
            and control_rate_mg_s < settings.stall_recovery_rate_threshold_mg_s
        )
        if not stalled:
            return None

        duty_before = self.duty_permyriad
        window_before = self.window_position_units
        if self._stall_recovery_attempts >= settings.stall_recovery_max_attempts:
            return self._decision(
                FeedbackStage.SETTLE,
                threshold_mg,
                0.0,
                duty_before,
                window_before,
                False,
                False,
                True,
                "stall recovery exhausted after "
                f"{self._stall_recovery_attempts} temporary-window attempts",
                control_rate_mg_s=control_rate_mg_s,
                estimated_tail_mg=estimated_tail_mg,
                projected_stop_mass_mg=projected_stop_mass_mg,
            )

        self._stall_recovery_active = True
        self._stall_recovery_attempts += 1
        self._stall_recovery_attempt_started_s = timestamp_s
        self._stall_recovery_waiting_for_observation = True
        self._stall_recovery_start_mass_mg = observation.mass_mg
        self.duty_permyriad = min(
            self.duty_permyriad,
            self._initial_duty_permyriad,
        )
        self.window_position_units = min(
            self._initial_window_position_units
            + settings.stall_recovery_window_step_units
            * self._stall_recovery_attempts,
            settings.stall_recovery_max_window_position_units,
        )
        self._integral_error_mg = 0.0
        self._settle_samples = 0
        self._last_duty_update_s = timestamp_s
        self._last_position_update_s = timestamp_s
        return self._decision(
            stage,
            threshold_mg,
            target_rate,
            duty_before,
            window_before,
            self.duty_permyriad != duty_before,
            self.window_position_units != window_before,
            False,
            "stall detected: freeze duty and start temporary-window recovery "
            f"attempt {self._stall_recovery_attempts} at {self.window_position_units}",
            control_rate_mg_s=control_rate_mg_s,
            estimated_tail_mg=estimated_tail_mg,
            projected_stop_mass_mg=projected_stop_mass_mg,
        )

    def _tail_taper_progress(self, projected_mass_mg: float) -> float:
        settings = self.settings
        if not settings.tail_taper_enabled:
            return 0.0
        remaining = max(0.0, self.target_mass_mg - projected_mass_mg)
        if remaining >= settings.tail_taper_start_remaining_mg:
            return 0.0
        if remaining <= settings.tail_taper_end_remaining_mg:
            return 1.0
        span = settings.tail_taper_start_remaining_mg - settings.tail_taper_end_remaining_mg
        return (settings.tail_taper_start_remaining_mg - remaining) / span

    def _stop_projection(self, observation: FeedbackObservation, control_rate_mg_s: float) -> tuple[float, float]:
        """Project mass after command, balance and falling-powder delays."""
        settings = self.settings
        horizon = settings.stop_prediction_horizon_s
        positive_acceleration = max(0.0, observation.acceleration_mg_s2)
        dynamic_tail = (
            control_rate_mg_s * horizon
            + 0.5 * positive_acceleration * horizon * horizon
        )
        observer_tail = max(0.0, observation.predicted_mass_mg - observation.mass_mg)
        estimated_tail = max(dynamic_tail, observer_tail) + settings.fixed_tail_mass_mg
        return estimated_tail, observation.mass_mg + estimated_tail
