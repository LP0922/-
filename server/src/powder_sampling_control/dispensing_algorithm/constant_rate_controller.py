"""Rate-regulating feedback controller for constant-rate dispensing tests.

Unlike :class:`ContinuousFeedbackController`, this controller targets a fixed
flow rate, has no stage transitions, no stop prediction, and no tail tapering.

Actuator priority (three-tier):
1. **Frequency + Duty** — co-primary, adjusted every ~0.5 s
2. **Window position** — last resort, only when both freq and duty are at hard limits

Lock mechanism: once |rate_error| <= lock_range_mg_s, frequency and duty are
held constant.  They resume only when the rate drifts outside the lock range
or a severe overspeed occurs.  Window adjustments are unaffected by lock.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True)
class ConstantRateSettings:
    """Defaults tuned for tight rate regulation with frequency+duty as primary."""

    # ── Frequency loop (coarse knob — used only when duty saturates) ──
    freq_gain_per_mg_s: float = 8.0
    freq_integral_gain_per_mg: float = 0.5
    freq_step_hz: int = 1
    freq_update_interval_s: float = 2.0
    freq_deadband_mg_s: float = 0.50

    # ── Duty loop (primary fine knob — adjusted first in all regimes) ──
    duty_gain_per_mg_s: float = 60.0
    duty_integral_gain_per_mg: float = 1.5
    duty_step_per_update: int = 20
    emergency_duty_step_per_update: int = 30
    duty_update_interval_s: float = 2.0
    emergency_duty_update_interval_s: float = 1.0
    duty_deadband_mg_s: float = 0.50

    # ── Parameter lock ──
    # When |rate_error| <= lock_range_mg_s, frequency and duty are frozen at
    # their current values.  They unlock automatically when the rate drifts
    # outside this band or severe overspeed is detected.
    lock_range_mg_s: float = 1.5

    # ── Frequency lock ──
    # When the system has been free of overspeed and clog for this duration,
    # frequency is locked at its current value and only duty adjusts.
    # Frequency unlocks on overspeed, clog, or duty hitting a limit.
    freq_lock_stable_s: float = 3.0

    # ── Window-position loop (last resort, very conservative) ──
    position_step_units: int = 5
    position_update_interval_s: float = 5.0
    position_deadband_mg_s: float = 4.0
    position_persistence_samples: int = 12

    # ── Bounds ──
    min_frequency_hz: int = 10
    max_frequency_hz: int = 80
    min_duty_permyriad: int = 1000
    max_duty_permyriad: int = 5000
    min_window_units: int = 100
    # The service uses absolute LA10 window coordinates.  The web client
    # translates its relative 100..750 display range by +700, so a normal
    # request such as 300 reaches this controller as coordinate 1000.
    # Keep this aligned with the service-side actuator limit.
    max_window_units: int = 2050

    # ── Clog detection ──
    # When the estimated rate stays below this threshold for clog_duration_s,
    # the controller enters "clogged" mode: only frequency is increased (to
    # shake powder loose) while duty is held steady.
    clog_rate_threshold_mg_s: float = 0.5
    clog_duration_s: float = 3.0

    # ── Oscillation-triggered window trim ──
    # When frequency flips back-and-forth within a narrow range the ±2 Hz
    # step is too coarse for this powder.  A sliding window tracks recent
    # frequency changes; oscillation is detected when ALL of these hold:
    #   1. direction flips within the window ≥ oscillation_flip_threshold
    #   2. frequency spread within the window ≤ oscillation_max_range_hz
    #   3. no run of ≥ oscillation_max_consecutive_same same-direction steps
    # Response: compare average rate at each observed frequency; if the
    # higher values are closer to target → close window, else open window.
    oscillation_flip_threshold: int = 2
    oscillation_max_range_hz: int = 12
    oscillation_max_consecutive_same: int = 8
    oscillation_window_step: int = 10
    oscillation_cooldown_s: float = 6.0

    # ── Safety ──
    acceleration_guard_mg_s2: float = 2.0
    overspeed_multiple: float = 1.5
    maximum_flow_rate_mg_s: float = 100.0

    def __post_init__(self) -> None:
        if min(self.freq_gain_per_mg_s, self.freq_integral_gain_per_mg,
               self.duty_gain_per_mg_s, self.duty_integral_gain_per_mg,
               self.freq_deadband_mg_s, self.duty_deadband_mg_s,
               self.position_deadband_mg_s,
               self.freq_update_interval_s, self.duty_update_interval_s,
               self.position_update_interval_s) <= 0:
            raise ValueError("controller gains, deadbands, and intervals must be positive")
        if self.lock_range_mg_s <= 0:
            raise ValueError("lock_range_mg_s must be positive")
        if self.freq_step_hz < 1 or self.duty_step_per_update < 1 or self.position_step_units < 1:
            raise ValueError("controller steps must be positive")
        if not 10 <= self.min_frequency_hz < self.max_frequency_hz <= 80:
            raise ValueError("frequency limits are invalid")
        if not 1000 <= self.min_duty_permyriad < self.max_duty_permyriad <= 5000:
            raise ValueError("duty limits are invalid")
        if not 0 <= self.min_window_units < self.max_window_units:
            raise ValueError("window limits are invalid")
        if self.overspeed_multiple <= 1:
            raise ValueError("overspeed_multiple must be greater than one")
        if self.maximum_flow_rate_mg_s <= 0:
            raise ValueError("maximum_flow_rate_mg_s must be positive")
        if self.emergency_duty_step_per_update < self.duty_step_per_update:
            raise ValueError("emergency duty step must be at least the normal duty step")
        if not 0 < self.emergency_duty_update_interval_s <= self.duty_update_interval_s:
            raise ValueError("emergency duty interval must be positive and no slower than normal")
        if self.oscillation_flip_threshold < 2:
            raise ValueError("oscillation_flip_threshold must be >= 2")
        if not 2 <= self.oscillation_max_range_hz <= 20:
            raise ValueError("oscillation_max_range_hz must be 2–20 Hz")
        if self.oscillation_max_consecutive_same < 2:
            raise ValueError("oscillation_max_consecutive_same must be >= 2")
        if not 1 <= self.oscillation_window_step <= self.position_step_units * 3:
            raise ValueError("oscillation_window_step must be 1–position_step_units*3")
        if self.oscillation_cooldown_s <= 0:
            raise ValueError("oscillation_cooldown_s must be positive")


@dataclass(frozen=True)
class ConstantRateObservation:
    """One live observation from the balance and motion estimator."""

    rate_mg_s: float
    predicted_rate_mg_s: float
    acceleration_mg_s2: float = 0.0
    valid: bool = True


@dataclass(frozen=True)
class ConstantRateDecision:
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
    clogged: bool
    reason: str


class ConstantRateController:
    """Three-tier controller for maintaining a constant powder flow rate.

    Frequency and duty are co-primary actuators — both adjusted every ~1.5 s
    in response to rate error, giving the powder flow time to stabilise after
    each change. Frequency is the coarser knob, duty is the finer one.

    Once the rate settles within lock_range_mg_s of target, the controller
    freezes frequency and duty at their current values.  They unfreeze
    automatically if the rate drifts outside the lock band or severe
    overspeed occurs.

    Window position is intentionally fixed during normal operation.  It is
    opened by one tiny step only when BOTH frequency and duty have reached
    their maximum limits yet the flow rate is still below target.  Window is
    NEVER closed by feedback — closing causes powder clogging.
    """

    def __init__(
        self,
        *,
        target_rate_mg_s: float,
        initial_duty_permyriad: int,
        initial_window_units: int,
        frequency_hz: int,
        settings: ConstantRateSettings | None = None,
    ) -> None:
        if target_rate_mg_s <= 0:
            raise ValueError("target_rate_mg_s must be positive")
        self.target_rate_mg_s = float(target_rate_mg_s)
        self.settings = settings or ConstantRateSettings()
        s = self.settings
        if not s.min_frequency_hz <= frequency_hz <= s.max_frequency_hz:
            raise ValueError("frequency_hz is outside controller limits")
        if not s.min_duty_permyriad <= initial_duty_permyriad <= s.max_duty_permyriad:
            raise ValueError("initial_duty_permyriad is outside controller limits")
        if not s.min_window_units <= initial_window_units <= s.max_window_units:
            raise ValueError("initial_window_units is outside controller limits")
        self.frequency_hz = frequency_hz
        self.duty_permyriad = initial_duty_permyriad
        self.window_position_units = initial_window_units

        # Separate integrals — frequency and duty are physically different actuators
        self._freq_integral_error_mg = 0.0
        self._duty_integral_error_mg = 0.0

        # Lock state — when True, frequency and duty are frozen
        self._locked = False

        # Clog state — when True, frequency+duty are increased together
        self._clogged = False
        self._zero_rate_since_s: float | None = None

        # Frequency lock — after no-overspeed/no-clog for freq_lock_stable_s,
        # frequency is held and only duty adjusts.  Unlocks on overspeed, clog,
        # or duty hitting a hard limit.
        self._freq_locked = False
        self._freq_stable_start: float | None = None

        # Oscillation tracking — sliding-window direction-flip detection
        self._osc_history: deque[tuple[int, int]] = deque(maxlen=16)  # (freq, direction_delta)
        self._osc_rate_map: dict[int, tuple[float, int]] = {}  # freq → (sum_rate, count)
        self._osc_last_change_time: float | None = None
        self._osc_last_window_time: float | None = None
        self._osc_lock_start_time: float | None = None  # continuous lock duration
        self._osc_same_dir_count: int = 0  # consecutive same-direction window trims
        self._osc_last_dir: int = 0  # last trim direction: 1=open, -1=close

        self._last_timestamp_s: float | None = None
        self._last_freq_update_s: float | None = None
        self._last_duty_update_s: float | None = None
        self._last_position_update_s: float | None = None
        self._under_rate_samples = 0
        self._over_rate_samples = 0

    def reset(self) -> None:
        self._freq_integral_error_mg = 0.0
        self._duty_integral_error_mg = 0.0
        self._locked = False
        self._clogged = False
        self._zero_rate_since_s = None
        self._freq_locked = False
        self._freq_stable_start = None
        self._osc_history.clear()
        self._osc_rate_map.clear()
        self._osc_last_change_time = None
        self._osc_last_window_time = None
        self._osc_lock_start_time = None
        self._osc_same_dir_count = 0
        self._osc_last_dir = 0
        self._last_timestamp_s = None
        self._last_freq_update_s = None
        self._last_duty_update_s = None
        self._last_position_update_s = None
        self._under_rate_samples = 0
        self._over_rate_samples = 0

    @property
    def locked(self) -> bool:
        """True when frequency and duty are frozen at their current values."""
        return self._locked

    def step(
        self,
        observation: ConstantRateObservation,
        timestamp_s: float | None = None,
    ) -> ConstantRateDecision:
        self._validate_observation(observation)
        s = self.settings
        now = monotonic() if timestamp_s is None else float(timestamp_s)
        if self._last_timestamp_s is not None and now <= self._last_timestamp_s:
            raise ValueError("controller timestamps must be strictly increasing")
        dt = 0.0 if self._last_timestamp_s is None else min(2.0, now - self._last_timestamp_s)
        self._last_timestamp_s = now

        # Stable control signal: weighted blend of filtered + predicted rate
        control_rate = 0.8 * observation.rate_mg_s + 0.2 * observation.predicted_rate_mg_s
        error = self.target_rate_mg_s - control_rate

        # Update separate integrals (clamped) — only when unlocked
        if dt > 0 and not self._locked:
            self._freq_integral_error_mg = max(
                -20.0, min(20.0, self._freq_integral_error_mg + error * dt)
            )
            self._duty_integral_error_mg = max(
                -20.0, min(20.0, self._duty_integral_error_mg + error * dt)
            )

        freq_before = self.frequency_hz
        duty_before = self.duty_permyriad
        position_before = self.window_position_units

        # --- hold during warm-up ---
        if not observation.valid:
            return ConstantRateDecision(
                target_rate_mg_s=self.target_rate_mg_s,
                control_rate_mg_s=control_rate,
                rate_error_mg_s=error,
                frequency_before_hz=freq_before,
                frequency_after_hz=freq_before,
                duty_before_permyriad=duty_before,
                duty_after_permyriad=duty_before,
                window_before_units=position_before,
                window_after_units=position_before,
                freq_changed=False,
                duty_changed=False,
                window_changed=False,
                locked=False,
                clogged=False,
                reason="motion estimate not valid; hold initial parameters",
            )

        # ── overspeed detection ──
        absolute_overspeed = control_rate > s.maximum_flow_rate_mg_s
        severe_overspeed = absolute_overspeed or control_rate >= self.target_rate_mg_s * s.overspeed_multiple

        # ── lock management ──
        # Severe overspeed always breaks the lock (safety first).
        # Otherwise, lock when rate is within the lock band; unlock when it drifts out.
        if severe_overspeed:
            self._locked = False
            self._freq_integral_error_mg = 0.0
            self._duty_integral_error_mg = 0.0
        elif abs(error) <= s.lock_range_mg_s:
            if not self._locked:
                self._locked = True
                # Clear integrals on lock entry to prevent windup
                self._freq_integral_error_mg = 0.0
                self._duty_integral_error_mg = 0.0
        else:
            self._locked = False

        # ── clog detection ──
        # Rate near zero for clog_duration_s → likely powder bridging / clogging.
        if observation.rate_mg_s < s.clog_rate_threshold_mg_s:
            if self._zero_rate_since_s is None:
                self._zero_rate_since_s = now
            elif now - self._zero_rate_since_s >= s.clog_duration_s:
                if not self._clogged:
                    self._clogged = True
                    # Clear integrals so frequency PI starts fresh
                    self._freq_integral_error_mg = 0.0
        else:
            self._clogged = False
            self._zero_rate_since_s = None

        # ── frequency lock management ──
        # After freq_lock_stable_s of no-overspeed and no-clog, the system
        # is considered to have found a workable frequency.  From that point
        # frequency is held and only duty fine-tunes the rate.
        # Overspeed or clog immediately unlock frequency.
        if severe_overspeed or self._clogged:
            self._freq_locked = False
            self._freq_stable_start = None
        elif self._freq_stable_start is None:
            self._freq_stable_start = now
        elif now - self._freq_stable_start >= s.freq_lock_stable_s:
            self._freq_locked = True

        reason = ""
        freq_delta = 0
        duty_delta = 0

        # ── duty-first priority regime ──
        # In all regimes duty is adjusted first.  Frequency moves ONLY when
        # duty is at a hard limit, OR during clog (where both ramp together
        # to break through the powder bridging).
        if severe_overspeed:
            # ── emergency: cut duty first; only cut frequency when duty at min ──
            overspeed = max(0.0, control_rate - self.target_rate_mg_s)
            emergency_steps = max(1, int(overspeed / 5.0))

            if self.duty_permyriad > s.min_duty_permyriad:
                duty_delta = -min(
                    s.emergency_duty_step_per_update,
                    emergency_steps * s.duty_step_per_update,
                )
                freq_delta = 0
                reason = "flow is above the overspeed guard; reduce duty"
            else:
                duty_delta = 0
                freq_delta = -s.freq_step_hz
                reason = "flow is above the overspeed guard; duty at minimum, reduce frequency"
            self._over_rate_samples += 1
            self._under_rate_samples = 0
        elif self._locked:
            # ── locked: hold current parameters ──
            freq_delta = 0
            duty_delta = 0
            self._under_rate_samples = self._over_rate_samples = 0
            reason = f"flow is within ±{s.lock_range_mg_s} mg/s of target; parameters locked"
        elif abs(error) <= s.freq_deadband_mg_s:
            # ── deadband: hold both ──
            freq_delta = 0
            duty_delta = 0
            self._under_rate_samples = self._over_rate_samples = 0
            reason = "flow is inside the deadband"
        elif self._clogged and error > 0:
            # ── clog: ramp BOTH frequency and duty together to break through ──
            # Frequency+duty rise in parallel so the powder threshold is
            # reached at a lower, more gradual frequency.
            freq_delta = round(
                s.freq_gain_per_mg_s * error
                + s.freq_integral_gain_per_mg * self._freq_integral_error_mg
            )
            freq_delta = max(0, min(s.freq_step_hz, freq_delta))
            duty_delta = round(
                s.duty_gain_per_mg_s * error
                + s.duty_integral_gain_per_mg * self._duty_integral_error_mg
            )
            duty_delta = max(0, min(s.duty_step_per_update, duty_delta))
            self._under_rate_samples += 1
            self._over_rate_samples = 0
            reason = "clog suspected; increase frequency and duty"
        elif error < 0:
            # ── above target: cut duty first ──
            self._under_rate_samples = 0
            self._over_rate_samples += 1

            if self.duty_permyriad > s.min_duty_permyriad:
                duty_delta = round(
                    s.duty_gain_per_mg_s * error
                    + s.duty_integral_gain_per_mg * self._duty_integral_error_mg
                )
                duty_delta = max(-s.duty_step_per_update, min(0, duty_delta))
                freq_delta = 0
                reason = "flow is above target; reduce duty"
            else:
                freq_delta = round(
                    s.freq_gain_per_mg_s * error
                    + s.freq_integral_gain_per_mg * self._freq_integral_error_mg
                )
                freq_delta = max(-s.freq_step_hz, min(0, freq_delta))
                duty_delta = 0
                reason = "flow is above target; duty at minimum, reduce frequency"
        else:
            # ── below target: increase duty first ──
            self._under_rate_samples += 1
            self._over_rate_samples = 0

            if self.duty_permyriad < s.max_duty_permyriad:
                duty_delta = round(
                    s.duty_gain_per_mg_s * error
                    + s.duty_integral_gain_per_mg * self._duty_integral_error_mg
                )
                duty_delta = max(0, min(s.duty_step_per_update, duty_delta))
                # Acceleration guard: don't increase if already accelerating
                if observation.acceleration_mg_s2 > s.acceleration_guard_mg_s2:
                    duty_delta = 0
                freq_delta = 0
                reason = "flow is below target; increase duty"
            else:
                freq_delta = round(
                    s.freq_gain_per_mg_s * error
                    + s.freq_integral_gain_per_mg * self._freq_integral_error_mg
                )
                freq_delta = max(0, min(s.freq_step_hz, freq_delta))
                if observation.acceleration_mg_s2 > s.acceleration_guard_mg_s2:
                    freq_delta = 0
                duty_delta = 0
                reason = "flow is below target; duty at maximum, increase frequency"

        # ── frequency lock ──
        # When locked, suppress all frequency changes.  If duty hits a hard
        # limit while the error is still pushing in that direction, unlock
        # frequency so it can take over.
        if self._freq_locked:
            if (self.duty_permyriad >= s.max_duty_permyriad and error > s.duty_deadband_mg_s) or \
               (self.duty_permyriad <= s.min_duty_permyriad and error < -s.duty_deadband_mg_s):
                self._freq_locked = False
                self._freq_stable_start = None
                reason += " (freq unlocked: duty at limit)"
            else:
                freq_delta = 0

        # ── apply frequency change ──
        freq_interval = s.freq_update_interval_s
        if self._last_freq_update_s is None or now - self._last_freq_update_s >= freq_interval:
            self.frequency_hz = self._bounded_freq(self.frequency_hz + freq_delta)
            self._last_freq_update_s = now

        # ── apply duty change ──
        duty_interval = (
            s.emergency_duty_update_interval_s
            if severe_overspeed
            else s.duty_update_interval_s
        )
        if self._last_duty_update_s is None or now - self._last_duty_update_s >= duty_interval:
            self.duty_permyriad = self._bounded_duty(self.duty_permyriad + duty_delta)
            self._last_duty_update_s = now

        # ── oscillation-triggered window trim ──
        # Sliding-window approach: track recent frequency changes in a
        # fixed-size deque.  Oscillation is detected when ALL of these hold:
        #   1. direction flips ≥ oscillation_flip_threshold
        #   2. frequency range ≤ oscillation_max_range_hz
        #   3. longest same-direction run < oscillation_max_consecutive_same
        # This catches multi-value patterns like 62→64→66→62→60→64,
        # not just strict A↔B↔A two-value toggling.
        position_changed = False
        freq_changed = self.frequency_hz != freq_before
        in_cooldown = (
            self._osc_last_window_time is not None
            and now - self._osc_last_window_time < s.oscillation_cooldown_s
        )

        # ── lock-duration tracking ──
        # Only clear history after *continuous* lock > 4 s.  A fleeting
        # touch of the lock band during oscillation must not wipe history.
        if self._locked:
            if self._osc_lock_start_time is None:
                self._osc_lock_start_time = now
            elif now - self._osc_lock_start_time > 4.0:
                self._osc_history.clear()
                self._osc_rate_map.clear()
                self._osc_last_change_time = None
                self._osc_lock_start_time = None
        else:
            self._osc_lock_start_time = None

        # Severe overspeed is part of the oscillation pattern (clog ramp-up
        # → overspeed → cut → clog …).  Do NOT clear history here — clearing
        # prevents oscillation detection from ever firing.
        if not self._locked:
            # If there was a long gap since the last frequency change,
            # start fresh — old history is not part of the current pattern.
            if (
                self._osc_last_change_time is not None
                and now - self._osc_last_change_time > s.freq_update_interval_s * 3
            ):
                self._osc_history.clear()
                self._osc_rate_map.clear()

            if freq_changed:
                direction = 1 if self.frequency_hz > freq_before else -1
                self._osc_history.append((self.frequency_hz, direction))
                self._osc_last_change_time = now

            # Accumulate rate sample EVERY step (not just on freq change)
            # so each frequency gets multiple samples for a reliable average.
            # Continue accumulating even during cooldown — only the trigger
            # is paused; the history should keep building so it can fire
            # immediately when the cooldown expires.
            key = self.frequency_hz
            prev_sum, prev_cnt = self._osc_rate_map.get(key, (0.0, 0))
            self._osc_rate_map[key] = (prev_sum + control_rate, prev_cnt + 1)

        # ── check oscillation trigger conditions ──
        min_history = s.oscillation_flip_threshold + 2
        if len(self._osc_history) >= min_history and not in_cooldown:
            directions = [d for _, d in self._osc_history]

            # 1. Count direction flips
            flips = sum(
                1 for i in range(1, len(directions))
                if directions[i] != directions[i - 1]
            )

            # 2. Longest consecutive same-direction run
            max_same = 1
            cur = 1
            for i in range(1, len(directions)):
                if directions[i] == directions[i - 1]:
                    cur += 1
                    if cur > max_same:
                        max_same = cur
                else:
                    cur = 1

            # 3. Frequency range within the window
            freqs = [f for f, _ in self._osc_history]
            freq_range = max(freqs) - min(freqs)

            if (
                flips >= s.oscillation_flip_threshold
                and freq_range <= s.oscillation_max_range_hz
                and max_same < s.oscillation_max_consecutive_same
            ):
                # Oscillation confirmed — compare average rate at each
                # frequency to decide window direction.
                sorted_freqs = sorted(self._osc_rate_map.keys())
                if len(sorted_freqs) >= 2:
                    # Split observed frequencies into "lower half" and
                    # "upper half" by median, then compare their average
                    # rate errors to decide window direction.
                    mid = len(sorted_freqs) // 2
                    low_freqs = sorted_freqs[:mid]
                    high_freqs = sorted_freqs[mid:]

                    low_sum = 0.0
                    low_cnt = 0
                    for f in low_freqs:
                        s_rate, cnt = self._osc_rate_map[f]
                        low_sum += s_rate
                        low_cnt += cnt
                    high_sum = 0.0
                    high_cnt = 0
                    for f in high_freqs:
                        s_rate, cnt = self._osc_rate_map[f]
                        high_sum += s_rate
                        high_cnt += cnt

                    if low_cnt > 0 and high_cnt > 0:
                        low_avg = low_sum / low_cnt
                        high_avg = high_sum / high_cnt
                        low_err = abs(self.target_rate_mg_s - low_avg)
                        high_err = abs(self.target_rate_mg_s - high_avg)

                        low_str = ",".join(str(f) for f in low_freqs)
                        high_str = ",".join(str(f) for f in high_freqs)

                        # Decide direction:
                        #   high closer AND high > target  → close (reduce overshoot)
                        #   high closer AND high < target  → open  (both too low, need more)
                        #   low  closer                   → open  (as before)
                        tgt = self.target_rate_mg_s
                        if high_err < low_err and high_avg > tgt:
                            direction = -1  # close
                        else:
                            direction = 1   # open

                        # ── same-direction guard ──
                        # If the last 3 trims were all the same direction, skip
                        # this one to prevent runaway (e.g. closing the window
                        # into a death spiral).
                        if (
                            direction == self._osc_last_dir
                            and self._osc_same_dir_count >= 3
                        ):
                            reason += (
                                f"; freq oscillation [{low_str}]<->[{high_str}]Hz "
                                f"(window trim skipped: {self._osc_same_dir_count} "
                                f"consecutive same-direction trims)"
                            )
                        else:
                            if direction == 1:
                                self.window_position_units = min(
                                    s.max_window_units,
                                    self.window_position_units + s.oscillation_window_step,
                                )
                                position_changed = self.window_position_units != position_before
                                reason += (
                                    f"; freq oscillation [{low_str}]<->[{high_str}]Hz "
                                    f"(low {low_str}Hz avg {low_avg:.1f}, "
                                    f"high {high_str}Hz avg {high_avg:.1f} — "
                                    f"open window {s.oscillation_window_step}u)"
                                )
                            else:
                                self.window_position_units = max(
                                    s.min_window_units,
                                    self.window_position_units - s.oscillation_window_step,
                                )
                                position_changed = self.window_position_units != position_before
                                reason += (
                                    f"; freq oscillation [{low_str}]<->[{high_str}]Hz "
                                    f"(low {low_str}Hz avg {low_avg:.1f}, "
                                    f"high {high_str}Hz avg {high_avg:.1f} — "
                                    f"close window {s.oscillation_window_step}u)"
                                )

                            # Track direction for same-direction guard
                            if direction == self._osc_last_dir:
                                self._osc_same_dir_count += 1
                            else:
                                self._osc_same_dir_count = 1
                            self._osc_last_dir = direction

                # Reset tracking & start cooldown after window adjustment
                self._osc_history.clear()
                self._osc_rate_map.clear()
                self._osc_last_change_time = None
                self._osc_last_window_time = now
                self._freq_integral_error_mg = 0.0

        # ── window-position adjustment (last resort) ──
        # Window stays fixed during normal operation — only frequency and
        # duty are adjusted.  When EITHER freq or duty (or both) hit their
        # maximum limits yet flow is still below target, open the window
        # a tiny step.  Window is NEVER closed by feedback (closing causes
        # powder clogging).
        position_due = (
            self._last_position_update_s is None
            or now - self._last_position_update_s >= s.position_update_interval_s
        )
        persistent_low = self._under_rate_samples >= s.position_persistence_samples
        freq_at_limit = self.frequency_hz == s.max_frequency_hz
        duty_at_limit = self.duty_permyriad == s.max_duty_permyriad
        if (
            position_due
            and persistent_low
            and error > 0
            and (freq_at_limit or duty_at_limit)
        ):
            self.window_position_units = min(
                s.max_window_units,
                self.window_position_units + s.position_step_units,
            )
            position_changed = self.window_position_units != position_before
            self._last_position_update_s = now
            if position_changed:
                who = "freq" if freq_at_limit else "duty"
                reason += f"; {who} at max, open window slightly"
            self._under_rate_samples = 0

        return ConstantRateDecision(
            target_rate_mg_s=self.target_rate_mg_s,
            control_rate_mg_s=control_rate,
            rate_error_mg_s=error,
            frequency_before_hz=freq_before,
            frequency_after_hz=self.frequency_hz,
            duty_before_permyriad=duty_before,
            duty_after_permyriad=self.duty_permyriad,
            window_before_units=position_before,
            window_after_units=self.window_position_units,
            freq_changed=self.frequency_hz != freq_before,
            duty_changed=self.duty_permyriad != duty_before,
            window_changed=position_changed,
            locked=self._locked,
            clogged=self._clogged,
            reason=reason,
        )

    @staticmethod
    def _validate_observation(observation: ConstantRateObservation) -> None:
        for name in ("rate_mg_s", "predicted_rate_mg_s"):
            if getattr(observation, name) < 0:
                raise ValueError(f"{name} must be non-negative")

    def _bounded_freq(self, value: int) -> int:
        return max(
            self.settings.min_frequency_hz,
            min(self.settings.max_frequency_hz, int(value)),
        )

    def _bounded_duty(self, value: int) -> int:
        return max(
            self.settings.min_duty_permyriad,
            min(self.settings.max_duty_permyriad, int(value)),
        )
