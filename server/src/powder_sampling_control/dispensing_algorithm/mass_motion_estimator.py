"""Filtered mass-motion estimation for quantized balance measurements.

The estimator uses an alpha-beta-gamma observer.  It differentiates the
observer state instead of repeatedly differentiating raw 1 mg balance data,
which would otherwise make acceleration and jerk mostly measurement noise.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MassMotionEstimatorSettings:
    alpha: float = 0.45
    beta: float = 0.10
    gamma: float = 0.008
    jerk_alpha: float = 0.20
    min_dt_s: float = 0.05
    max_dt_s: float = 1.0
    min_valid_elapsed_s: float = 1.5
    min_valid_samples: int = 5
    max_rate_mg_s: float = 500.0
    max_acceleration_mg_s2: float = 60.0
    max_jerk_mg_s3: float = 120.0
    prediction_horizon_s: float = 0.75

    def __post_init__(self) -> None:
        for name in ("alpha", "beta", "gamma", "jerk_alpha"):
            value = getattr(self, name)
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be in (0, 1]")
        if not 0 < self.min_dt_s <= self.max_dt_s:
            raise ValueError("estimator dt limits are invalid")
        if self.min_valid_elapsed_s <= 0 or self.min_valid_samples < 2:
            raise ValueError("estimator validity limits are invalid")
        if min(
            self.max_rate_mg_s,
            self.max_acceleration_mg_s2,
            self.max_jerk_mg_s3,
            self.prediction_horizon_s,
        ) <= 0:
            raise ValueError("estimator bounds and prediction horizon must be positive")


@dataclass(frozen=True)
class MassMotionState:
    timestamp_s: float
    measured_mass_mg: float
    filtered_mass_mg: float
    rate_mg_s: float
    acceleration_mg_s2: float
    jerk_mg_s3: float
    predicted_mass_mg: float
    predicted_rate_mg_s: float
    innovation_mg: float
    sample_count: int
    valid: bool


class MassMotionEstimator:
    """Estimate mass, flow, acceleration and jerk with variable sample time."""

    def __init__(self, settings: MassMotionEstimatorSettings | None = None) -> None:
        self.settings = settings or MassMotionEstimatorSettings()
        self.reset()

    def reset(self) -> None:
        self._timestamp_s: float | None = None
        self._started_at_s: float | None = None
        self._mass_mg = 0.0
        self._rate_mg_s = 0.0
        self._acceleration_mg_s2 = 0.0
        self._jerk_mg_s3 = 0.0
        self._sample_count = 0

    @staticmethod
    def _bounded(value: float, lower: float, upper: float) -> float:
        return min(upper, max(lower, value))

    def update(self, timestamp_s: float, measured_mass_mg: float) -> MassMotionState:
        if measured_mass_mg < 0:
            raise ValueError("measured_mass_mg must be non-negative")
        if self._timestamp_s is not None and timestamp_s <= self._timestamp_s:
            raise ValueError("estimator timestamps must be strictly increasing")

        settings = self.settings
        if self._timestamp_s is None:
            self._timestamp_s = timestamp_s
            self._started_at_s = timestamp_s
            self._mass_mg = measured_mass_mg
            self._sample_count = 1
            return self._state(measured_mass_mg, innovation_mg=0.0)

        raw_dt = timestamp_s - self._timestamp_s
        dt = self._bounded(raw_dt, settings.min_dt_s, settings.max_dt_s)
        predicted_mass = (
            self._mass_mg
            + self._rate_mg_s * dt
            + 0.5 * self._acceleration_mg_s2 * dt * dt
        )
        predicted_rate = self._rate_mg_s + self._acceleration_mg_s2 * dt
        innovation = measured_mass_mg - predicted_mass

        previous_acceleration = self._acceleration_mg_s2
        self._mass_mg = max(0.0, predicted_mass + settings.alpha * innovation)
        self._rate_mg_s = self._bounded(
            predicted_rate + settings.beta * innovation / dt,
            0.0,
            settings.max_rate_mg_s,
        )
        self._acceleration_mg_s2 = self._bounded(
            previous_acceleration + 2.0 * settings.gamma * innovation / (dt * dt),
            -settings.max_acceleration_mg_s2,
            settings.max_acceleration_mg_s2,
        )
        raw_jerk = (self._acceleration_mg_s2 - previous_acceleration) / dt
        raw_jerk = self._bounded(
            raw_jerk,
            -settings.max_jerk_mg_s3,
            settings.max_jerk_mg_s3,
        )
        self._jerk_mg_s3 = (
            settings.jerk_alpha * raw_jerk
            + (1.0 - settings.jerk_alpha) * self._jerk_mg_s3
        )
        self._timestamp_s = timestamp_s
        self._sample_count += 1
        return self._state(measured_mass_mg, innovation_mg=innovation)

    def _state(self, measured_mass_mg: float, *, innovation_mg: float) -> MassMotionState:
        assert self._timestamp_s is not None
        assert self._started_at_s is not None
        horizon = self.settings.prediction_horizon_s
        predicted_mass = max(
            self._mass_mg,
            self._mass_mg
            + self._rate_mg_s * horizon
            + 0.5 * self._acceleration_mg_s2 * horizon * horizon,
        )
        predicted_rate = self._bounded(
            self._rate_mg_s + self._acceleration_mg_s2 * horizon,
            0.0,
            self.settings.max_rate_mg_s,
        )
        valid = (
            self._sample_count >= self.settings.min_valid_samples
            and self._timestamp_s - self._started_at_s >= self.settings.min_valid_elapsed_s
        )
        return MassMotionState(
            timestamp_s=self._timestamp_s,
            measured_mass_mg=measured_mass_mg,
            filtered_mass_mg=self._mass_mg,
            rate_mg_s=self._rate_mg_s,
            acceleration_mg_s2=self._acceleration_mg_s2,
            jerk_mg_s3=self._jerk_mg_s3,
            predicted_mass_mg=predicted_mass,
            predicted_rate_mg_s=predicted_rate,
            innovation_mg=innovation_mg,
            sample_count=self._sample_count,
            valid=valid,
        )
