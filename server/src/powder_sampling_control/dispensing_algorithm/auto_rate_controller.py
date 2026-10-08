"""Auto-tuning constant-rate controller with four-stage state machine.

Unlike :class:`ConstantRateController` which uses a fixed three-tier PI strategy,
this controller actively searches for the minimum viable parameter combination
(window → frequency → duty) and then locks into PI fine-tuning on duty only.

Stage overview
--------------
1. **INITIAL_LOCATE** — open window stepwise until powder starts flowing
2. **FREQ_SEARCH**    — sweep frequency up to find the critical threshold
3. **DUTY_LOCK**      — PI on duty only; frequency and window are frozen
4. **STEADY_MONITOR** — detect drift and escalate through the fallback chain

Escalation chain (rate too low)
    duty↑ → 45% → freq↑ → 80Hz → window↑ (reset freq+duty) → retry
Escalation chain (rate too high)
    duty↓ → 12% → freq↓ → 10Hz → window↓ (reset freq+duty) → retry
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from time import monotonic
from typing import Optional


class AutoRateStage(IntEnum):
    INITIAL_LOCATE = 1
    FREQ_SEARCH = 2
    DUTY_LOCK = 3
    STEADY_MONITOR = 4


@dataclass(frozen=True)
class AutoRateDecision:
    """One control decision from the auto-tuning controller."""

    target_rate_mg_s: float
    control_rate_mg_s: float
    rate_error_mg_s: float
    frequency_before_hz: int
    frequency_after_hz: int
    duty_before_permyriad: int
    duty_after_permyriad: int
    window_before_units: int
    window_after_units: int
    freq_changed: bool
    duty_changed: bool
    window_changed: bool
    locked: bool
    stage: int
    reason: str


@dataclass
class AutoRateSettings:
    """Tunable parameters for the auto-tuning controller."""

    # ── Hardware bounds ──
    min_frequency_hz: int = 10
    max_frequency_hz: int = 80
    min_duty_permyriad: int = 1000
    max_duty_permyriad: int = 5000
    min_window_units: int = 100
    max_window_units: int = 600

    # ── Stage 1: window location ──
    locate_start_window: int = 150
    locate_start_freq_hz: int = 40
    locate_start_duty: int = 2000
    locate_window_step: int = 50
    locate_eval_interval_s: float = 1.0
    locate_settle_s: float = 4.0
    locate_rate_threshold_ratio: float = 0.7  # rate > target * 0.7 → flow established
    locate_flow_persistence_s: float = 3.0     # flow must stay above threshold this long

    # ── Stage 2: frequency search ──
    freq_search_duty: int = 2000
    freq_search_step_hz: int = 2
    freq_search_eval_interval_s: float = 1.0
    freq_search_settle_s: float = 3.0
    freq_search_overshoot_ratio: float = 1.3    # rate > target * 1.3 → freq found
    freq_search_severe_overshoot_ratio: float = 2.0  # rate > target * 2 → back off
    freq_search_zero_streak_limit: int = 4       # consecutive zero-flow → back to stage 1
    freq_search_worse_streak_limit: int = 2      # consecutive rate drops → freq overshot, go stage 3

    # ── Stage 3: duty PI lock ──
    duty_pi_gain_per_mg_s: float = 60.0
    duty_pi_step: int = 10
    duty_pi_interval_s: float = 1.5
    duty_lock_range_mg_s: float = 2.0
    duty_lock_duration_s: float = 2.0  # continuous lock before -> stage 4
    duty_lock_dead_end_drift: int = 300  # duty +3% without lock → escalate
    duty_lock_dead_end_timeout_s: float = 15.0  # stuck in stage 3 too long → escalate

    # ── Stage 4: steady monitor ──
    # Escalation uses relative drift from the duty at which we entered stage 4,
    # NOT hard thresholds.  This adapts to different powder/target combinations
    # where the achievable duty range varies.
    monitor_duty_drift: int = 500        # ±5% duty drift from entry → escalate
    monitor_rate_low_ratio: float = 0.7
    monitor_rate_high_ratio: float = 1.3
    monitor_persistence_s: float = 5.0
    monitor_rate_deviation_timeout_s: float = 20.0  # rate off-target too long → escalate

    # ── Safety ──
    overspeed_multiple: float = 1.5
    maximum_flow_rate_mg_s: float = 100.0
    emergency_duty_step: int = 50
    emergency_duty_interval_s: float = 0.5


class AutoRateController:
    """Automatically find and maintain a target powder flow rate.

    Usage is identical to :class:`ConstantRateController`::

        ctrl = AutoRateController(target_rate_mg_s=10.0)
        for mass, time in readings:
            decision = ctrl.step(observation, timestamp_s=time)
            if decision.freq_changed or decision.duty_changed:
                update_vibration(decision.frequency_after_hz, decision.duty_after_permyriad)
            if decision.window_changed:
                move_window(decision.window_after_units)
    """

    def __init__(
        self,
        target_rate_mg_s: float,
        settings: AutoRateSettings | None = None,
    ) -> None:
        if target_rate_mg_s <= 0:
            raise ValueError("target_rate_mg_s must be positive")
        self.target_rate_mg_s = float(target_rate_mg_s)
        self.settings = settings or AutoRateSettings()
        s = self.settings

        # Parameter state — start from locate defaults
        self.frequency_hz = s.locate_start_freq_hz
        self.duty_permyriad = s.locate_start_duty
        self.window_position_units = s.locate_start_window

        # Stage state
        self._stage = AutoRateStage.INITIAL_LOCATE
        self._stage_entered_at: float | None = monotonic()
        self._last_decision_time: float | None = None
        self._last_timestamp_s: float | None = None

        # Rate buffer for evaluation windows
        self._rate_buffer: deque[tuple[float, float]] = deque()  # (timestamp, rate)

        # Stage 1 persistence tracking
        self._locate_flow_since: float | None = None
        self._locate_settle_cuts: int = 0

        # Stage 2 zero-flow streak
        self._freq_search_zero_streak: int = 0

        # Stage 2 non-monotonic detection: track best rate+freq seen so far
        self._freq_search_best_rate: float = -1.0
        self._freq_search_best_freq: int = 0
        self._freq_search_worse_streak: int = 0

        # Stage 3 PI state
        self._duty_integral_error_mg: float = 0.0
        self._locked_since: float | None = None
        self._locked = False
        self._stage3_entry_duty: int = 0

        # Stage 4: duty at which we entered stage 4 (for drift-based escalation)
        self._stage4_entry_duty: int = 0

        # Stage 4 persistence counters
        self._high_duty_since: float | None = None
        self._low_duty_since: float | None = None
        self._low_rate_since: float | None = None
        self._high_rate_since: float | None = None
        self._rate_below_target_since: float | None = None  # time-based escalation

        # Emergency (overspeed) tracking
        self._last_duty_update_s: float | None = None

        # Track previous state for decision diff
        self._freq_before: int = self.frequency_hz
        self._duty_before: int = self.duty_permyriad
        self._window_before: int = self.window_position_units

        # Accumulated reason fragments
        self._pending_reason: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def stage(self) -> AutoRateStage:
        return self._stage

    @property
    def locked(self) -> bool:
        return self._locked

    def reset(self) -> None:
        """Reset all state to initial conditions."""
        s = self.settings
        self.frequency_hz = s.locate_start_freq_hz
        self.duty_permyriad = s.locate_start_duty
        self.window_position_units = s.locate_start_window
        self._stage = AutoRateStage.INITIAL_LOCATE
        self._stage_entered_at = None
        self._last_decision_time = None
        self._last_timestamp_s = None
        self._rate_buffer.clear()
        self._locate_flow_since = None
        self._locate_settle_cuts = 0
        self._freq_search_zero_streak = 0
        self._freq_search_best_rate = -1.0
        self._freq_search_best_freq = 0
        self._freq_search_worse_streak = 0
        self._duty_integral_error_mg = 0.0
        self._locked_since = None
        self._locked = False
        self._stage3_entry_duty = 0
        self._stage4_entry_duty = 0
        self._high_duty_since = None
        self._low_duty_since = None
        self._low_rate_since = None
        self._high_rate_since = None
        self._rate_below_target_since = None
        self._last_duty_update_s = None
        self._freq_before = self.frequency_hz
        self._duty_before = self.duty_permyriad
        self._window_before = self.window_position_units
        self._pending_reason = ""

    def step(
        self,
        observation,
        timestamp_s: float | None = None,
    ):
        """Evaluate one observation and return a control decision.

        Parameters
        ----------
        observation:
            Must have attributes ``rate_mg_s``, ``predicted_rate_mg_s``,
            ``acceleration_mg_s2``, ``valid`` (bool).
        timestamp_s:
            Monotonic timestamp.  Defaults to ``time.monotonic()``.
        """
        now = monotonic() if timestamp_s is None else float(timestamp_s)
        if self._last_timestamp_s is not None and now <= self._last_timestamp_s:
            raise ValueError("controller timestamps must be strictly increasing")
        self._last_timestamp_s = now

        s = self.settings

        # Snapshot current state for diff
        self._freq_before = self.frequency_hz
        self._duty_before = self.duty_permyriad
        self._window_before = self.window_position_units
        self._pending_reason = ""

        # Control rate: blend filtered + predicted
        control_rate = (
            0.8 * observation.rate_mg_s + 0.2 * observation.predicted_rate_mg_s
        )
        error = self.target_rate_mg_s - control_rate

        # ── Not valid → hold ──
        if not observation.valid:
            return self._make_decision(control_rate, error, "motion estimate not valid; hold")

        # ── Buffer valid samples ──
        self._rate_buffer.append((now, control_rate))
        # Trim old samples (> 10s)
        cutoff = now - 10.0
        while self._rate_buffer and self._rate_buffer[0][0] < cutoff:
            self._rate_buffer.popleft()

        # ── Overspeed emergency (always active regardless of stage) ──
        # In stage 4 the system is locked; use a 2 s sliding average to
        # distinguish genuine overspeed from isolated spikes.  Single-point
        # noise is left to the normal duty PI.
        if self._stage == AutoRateStage.STEADY_MONITOR:
            avg_2s = self._recent_avg_rate(now, lookback_s=2.0)
            absolute_overspeed = control_rate > s.maximum_flow_rate_mg_s
            severe_overspeed = (
                absolute_overspeed
                or (
                    control_rate >= self.target_rate_mg_s * s.overspeed_multiple
                    and avg_2s is not None
                    and avg_2s >= self.target_rate_mg_s * s.overspeed_multiple
                )
            )
        else:
            absolute_overspeed = control_rate > s.maximum_flow_rate_mg_s
            severe_overspeed = (
                absolute_overspeed
                or control_rate >= self.target_rate_mg_s * s.overspeed_multiple
            )
        if severe_overspeed:
            return self._handle_overspeed(control_rate, error, now)

        # ── Delegate to current stage ──
        if self._stage == AutoRateStage.INITIAL_LOCATE:
            return self._eval_initial_locate(control_rate, error, now)
        elif self._stage == AutoRateStage.FREQ_SEARCH:
            return self._eval_freq_search(control_rate, error, now)
        elif self._stage == AutoRateStage.DUTY_LOCK:
            return self._eval_duty_lock(control_rate, error, now)
        else:  # STEADY_MONITOR
            return self._eval_steady_monitor(control_rate, error, now)

    # ------------------------------------------------------------------
    # Stage evaluation
    # ------------------------------------------------------------------

    def _eval_initial_locate(self, control_rate: float, error: float, now: float):
        """Stage 1: open window stepwise until powder flows persistently."""
        s = self.settings

        if self._stage_entered_at is None:
            self._stage_entered_at = now
            self._locate_flow_since = None
            self._locate_settle_cuts = 0

        # Wait for settle after last change
        if self._last_decision_time is not None:
            elapsed = now - self._last_decision_time
            if elapsed < s.locate_settle_s:
                return self._make_decision(
                    control_rate, error,
                    f"stage 1: settling ({elapsed:.1f}/{s.locate_settle_s:.0f}s)",
                )

        # Evaluate recent average rate
        avg_rate = self._recent_avg_rate(now, lookback_s=s.locate_eval_interval_s)
        threshold = self.target_rate_mg_s * s.locate_rate_threshold_ratio

        # Track persistent flow — must stay above threshold for
        # locate_flow_persistence_s before declaring success.  This prevents
        # a startup transient from falsely passing stage 1.
        if avg_rate is not None and avg_rate > threshold:
            if self._locate_flow_since is None:
                self._locate_flow_since = now
            elif now - self._locate_flow_since >= s.locate_flow_persistence_s:
                return self._transition_to(
                    AutoRateStage.FREQ_SEARCH, control_rate, error, now,
                    f"stage 1: persistent flow for {now - self._locate_flow_since:.1f}s "
                    f"(avg {avg_rate:.1f} > {threshold:.1f}); moving to stage 2",
                )
            return self._make_decision(
                control_rate, error,
                f"stage 1: flow above threshold ({avg_rate:.1f} > {threshold:.1f}), "
                f"persisting {(now - self._locate_flow_since):.1f}/{s.locate_flow_persistence_s:.0f}s",
            )
        else:
            self._locate_flow_since = None

        if self.window_position_units >= s.max_window_units:
            return self._make_decision(
                control_rate, error,
                f"stage 1: window at max ({s.max_window_units}), "
                f"avg {avg_rate:.1f} — target may be unreachable",
            )

        # Open window further
        self.window_position_units = min(
            s.max_window_units,
            self.window_position_units + s.locate_window_step,
        )
        self._last_decision_time = now
        return self._make_decision(
            control_rate, error,
            f"stage 1: avg {avg_rate:.1f} < {threshold:.1f}; "
            f"open window to {self.window_position_units}",
        )

    def _eval_freq_search(self, control_rate: float, error: float, now: float):
        """Stage 2: sweep frequency to find critical threshold."""
        s = self.settings

        if self._stage_entered_at is None:
            self._stage_entered_at = now
            self.duty_permyriad = s.freq_search_duty
            self._freq_search_zero_streak = 0
            self._freq_search_best_rate = -1.0
            self._freq_search_best_freq = 0
            self._freq_search_worse_streak = 0

        # Wait for settle
        if self._last_decision_time is not None:
            elapsed = now - self._last_decision_time
            if elapsed < s.freq_search_settle_s:
                return self._make_decision(
                    control_rate, error,
                    f"stage 2: settling ({elapsed:.1f}/{s.freq_search_settle_s:.0f}s)",
                )

        avg_rate = self._recent_avg_rate(now, lookback_s=s.freq_search_eval_interval_s)

        if avg_rate is None:
            return self._make_decision(control_rate, error, "stage 2: waiting for valid rate samples")

        # Track consecutive zero-flow evaluations — if the powder is
        # consistently not flowing, this window is too small and we should
        # go back to stage 1 to open it further.
        if avg_rate < 0.3:
            self._freq_search_zero_streak += 1
        else:
            self._freq_search_zero_streak = 0

        if self._freq_search_zero_streak >= s.freq_search_zero_streak_limit:
            if self.window_position_units < s.max_window_units:
                self.window_position_units = min(
                    s.max_window_units,
                    self.window_position_units + s.locate_window_step,
                )
                self.frequency_hz = s.locate_start_freq_hz
                self.duty_permyriad = s.freq_search_duty
                self._freq_search_zero_streak = 0
                self._freq_search_best_rate = -1.0
                self._freq_search_best_freq = 0
                self._freq_search_worse_streak = 0
                # Stay in stage 2 with larger window, reset freq
                self._last_decision_time = now
                self._stage_entered_at = now
                return self._make_decision(
                    control_rate, error,
                    f"stage 2: {s.freq_search_zero_streak_limit} consecutive zero-flow "
                    f"evaluations; expand window to {self.window_position_units}, "
                    f"reset freq to {self.frequency_hz}Hz",
                )

        severe = self.target_rate_mg_s * s.freq_search_severe_overshoot_ratio
        target_overshoot = self.target_rate_mg_s * s.freq_search_overshoot_ratio

        if avg_rate > severe:
            self.frequency_hz = max(s.min_frequency_hz, self.frequency_hz - 1)
            return self._transition_to(
                AutoRateStage.DUTY_LOCK, control_rate, error, now,
                f"stage 2: severe overshoot (avg {avg_rate:.1f} > {severe:.1f}); "
                f"back off freq to {self.frequency_hz}Hz, moving to stage 3",
            )

        if avg_rate > target_overshoot:
            return self._transition_to(
                AutoRateStage.DUTY_LOCK, control_rate, error, now,
                f"stage 2: frequency found (avg {avg_rate:.1f}); moving to stage 3",
            )

        if self.frequency_hz >= s.max_frequency_hz:
            if self.window_position_units >= s.max_window_units:
                return self._make_decision(
                    control_rate, error,
                    f"stage 2: freq at max, window at max — target may be unreachable",
                )
            self.window_position_units = min(
                s.max_window_units,
                self.window_position_units + s.locate_window_step,
            )
            self.frequency_hz = s.locate_start_freq_hz
            self.duty_permyriad = s.freq_search_duty
            self._freq_search_zero_streak = 0
            self._freq_search_best_rate = -1.0
            self._freq_search_best_freq = 0
            self._freq_search_worse_streak = 0
            self._last_decision_time = now
            self._stage_entered_at = now
            return self._make_decision(
                control_rate, error,
                f"stage 2: freq at max ({s.max_frequency_hz}Hz), avg {avg_rate:.1f}; "
                f"expand window to {self.window_position_units}, reset freq to {self.frequency_hz}Hz",
            )

        # ── Non-monotonic detection ──
        # If rate drops after 2+ consecutive frequency increases we have
        # likely passed the powder's frequency sweet-spot.  Fall back to
        # the best frequency seen so far and transition to stage 3.
        if avg_rate > self._freq_search_best_rate:
            self._freq_search_best_rate = avg_rate
            self._freq_search_best_freq = self.frequency_hz
            self._freq_search_worse_streak = 0
        elif self._freq_search_best_rate >= 0:
            self._freq_search_worse_streak += 1

        if self._freq_search_worse_streak >= s.freq_search_worse_streak_limit:
            self.frequency_hz = self._freq_search_best_freq
            return self._transition_to(
                AutoRateStage.DUTY_LOCK, control_rate, error, now,
                f"stage 2: rate declining over {self._freq_search_worse_streak} steps "
                f"(best was {self._freq_search_best_rate:.1f} at "
                f"{self._freq_search_best_freq}Hz); fall back and move to stage 3",
            )

        # Increase frequency
        self.frequency_hz = min(
            s.max_frequency_hz,
            self.frequency_hz + s.freq_search_step_hz,
        )
        self._last_decision_time = now
        return self._make_decision(
            control_rate, error,
            f"stage 2: avg {avg_rate:.1f} < {target_overshoot:.1f}; "
            f"increase freq to {self.frequency_hz}Hz",
        )

    def _eval_duty_lock(self, control_rate: float, error: float, now: float):
        """Stage 3: PI on duty only; frequency and window are frozen."""
        s = self.settings

        if self._stage_entered_at is None:
            self._stage_entered_at = now
            self._duty_integral_error_mg = 0.0
            self._locked_since = None
            self._locked = False
            self._stage3_entry_duty = self.duty_permyriad

        # ── Dead-end detection: duty keeps climbing but rate nowhere near target ──
        # This happens when the current window×frequency cannot physically
        # reach the target rate.  Without this check the system would stay
        # stuck in stage 3 forever, never locking and never escalating.
        duty_since_entry = self.duty_permyriad - self._stage3_entry_duty
        time_in_stage = now - self._stage_entered_at
        stuck = (
            abs(duty_since_entry) >= s.duty_lock_dead_end_drift
            or time_in_stage >= s.duty_lock_dead_end_timeout_s
        )
        if stuck and abs(error) > s.duty_lock_range_mg_s * 3:
            rate_low = error > 0
            rate_high = error < 0

            # Rate LOW: open window first, then try frequency.
            # The non-monotonic detection in stage 2 already proved that higher
            # frequencies hurt at this window; window expansion is the correct
            # escalation because it lowers the critical-frequency threshold.
            if rate_low:
                if self.window_position_units < s.max_window_units:
                    self.window_position_units = min(
                        s.max_window_units,
                        self.window_position_units + s.locate_window_step,
                    )
                    self.frequency_hz = s.locate_start_freq_hz
                    self.duty_permyriad = s.freq_search_duty
                    self._last_decision_time = now
                    return self._transition_to(
                        AutoRateStage.FREQ_SEARCH, control_rate, error, now,
                        f"stage 3: dead end — rate low for {time_in_stage:.0f}s; "
                        f"open window to {self.window_position_units}, goto stage 2",
                    )
                elif self.frequency_hz < s.max_frequency_hz:
                    self.frequency_hz += s.freq_search_step_hz
                    self.duty_permyriad = s.freq_search_duty
                    self._last_decision_time = now
                    return self._transition_to(
                        AutoRateStage.FREQ_SEARCH, control_rate, error, now,
                        f"stage 3: dead end — rate low for {time_in_stage:.0f}s, "
                        f"window at max; increase freq to {self.frequency_hz}Hz, "
                        f"goto stage 2",
                    )

            # Rate HIGH: decrease frequency first, then close window.
            # Lower frequency reduces flow without risking clogging that
            # window closure could cause.
            if rate_high:
                if self.frequency_hz > s.min_frequency_hz:
                    self.frequency_hz -= s.freq_search_step_hz
                    self.duty_permyriad = s.freq_search_duty
                    self._last_decision_time = now
                    return self._transition_to(
                        AutoRateStage.FREQ_SEARCH, control_rate, error, now,
                        f"stage 3: dead end — rate high for {time_in_stage:.0f}s; "
                        f"decrease freq to {self.frequency_hz}Hz, goto stage 2",
                    )
                elif self.window_position_units > s.min_window_units:
                    self.window_position_units = max(
                        s.min_window_units,
                        self.window_position_units - s.locate_window_step,
                    )
                    self.frequency_hz = s.locate_start_freq_hz
                    self.duty_permyriad = s.freq_search_duty
                    self._last_decision_time = now
                    return self._transition_to(
                        AutoRateStage.FREQ_SEARCH, control_rate, error, now,
                        f"stage 3: dead end — rate high for {time_in_stage:.0f}s, "
                        f"freq at min; close window to "
                        f"{self.window_position_units}, goto stage 2",
                    )

            # All parameters at limits
            return self._make_decision(
                control_rate, error,
                f"stage 3: dead end — all parameters at limits",
            )

        # Rate IS close to target but lock hasn't happened yet —
        # reset the counters so we don't trigger prematurely
        if stuck and abs(error) <= s.duty_lock_range_mg_s * 3:
            self._stage3_entry_duty = self.duty_permyriad
            self._stage_entered_at = now

        # ── Overspeed within stage 3 ──
        if control_rate > self.target_rate_mg_s * s.overspeed_multiple:
            return self._handle_overspeed(control_rate, error, now)

        # ── Duty PI with interval gating ──
        duty_interval = s.duty_pi_interval_s
        if self._last_decision_time is not None:
            since_last = now - self._last_decision_time
        else:
            since_last = duty_interval + 1.0

        duty_delta = 0
        freq_delta = 0
        reason_frag = ""

        if since_last >= duty_interval and abs(error) > 0.2:
            self._duty_integral_error_mg = max(
                -20.0, min(20.0, self._duty_integral_error_mg + error * since_last)
            )
            duty_delta = round(
                s.duty_pi_gain_per_mg_s * error
                + 1.0 * self._duty_integral_error_mg
            )
            duty_delta = max(-s.duty_pi_step, min(s.duty_pi_step, duty_delta))

            # Apply with bounds
            new_duty = self.duty_permyriad + duty_delta
            new_duty = max(s.min_duty_permyriad, min(s.max_duty_permyriad, new_duty))
            actual_delta = new_duty - self.duty_permyriad

            if actual_delta != 0:
                self.duty_permyriad = new_duty
                self._last_decision_time = now
                if actual_delta > 0:
                    reason_frag = f"stage 3: increase duty to {self.duty_permyriad}"
                else:
                    reason_frag = f"stage 3: reduce duty to {self.duty_permyriad}"

        # ── Lock detection ──
        if abs(error) <= s.duty_lock_range_mg_s:
            if self._locked_since is None:
                self._locked_since = now
            elif now - self._locked_since >= s.duty_lock_duration_s:
                if not self._locked:
                    self._locked = True
                    return self._transition_to(
                        AutoRateStage.STEADY_MONITOR, control_rate, error, now,
                        f"stage 3: locked for {now - self._locked_since:.1f}s; "
                        f"moving to stage 4",
                    )
        else:
            self._locked_since = None

        if not reason_frag:
            reason_frag = f"stage 3: locked={self._locked} error={error:.1f}"

        return self._make_decision(control_rate, error, reason_frag)

    def _eval_steady_monitor(self, control_rate: float, error: float, now: float):
        """Stage 4: monitor for drift and escalate through the fallback chain.

        Escalation uses *relative* duty drift from the value at which we
        entered stage 4, NOT hard thresholds.  This adapts to different
        powder/target combinations where the achievable duty band varies.
        """
        s = self.settings

        if self._stage_entered_at is None:
            self._stage_entered_at = now
            self._stage4_entry_duty = self.duty_permyriad
            self._reset_monitor_counters()

        # ── Persistence tracking for escalation (must run before unlock) ──
        self._update_monitor_counters(control_rate, now)

        # ── Time-based escalation: rate persistently below target ──
        # This MUST run before the unlock check, otherwise a large persistent
        # error causes unlock → PI tweak → return on every frame, and the
        # escalation never gets a chance to fire.
        # If the rate has been below 90 % of target for too long the current
        # window×frequency combination is physically incapable of reaching
        # the target regardless of duty.  Escalate without waiting for the
        # slower duty-drift trigger.
        if control_rate < self.target_rate_mg_s * 0.9:
            if self._rate_below_target_since is None:
                self._rate_below_target_since = now
            elif now - self._rate_below_target_since >= s.monitor_rate_deviation_timeout_s:
                if self.frequency_hz < s.max_frequency_hz:
                    self.frequency_hz += s.freq_search_step_hz
                    self._rate_below_target_since = None
                    self._reset_monitor_counters()
                    self._stage4_entry_duty = self.duty_permyriad
                    return self._make_decision(
                        control_rate, error,
                        f"stage 4: rate below target for "
                        f"{now - self._rate_below_target_since:.0f}s; "
                        f"increase freq to {self.frequency_hz}Hz",
                    )
                elif self.window_position_units < s.max_window_units:
                    self.window_position_units = min(
                        s.max_window_units,
                        self.window_position_units + s.locate_window_step,
                    )
                    self.frequency_hz = s.locate_start_freq_hz
                    self.duty_permyriad = s.freq_search_duty
                    self._rate_below_target_since = None
                    self._reset_monitor_counters()
                    return self._transition_to(
                        AutoRateStage.FREQ_SEARCH, control_rate, error, now,
                        f"stage 4: rate below target for "
                        f"{now - self._rate_below_target_since:.0f}s, freq at max; "
                        f"open window to {self.window_position_units}, reset, goto stage 2",
                    )
        else:
            self._rate_below_target_since = None

        # ── Escalate: duty drifted HIGH + rate LOW → need more frequency ──
        if (
            self._high_duty_since is not None
            and self._low_rate_since is not None
            and now - self._high_duty_since >= s.monitor_persistence_s
            and now - self._low_rate_since >= s.monitor_persistence_s
        ):
            if self.frequency_hz < s.max_frequency_hz:
                self.frequency_hz += s.freq_search_step_hz
                self._last_decision_time = now
                self._reset_monitor_counters()
                self._stage4_entry_duty = self.duty_permyriad
                return self._make_decision(
                    control_rate, error,
                    f"stage 4: duty drifted up ({self.duty_permyriad}, "
                    f"+{self.duty_permyriad - self._stage4_entry_duty} from entry) "
                    f"+ rate low; increase freq to {self.frequency_hz}Hz",
                )
            elif self.window_position_units < s.max_window_units:
                self.window_position_units = min(
                    s.max_window_units,
                    self.window_position_units + s.locate_window_step,
                )
                self.frequency_hz = s.locate_start_freq_hz
                self.duty_permyriad = s.freq_search_duty
                self._reset_monitor_counters()
                return self._transition_to(
                    AutoRateStage.FREQ_SEARCH, control_rate, error, now,
                    f"stage 4: duty drifted up, freq at max; "
                    f"open window to {self.window_position_units}, reset, goto stage 2",
                )

        # ── Escalate: duty drifted LOW + rate HIGH → need less frequency ──
        if (
            self._low_duty_since is not None
            and self._high_rate_since is not None
            and now - self._low_duty_since >= s.monitor_persistence_s
            and now - self._high_rate_since >= s.monitor_persistence_s
        ):
            if self.frequency_hz > s.min_frequency_hz:
                self.frequency_hz -= s.freq_search_step_hz
                self._last_decision_time = now
                self._reset_monitor_counters()
                self._stage4_entry_duty = self.duty_permyriad
                return self._make_decision(
                    control_rate, error,
                    f"stage 4: duty drifted down ({self.duty_permyriad}, "
                    f"{self.duty_permyriad - self._stage4_entry_duty} from entry) "
                    f"+ rate high; reduce freq to {self.frequency_hz}Hz",
                )
            elif self.window_position_units > s.min_window_units:
                self.window_position_units = max(
                    s.min_window_units,
                    self.window_position_units - s.locate_window_step,
                )
                self.frequency_hz = s.locate_start_freq_hz
                self.duty_permyriad = s.freq_search_duty
                self._reset_monitor_counters()
                return self._transition_to(
                    AutoRateStage.FREQ_SEARCH, control_rate, error, now,
                    f"stage 4: duty drifted down, freq at min; "
                    f"close window to {self.window_position_units}, reset, goto stage 2",
                )

        # ── Unlock / re-lock (runs after escalation, before PI trim) ──
        if abs(error) > s.duty_lock_range_mg_s and self._locked:
            self._locked = False
            self._locked_since = None
            return self._eval_duty_lock(control_rate, error, now)

        if abs(error) <= s.duty_lock_range_mg_s and not self._locked:
            if self._locked_since is None:
                self._locked_since = now
            elif now - self._locked_since >= s.duty_lock_duration_s:
                self._locked = True
                self._stage4_entry_duty = self.duty_permyriad
                self._reset_monitor_counters()
                return self._make_decision(
                    control_rate, error,
                    f"stage 4: re-locked, duty={self.duty_permyriad}",
                )

        # ── Routine duty trim ──
        return self._eval_duty_lock(control_rate, error, now)

    # ------------------------------------------------------------------
    # Emergency overspeed
    # ------------------------------------------------------------------

    def _handle_overspeed(self, control_rate: float, error: float, now: float):
        """Cut duty aggressively when overspeed detected (any stage).

        In stage 2 this means frequency is already high enough — transition
        to stage 3 so the controller stops hunting for more frequency and
        instead fine-tunes duty downward.
        """
        s = self.settings
        self._locked = False
        self._locked_since = None
        self._reset_monitor_counters()

        # In stage 1, overspeed means the window is already large enough — stop
        # opening it further and move to stage 2 to find the right frequency+duty.
        # BUT: during the settle period startup transients can produce brief
        # spikes.  Limit duty cuts to 3 per settle window — cutting all the way
        # to 10 % kills flow and the PI cannot recover in reasonable time.
        if self._stage == AutoRateStage.INITIAL_LOCATE:
            last_change = (
                self._last_decision_time
                if self._last_decision_time is not None
                else self._stage_entered_at
            )
            in_settle = (
                self._stage_entered_at is not None
                and now - max(self._stage_entered_at, last_change) < s.locate_settle_s
            )
            if in_settle and self._locate_settle_cuts < 3:
                self.duty_permyriad = max(s.min_duty_permyriad, self.duty_permyriad - s.emergency_duty_step)
                self._locate_settle_cuts += 1
                self._last_duty_update_s = now
                return self._make_decision(
                    control_rate, error,
                    f"stage 1: overspeed during settle (cut {self._locate_settle_cuts}/3); "
                    f"duty to {self.duty_permyriad}, staying in stage 1",
                )
            if in_settle:
                # Already cut 3 times — hold and wait for settle to expire
                return self._make_decision(
                    control_rate, error,
                    f"stage 1: overspeed during settle; max cuts reached, holding at "
                    f"duty={self.duty_permyriad}",
                )
            self.duty_permyriad = max(s.min_duty_permyriad, self.duty_permyriad - s.emergency_duty_step)
            self._last_duty_update_s = now
            self._last_decision_time = now
            return self._transition_to(
                AutoRateStage.FREQ_SEARCH, control_rate, error, now,
                f"stage 1 overspeed: window {self.window_position_units} is sufficient "
                f"(settled); cut duty to {self.duty_permyriad}, transitioning to stage 2",
            )

        # In stage 2, overspeed means frequency was found — go to stage 3
        if self._stage == AutoRateStage.FREQ_SEARCH:
            self.duty_permyriad = max(s.min_duty_permyriad, self.duty_permyriad - s.emergency_duty_step)
            self._last_duty_update_s = now
            self._last_decision_time = now
            return self._transition_to(
                AutoRateStage.DUTY_LOCK, control_rate, error, now,
                f"stage 2 overspeed: rate {control_rate:.1f} exceeds threshold; "
                f"freq={self.frequency_hz}Hz is sufficient, transitioning to stage 3 "
                f"with duty cut to {self.duty_permyriad}",
            )

        duty_interval = s.emergency_duty_interval_s
        if self._last_duty_update_s is not None:
            since_last = now - self._last_duty_update_s
        else:
            since_last = duty_interval + 1.0

        if since_last < duty_interval:
            return self._make_decision(
                control_rate, error,
                "overspeed: waiting for emergency duty cooldown",
            )

        # Aggressive cut: proportional to overshoot severity, but not so
        # large that it creates asymmetric oscillation against the normal
        # PI step (duty_pi_step = 20).
        overshoot = max(0.0, control_rate - self.target_rate_mg_s * s.overspeed_multiple)
        cut = min(
            s.emergency_duty_step,
            max(s.duty_pi_step, int(overshoot / 2.0)),
        )
        self.duty_permyriad = max(s.min_duty_permyriad, self.duty_permyriad - cut)
        self._last_duty_update_s = now
        self._last_decision_time = now

        if self.duty_permyriad <= s.min_duty_permyriad and self.frequency_hz > s.min_frequency_hz:
            self.frequency_hz -= 1
            return self._make_decision(
                control_rate, error,
                f"overspeed: duty at min; cut freq to {self.frequency_hz}Hz",
            )

        return self._make_decision(
            control_rate, error,
            f"overspeed: cut duty by {cut} to {self.duty_permyriad}",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _recent_avg_rate(self, now: float, lookback_s: float = 2.0) -> float | None:
        """Average control rate over the last *lookback_s* seconds."""
        cutoff = now - lookback_s
        recent = [r for t, r in self._rate_buffer if t >= cutoff]
        if not recent:
            return None
        return sum(recent) / len(recent)

    def _transition_to(
        self,
        stage: AutoRateStage,
        control_rate: float,
        error: float,
        now: float,
        reason: str,
    ):
        """Move to a new stage, resetting stage-specific state."""
        self._stage = stage
        self._stage_entered_at = None
        self._last_decision_time = None
        self._locate_flow_since = None
        self._locate_settle_cuts = 0
        self._freq_search_zero_streak = 0
        self._freq_search_best_rate = -1.0
        self._freq_search_best_freq = 0
        self._freq_search_worse_streak = 0
        self._duty_integral_error_mg = 0.0
        self._locked_since = None
        self._locked = False
        if stage == AutoRateStage.DUTY_LOCK:
            self._stage3_entry_duty = self.duty_permyriad
        if stage == AutoRateStage.STEADY_MONITOR:
            self._stage4_entry_duty = self.duty_permyriad
        self._reset_monitor_counters()
        return self._make_decision(control_rate, error, reason)

    def _reset_monitor_counters(self) -> None:
        self._high_duty_since = None
        self._low_duty_since = None
        self._low_rate_since = None
        self._high_rate_since = None
        self._rate_below_target_since = None

    def _update_monitor_counters(self, control_rate: float, now: float) -> None:
        """Track persistence of duty drift and rate deviation for escalation.

        Uses *relative* drift from the entry duty (``_stage4_entry_duty``)
        rather than hard thresholds, so the same logic works across
        different target rates and powder behaviours.
        """
        s = self.settings
        drift = s.monitor_duty_drift

        # Duty drifted high from entry point
        if self.duty_permyriad >= self._stage4_entry_duty + drift:
            if self._high_duty_since is None:
                self._high_duty_since = now
        else:
            self._high_duty_since = None

        # Duty drifted low from entry point
        if self.duty_permyriad <= self._stage4_entry_duty - drift:
            if self._low_duty_since is None:
                self._low_duty_since = now
        else:
            self._low_duty_since = None

        # Rate low
        if control_rate < self.target_rate_mg_s * s.monitor_rate_low_ratio:
            if self._low_rate_since is None:
                self._low_rate_since = now
        else:
            self._low_rate_since = None

        # Rate high
        if control_rate > self.target_rate_mg_s * s.monitor_rate_high_ratio:
            if self._high_rate_since is None:
                self._high_rate_since = now
        else:
            self._high_rate_since = None

    def _make_decision(self, control_rate: float, error: float, reason: str):
        """Build the decision dataclass."""
        freq_changed = self.frequency_hz != self._freq_before
        duty_changed = self.duty_permyriad != self._duty_before
        window_changed = self.window_position_units != self._window_before

        return AutoRateDecision(
            target_rate_mg_s=self.target_rate_mg_s,
            control_rate_mg_s=round(control_rate, 3),
            rate_error_mg_s=round(error, 3),
            frequency_before_hz=self._freq_before,
            frequency_after_hz=self.frequency_hz,
            duty_before_permyriad=self._duty_before,
            duty_after_permyriad=self.duty_permyriad,
            window_before_units=self._window_before,
            window_after_units=self.window_position_units,
            freq_changed=freq_changed,
            duty_changed=duty_changed,
            window_changed=window_changed,
            locked=self._locked,
            stage=int(self._stage),
            reason=reason,
        )
