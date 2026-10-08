"""Versioned L0 parameter lookup and target-mass interpolation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from .models import L0Profile, StageParameters


def _stage_from_mapping(data: dict[str, Any]) -> StageParameters:
    return StageParameters(
        window_position_units=int(data["window_position_units"]),
        frequency_hz=int(data["frequency_hz"]),
        duty_permyriad=int(data["duty_permyriad"]),
        reference_mg_per_s=float(data["reference_mg_per_s"]),
        min_duration_ms=int(data["min_duration_ms"]),
        max_duration_ms=int(data["max_duration_ms"]),
    )


def _profile_from_mapping(data: dict[str, Any]) -> L0Profile:
    return L0Profile(
        profile_id=str(data["profile_id"]),
        powder_type=str(data["powder_type"]),
        powder_batch=str(data["powder_batch"]),
        feeder_head=str(data["feeder_head"]),
        recipe_version=str(data["recipe_version"]),
        target_mass_mg=float(data["target_mass_mg"]),
        slow_entry_margin_mg=float(data["slow_entry_margin_mg"]),
        fine_entry_margin_mg=float(data["fine_entry_margin_mg"]),
        hard_overweight_margin_mg=float(data["hard_overweight_margin_mg"]),
        coarse=_stage_from_mapping(data["coarse"]),
        slow=_stage_from_mapping(data["slow"]),
        fine=_stage_from_mapping(data["fine"]),
    )


def _interpolate_stage(low: StageParameters, high: StageParameters, ratio: float) -> StageParameters:
    def blend(name: str) -> float:
        return getattr(low, name) + (getattr(high, name) - getattr(low, name)) * ratio

    return StageParameters(
        window_position_units=round(blend("window_position_units")),
        frequency_hz=round(blend("frequency_hz")),
        duty_permyriad=round(blend("duty_permyriad")),
        reference_mg_per_s=blend("reference_mg_per_s"),
        min_duration_ms=round(blend("min_duration_ms")),
        max_duration_ms=round(blend("max_duration_ms")),
    )


class L0Repository:
    """Selects an approved L0 row, interpolating only between matching rows."""

    def __init__(self, profiles: list[L0Profile]) -> None:
        if not profiles:
            raise ValueError("at least one L0 profile is required")
        self._profiles = profiles

    @classmethod
    def from_json(cls, path: str | Path) -> "L0Repository":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([_profile_from_mapping(item) for item in data["profiles"]])

    def select(
        self,
        *,
        powder_type: str,
        powder_batch: str,
        feeder_head: str,
        recipe_version: str,
        target_mass_mg: float,
    ) -> L0Profile:
        candidates = [
            profile
            for profile in self._profiles
            if (
                profile.powder_type == powder_type
                and profile.powder_batch == powder_batch
                and profile.feeder_head == feeder_head
                and profile.recipe_version == recipe_version
            )
        ]
        if not candidates:
            raise LookupError("no approved L0 profile matches powder, head, batch, and recipe version")
        candidates.sort(key=lambda profile: profile.target_mass_mg)
        if target_mass_mg <= candidates[0].target_mass_mg:
            return candidates[0]
        if target_mass_mg >= candidates[-1].target_mass_mg:
            return candidates[-1]
        high_index = next(index for index, item in enumerate(candidates) if item.target_mass_mg >= target_mass_mg)
        low, high = candidates[high_index - 1], candidates[high_index]
        ratio = (target_mass_mg - low.target_mass_mg) / (high.target_mass_mg - low.target_mass_mg)
        return replace(
            low,
            profile_id=f"interpolated:{low.profile_id}:{high.profile_id}:{target_mass_mg:g}mg",
            target_mass_mg=target_mass_mg,
            slow_entry_margin_mg=low.slow_entry_margin_mg + (high.slow_entry_margin_mg - low.slow_entry_margin_mg) * ratio,
            fine_entry_margin_mg=low.fine_entry_margin_mg + (high.fine_entry_margin_mg - low.fine_entry_margin_mg) * ratio,
            hard_overweight_margin_mg=low.hard_overweight_margin_mg + (high.hard_overweight_margin_mg - low.hard_overweight_margin_mg) * ratio,
            coarse=_interpolate_stage(low.coarse, high.coarse, ratio),
            slow=_interpolate_stage(low.slow, high.slow, ratio),
            fine=_interpolate_stage(low.fine, high.fine, ratio),
        )
