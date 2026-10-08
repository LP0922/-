"""Window-position feedforward plus PID trim for powder dispensing.

This planner is intentionally command-only: it does not open serial ports or
drive hardware. It turns a stable mass observation and optional recent flow-rate
estimate into the next LA10 action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .models import FeedAction


class WindowPidStage(str, Enum):
    COARSE = "coarse"
    SLOW = "slow"
    FINE = "fine"
    RECOVERY = "recovery"
    SETTLE = "settle"


@dataclass(frozen=True)
class WindowRatePoint:
    window_position_units: int
    reference_mg_per_s: float


@dataclass(frozen=True)
class PidGains:
    kp_window_per_mg_s: float = 3.0
    ki_window_per_mg: float = 0.25
    kd_window_per_mg_s2: float = 0.8


@dataclass(frozen=True)
class StageWindowConfig:
    base_window_position_units: int
    target_rate_mg_s: float
    reserve_after_action_mg: float
    max_expected_mass_mg: float
    min_duration_ms: int
    max_duration_ms: int


@dataclass(frozen=True)
class WindowPidConfig:
    target_mass_mg: float = 500.0
    allowed_overweight_mg: float = 10.0
    frequency_hz: int = 80
    duty_permyriad: int = 2000
    min_window_position_units: int = 100
    max_window_position_units: int = 650
    pid_adjust_limit_units: int = 80
    output_window_step_units: int = 10
    tail_seconds: float = 0.20
    max_tail_mg: float = 6.0
    no_flow_rate_mg_s: float = 1.0
    no_flow_timeout_s: float = 1.5
    weak_flow_rate_mg_s: float = 3.0
    pid_gains: PidGains = field(default_factory=PidGains)
    rate_points: tuple[WindowRatePoint, ...] = (
        WindowRatePoint(100, 6.0),
        WindowRatePoint(200, 27.0),
        WindowRatePoint(400, 42.0),
        WindowRatePoint(650, 55.0),
    )
    coarse_entry_margin_mg: float = 160.0
    fine_entry_margin_mg: float = 35.0
    coarse: StageWindowConfig = StageWindowConfig(
        base_window_position_units=650,
        target_rate_mg_s=50.0,
        reserve_after_action_mg=160.0,
        max_expected_mass_mg=220.0,
        min_duration_ms=1500,
        max_duration_ms=4500,
    )
    slow: StageWindowConfig = StageWindowConfig(
        base_window_position_units=200,
        target_rate_mg_s=22.0,
        reserve_after_action_mg=35.0,
        max_expected_mass_mg=80.0,
        min_duration_ms=900,
        max_duration_ms=4000,
    )
    fine: StageWindowConfig = StageWindowConfig(
        base_window_position_units=100,
        target_rate_mg_s=6.0,
        reserve_after_action_mg=0.0,
        max_expected_mass_mg=15.0,
        min_duration_ms=500,
        max_duration_ms=2500,
    )
    recovery_duration_ms: int = 600
    recovery_window_position_units: int = 650
    recovery_duty_permyriad: int = 2600


@dataclass(frozen=True)
class WindowPidState:
    integral_error: float = 0.0
    previous_error_mg_s: float = 0.0
    no_flow_seconds: float = 0.0


@dataclass(frozen=True)
class WindowPidDecision:
    stage: WindowPidStage
    action: FeedAction | None
    remaining_mg: float
    predicted_tail_mg: float
    target_rate_mg_s: float
    observed_rate_mg_s: float | None
    expected_mass_mg: float
    stop_mass_mg: float
    pid_adjust_units: int
    next_state: WindowPidState
    reason: str


class WindowPidPlanner:
    """Plan a window-position command with feedforward and PID correction."""

    def __init__(self, config: WindowPidConfig | None = None) -> None:
        self.config = config or WindowPidConfig()

    def next_decision(
        self,
        *,
        current_mass_mg: float,
        observed_rate_mg_s: float | None = None,
        state: WindowPidState | None = None,
        dt_s: float = 1.0,
    ) -> WindowPidDecision:
        if current_mass_mg < 0:
            raise ValueError("current_mass_mg must be non-negative")
        if observed_rate_mg_s is not None and observed_rate_mg_s < 0:
            raise ValueError("observed_rate_mg_s must be non-negative")
        if dt_s <= 0:
            raise ValueError("dt_s must be positive")

        state = state or WindowPidState()
        cfg = self.config
        predicted_tail_mg = self._predict_tail(observed_rate_mg_s)
        remaining_mg = cfg.target_mass_mg - current_mass_mg - predicted_tail_mg
        hard_limit_mg = cfg.target_mass_mg + cfg.allowed_overweight_mg

        if current_mass_mg + predicted_tail_mg >= hard_limit_mg:
            return self._stop_decision(
                current_mass_mg,
                remaining_mg,
                predicted_tail_mg,
                observed_rate_mg_s,
                state,
                "hard overweight boundary reached",
            )
        if remaining_mg <= 0:
            return self._stop_decision(
                current_mass_mg,
                remaining_mg,
                predicted_tail_mg,
                observed_rate_mg_s,
                state,
                "target reached by measured mass plus predicted tail",
            )

        no_flow_seconds = self._updated_no_flow_seconds(observed_rate_mg_s, state.no_flow_seconds, dt_s)
        if (
            observed_rate_mg_s is not None
            and no_flow_seconds >= cfg.no_flow_timeout_s
            and remaining_mg > cfg.fine_entry_margin_mg
        ):
            next_state = WindowPidState(
                integral_error=0.0,
                previous_error_mg_s=0.0,
                no_flow_seconds=no_flow_seconds,
            )
            action = FeedAction(
                cfg.recovery_window_position_units,
                cfg.frequency_hz,
                cfg.recovery_duty_permyriad,
                cfg.recovery_duration_ms,
            )
            return WindowPidDecision(
                stage=WindowPidStage.RECOVERY,
                action=self._bound_action(action),
                remaining_mg=remaining_mg,
                predicted_tail_mg=predicted_tail_mg,
                target_rate_mg_s=0.0,
                observed_rate_mg_s=observed_rate_mg_s,
                expected_mass_mg=0.0,
                stop_mass_mg=current_mass_mg,
                pid_adjust_units=0,
                next_state=next_state,
                reason="flow rate stayed near zero; use a short high-window recovery pulse",
            )

        stage, stage_cfg = self._stage_for_remaining(remaining_mg)
        expected_mass_mg = self._expected_mass(remaining_mg, stage_cfg)
        pid_adjust_units, next_state = self._pid_adjust(
            target_rate_mg_s=stage_cfg.target_rate_mg_s,
            observed_rate_mg_s=observed_rate_mg_s,
            state=state,
            dt_s=dt_s,
            no_flow_seconds=no_flow_seconds,
        )
        feedforward_window = self._feedforward_window(stage_cfg)
        window = self._round_window(feedforward_window + pid_adjust_units)
        duration_ms = round(expected_mass_mg / stage_cfg.target_rate_mg_s * 1000.0)
        duration_ms = min(max(duration_ms, stage_cfg.min_duration_ms), stage_cfg.max_duration_ms)
        action = self._bound_action(
            FeedAction(
                window,
                cfg.frequency_hz,
                cfg.duty_permyriad,
                duration_ms,
            )
        )
        stop_mass_mg = min(current_mass_mg + expected_mass_mg, cfg.target_mass_mg)
        reason = "feedforward window from remaining mass"
        if observed_rate_mg_s is not None:
            reason += "; PID trims window from recent flow-rate error"
        return WindowPidDecision(
            stage=stage,
            action=action,
            remaining_mg=remaining_mg,
            predicted_tail_mg=predicted_tail_mg,
            target_rate_mg_s=stage_cfg.target_rate_mg_s,
            observed_rate_mg_s=observed_rate_mg_s,
            expected_mass_mg=expected_mass_mg,
            stop_mass_mg=stop_mass_mg,
            pid_adjust_units=pid_adjust_units,
            next_state=next_state,
            reason=reason,
        )

    def _stage_for_remaining(self, remaining_mg: float) -> tuple[WindowPidStage, StageWindowConfig]:
        cfg = self.config
        if remaining_mg > cfg.coarse_entry_margin_mg:
            return WindowPidStage.COARSE, cfg.coarse
        if remaining_mg > cfg.fine_entry_margin_mg:
            return WindowPidStage.SLOW, cfg.slow
        return WindowPidStage.FINE, cfg.fine

    def _expected_mass(self, remaining_mg: float, stage_cfg: StageWindowConfig) -> float:
        planned = remaining_mg - stage_cfg.reserve_after_action_mg
        if stage_cfg.reserve_after_action_mg == 0.0:
            planned = remaining_mg * 0.5
        return max(0.0, min(planned, stage_cfg.max_expected_mass_mg))

    def _pid_adjust(
        self,
        *,
        target_rate_mg_s: float,
        observed_rate_mg_s: float | None,
        state: WindowPidState,
        dt_s: float,
        no_flow_seconds: float,
    ) -> tuple[int, WindowPidState]:
        if observed_rate_mg_s is None:
            return 0, WindowPidState(state.integral_error, state.previous_error_mg_s, no_flow_seconds)

        cfg = self.config
        gains = cfg.pid_gains
        error = target_rate_mg_s - observed_rate_mg_s
        integral = state.integral_error + error * dt_s
        integral = min(max(integral, -120.0), 120.0)
        derivative = (error - state.previous_error_mg_s) / dt_s
        raw_adjust = (
            gains.kp_window_per_mg_s * error
            + gains.ki_window_per_mg * integral
            + gains.kd_window_per_mg_s2 * derivative
        )
        limited = min(max(raw_adjust, -cfg.pid_adjust_limit_units), cfg.pid_adjust_limit_units)
        rounded = round(limited / cfg.output_window_step_units) * cfg.output_window_step_units
        next_state = WindowPidState(
            integral_error=integral,
            previous_error_mg_s=error,
            no_flow_seconds=no_flow_seconds,
        )
        return int(rounded), next_state

    def _predict_tail(self, observed_rate_mg_s: float | None) -> float:
        if observed_rate_mg_s is None:
            return 0.0
        return min(max(observed_rate_mg_s * self.config.tail_seconds, 0.0), self.config.max_tail_mg)

    def _feedforward_window(self, stage_cfg: StageWindowConfig) -> int:
        if not self.config.rate_points:
            return stage_cfg.base_window_position_units
        closest = min(
            self.config.rate_points,
            key=lambda point: abs(point.reference_mg_per_s - stage_cfg.target_rate_mg_s),
        )
        return closest.window_position_units

    def _updated_no_flow_seconds(self, observed_rate_mg_s: float | None, previous: float, dt_s: float) -> float:
        if observed_rate_mg_s is None:
            return 0.0
        if observed_rate_mg_s < self.config.no_flow_rate_mg_s:
            return previous + dt_s
        if observed_rate_mg_s >= self.config.weak_flow_rate_mg_s:
            return 0.0
        return previous

    def _round_window(self, window_position_units: int) -> int:
        step = self.config.output_window_step_units
        return int(round(window_position_units / step) * step)

    def _bound_action(self, action: FeedAction) -> FeedAction:
        cfg = self.config
        window = min(max(action.window_position_units, cfg.min_window_position_units), cfg.max_window_position_units)
        return FeedAction(window, action.frequency_hz, action.duty_permyriad, action.duration_ms)

    def _stop_decision(
        self,
        current_mass_mg: float,
        remaining_mg: float,
        predicted_tail_mg: float,
        observed_rate_mg_s: float | None,
        state: WindowPidState,
        reason: str,
    ) -> WindowPidDecision:
        return WindowPidDecision(
            stage=WindowPidStage.SETTLE,
            action=None,
            remaining_mg=remaining_mg,
            predicted_tail_mg=predicted_tail_mg,
            target_rate_mg_s=0.0,
            observed_rate_mg_s=observed_rate_mg_s,
            expected_mass_mg=0.0,
            stop_mass_mg=current_mass_mg,
            pid_adjust_units=0,
            next_state=state,
            reason=reason,
        )
