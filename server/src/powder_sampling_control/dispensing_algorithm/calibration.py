"""Local, explainable mass-yield estimation from approved calibration samples."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .models import DispenseStage, FeedAction


@dataclass(frozen=True)
class CalibrationSample:
    stage: DispenseStage
    action: FeedAction
    stable_mass_delta_mg: float
    communication_ok: bool
    stable: bool
    alarm_free: bool

    @property
    def eligible(self) -> bool:
        return (
            self.action.duration_ms > 0
            and self.stable_mass_delta_mg > 0
            and self.communication_ok
            and self.stable
            and self.alarm_free
        )

    @property
    def mg_per_s(self) -> float:
        return self.stable_mass_delta_mg / (self.action.duration_ms / 1000.0)


class LocalYieldEstimator:
    """Inverse-distance estimate; deliberately simpler than GPR for phase one."""

    def __init__(self, samples: list[CalibrationSample] | None = None) -> None:
        self._samples = list(samples or [])

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def add(self, sample: CalibrationSample) -> None:
        self._samples.append(sample)

    @classmethod
    def from_directory(cls, path: str | Path) -> "LocalYieldEstimator":
        """Load completed physical calibration records written by the collection script."""
        samples = []
        for record_path in Path(path).glob("*.json"):
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
                if record.get("result") != "completed" or not record.get("approved_for_planner", True):
                    continue
                action = record["action"]
                mass_after = record["mass_after"]
                samples.append(
                    CalibrationSample(
                        stage=DispenseStage(record.get("stage", DispenseStage.COARSE.value)),
                        action=FeedAction(
                            window_position_units=int(action["window_position_units"]),
                            frequency_hz=int(action["frequency_hz"]),
                            duty_permyriad=int(action["duty_permyriad"]),
                            duration_ms=round(float(record["actual_duration_s"]) * 1000),
                        ),
                        stable_mass_delta_mg=float(record["stable_mass_delta_mg"]),
                        communication_ok=True,
                        stable=bool(mass_after["stable"]),
                        alarm_free=not bool(record.get("alarm_trace")),
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return cls(samples)

    def estimate_mg_per_s(
        self,
        *,
        stage: DispenseStage,
        action: FeedAction,
        fallback_mg_per_s: float,
    ) -> float:
        eligible = [sample for sample in self._samples if sample.stage == stage and sample.eligible]
        if not eligible:
            return fallback_mg_per_s

        weighted_total = 0.0
        weight_sum = 0.0
        for sample in eligible:
            distance = (
                abs(sample.action.window_position_units - action.window_position_units) / 200.0
                + abs(sample.action.frequency_hz - action.frequency_hz) / 20.0
                + abs(sample.action.duty_permyriad - action.duty_permyriad) / 1000.0
            )
            weight = 1.0 / (0.25 + distance)
            weighted_total += sample.mg_per_s * weight
            weight_sum += weight
        return weighted_total / weight_sum
