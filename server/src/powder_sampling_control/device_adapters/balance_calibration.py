"""Versioned AT8811C raw-count to milligram calibration records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isclose, sqrt
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class BalanceCalibrationPoint:
    """One stable standard-mass observation used by the linear fit."""

    reference_mg: float
    raw_count: float
    sample_count: int = 1
    raw_count_spread: float = 0.0

    def __post_init__(self) -> None:
        if self.reference_mg < 0:
            raise ValueError("reference_mg must be non-negative")
        if self.sample_count < 1:
            raise ValueError("sample_count must be positive")
        if self.raw_count_spread < 0:
            raise ValueError("raw_count_spread must be non-negative")

    def to_dict(self) -> dict:
        return {
            "reference_mg": self.reference_mg,
            "raw_count": self.raw_count,
            "sample_count": self.sample_count,
            "raw_count_spread": self.raw_count_spread,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BalanceCalibrationPoint":
        return cls(
            reference_mg=float(data["reference_mg"]),
            raw_count=float(data["raw_count"]),
            sample_count=int(data.get("sample_count", 1)),
            raw_count_spread=float(data.get("raw_count_spread", 0.0)),
        )


@dataclass(frozen=True)
class BalanceCalibration:
    """Validated linear conversion ``mass_mg = count * scale + offset``."""

    calibration_id: str
    created_at_utc: str
    device_id: str
    scale_mg_per_count: float
    offset_mg: float
    points: tuple[BalanceCalibrationPoint, ...]
    max_abs_residual_mg: float
    rms_residual_mg: float
    r_squared: float
    maximum_allowed_residual_mg: float
    minimum_r_squared: float
    valid: bool

    def __post_init__(self) -> None:
        if not self.calibration_id:
            raise ValueError("calibration_id is required")
        if self.scale_mg_per_count <= 0:
            raise ValueError("scale_mg_per_count must be positive")
        if len(self.points) < 3:
            raise ValueError("at least three calibration points are required")
        if self.maximum_allowed_residual_mg <= 0:
            raise ValueError("maximum_allowed_residual_mg must be positive")
        if not 0 < self.minimum_r_squared <= 1:
            raise ValueError("minimum_r_squared must be in (0, 1]")

    def mass_mg(self, raw_count: float) -> float:
        return float(raw_count) * self.scale_mg_per_count + self.offset_mg

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "calibration_id": self.calibration_id,
            "created_at_utc": self.created_at_utc,
            "device_id": self.device_id,
            "conversion": {
                "formula": "mass_mg = raw_count * scale_mg_per_count + offset_mg",
                "scale_mg_per_count": self.scale_mg_per_count,
                "offset_mg": self.offset_mg,
            },
            "validation": {
                "valid": self.valid,
                "max_abs_residual_mg": self.max_abs_residual_mg,
                "rms_residual_mg": self.rms_residual_mg,
                "r_squared": self.r_squared,
                "maximum_allowed_residual_mg": self.maximum_allowed_residual_mg,
                "minimum_r_squared": self.minimum_r_squared,
            },
            "points": [point.to_dict() for point in self.points],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BalanceCalibration":
        if int(data.get("schema_version", 0)) != 1:
            raise ValueError("unsupported balance calibration schema_version")
        conversion = data.get("conversion", {})
        validation = data.get("validation", {})
        return cls(
            calibration_id=str(data["calibration_id"]),
            created_at_utc=str(data["created_at_utc"]),
            device_id=str(data.get("device_id", "")),
            scale_mg_per_count=float(conversion["scale_mg_per_count"]),
            offset_mg=float(conversion["offset_mg"]),
            points=tuple(BalanceCalibrationPoint.from_dict(item) for item in data["points"]),
            max_abs_residual_mg=float(validation["max_abs_residual_mg"]),
            rms_residual_mg=float(validation["rms_residual_mg"]),
            r_squared=float(validation["r_squared"]),
            maximum_allowed_residual_mg=float(validation["maximum_allowed_residual_mg"]),
            minimum_r_squared=float(validation["minimum_r_squared"]),
            valid=bool(validation["valid"]),
        )


def fit_balance_calibration(
    points: Iterable[BalanceCalibrationPoint],
    *,
    device_id: str = "balance_01",
    maximum_allowed_residual_mg: float = 2.0,
    minimum_r_squared: float = 0.999,
    calibration_id: str | None = None,
    created_at_utc: str | None = None,
) -> BalanceCalibration:
    """Fit and validate a count-to-mg line from at least three mass points."""

    fitted_points = tuple(points)
    if len(fitted_points) < 3:
        raise ValueError("at least zero plus two standard-mass points are required")
    if len({point.reference_mg for point in fitted_points}) != len(fitted_points):
        raise ValueError("reference masses must be unique")
    if len({point.raw_count for point in fitted_points}) < 2:
        raise ValueError("raw counts must change across calibration points")
    if not any(point.reference_mg == 0 for point in fitted_points):
        raise ValueError("a zero-mass calibration point is required")
    if maximum_allowed_residual_mg <= 0:
        raise ValueError("maximum_allowed_residual_mg must be positive")
    if not 0 < minimum_r_squared <= 1:
        raise ValueError("minimum_r_squared must be in (0, 1]")

    mean_count = sum(point.raw_count for point in fitted_points) / len(fitted_points)
    mean_mass = sum(point.reference_mg for point in fitted_points) / len(fitted_points)
    denominator = sum((point.raw_count - mean_count) ** 2 for point in fitted_points)
    if denominator == 0:
        raise ValueError("calibration raw counts have zero variance")
    scale = sum(
        (point.raw_count - mean_count) * (point.reference_mg - mean_mass)
        for point in fitted_points
    ) / denominator
    if scale <= 0:
        raise ValueError("calibration scale must be positive; check mass/count ordering")
    offset = mean_mass - scale * mean_count

    residuals = [
        point.reference_mg - (scale * point.raw_count + offset)
        for point in fitted_points
    ]
    max_abs_residual = max(abs(value) for value in residuals)
    rms_residual = sqrt(sum(value * value for value in residuals) / len(residuals))
    total_variance = sum((point.reference_mg - mean_mass) ** 2 for point in fitted_points)
    residual_variance = sum(value * value for value in residuals)
    r_squared = 1.0 - residual_variance / total_variance if total_variance else 0.0
    valid = (
        max_abs_residual <= maximum_allowed_residual_mg
        and r_squared >= minimum_r_squared
    )

    created = created_at_utc or datetime.now(timezone.utc).isoformat()
    identifier = calibration_id or datetime.now().strftime("at8811c-cal-%Y%m%d-%H%M%S")
    return BalanceCalibration(
        calibration_id=identifier,
        created_at_utc=created,
        device_id=device_id,
        scale_mg_per_count=scale,
        offset_mg=offset,
        points=fitted_points,
        max_abs_residual_mg=max_abs_residual,
        rms_residual_mg=rms_residual,
        r_squared=r_squared,
        maximum_allowed_residual_mg=maximum_allowed_residual_mg,
        minimum_r_squared=minimum_r_squared,
        valid=valid,
    )


def load_balance_calibration(
    path: str | Path,
    *,
    require_valid: bool = True,
) -> BalanceCalibration:
    calibration_path = Path(path)
    stored = BalanceCalibration.from_dict(
        json.loads(calibration_path.read_text(encoding="utf-8"))
    )
    # Never trust validation flags or conversion coefficients copied into the
    # JSON. Refit from the recorded reference points every time it is loaded.
    calibration = fit_balance_calibration(
        stored.points,
        device_id=stored.device_id,
        maximum_allowed_residual_mg=stored.maximum_allowed_residual_mg,
        minimum_r_squared=stored.minimum_r_squared,
        calibration_id=stored.calibration_id,
        created_at_utc=stored.created_at_utc,
    )
    if not isclose(
        stored.scale_mg_per_count,
        calibration.scale_mg_per_count,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ) or not isclose(stored.offset_mg, calibration.offset_mg, rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError(
            f"balance calibration {stored.calibration_id} conversion does not match its points"
        )
    if stored.valid != calibration.valid:
        raise ValueError(
            f"balance calibration {stored.calibration_id} validation flag does not match its points"
        )
    if require_valid and not calibration.valid:
        raise ValueError(
            f"balance calibration {calibration.calibration_id} failed validation"
        )
    return calibration
