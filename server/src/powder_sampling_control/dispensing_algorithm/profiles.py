"""Dispensing profile seeds, control-profile loading, and draft generation.

Consolidates the former standalone modules:

    feedback_profiles.py   software seed presets and per-target feedback profiles
    control_profiles.py    runtime control-profile loading and interpolation
    method_generator.py    auditable draft control-profile generation

The files in ``data/control_profiles`` are runtime candidates derived from the
research workspaces.  They contain a small set of mass anchors; this module
interpolates continuous controller parameters for every integer target from
100 through 1000 mg.  Discrete startup/recovery decisions remain powder-wide.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import load_product_requirements, validate_target_mass


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROFILE_DIR = PROJECT_ROOT / "data" / "control_profiles"


# ── feedback seeds (was feedback_profiles.py) ───────────────────────────────
#
# These values are software seeds for the live feedback controller. They are not
# calibration results and should be updated only from completed, stable runs.

DISPENSE_PRESETS = {
    "fast-80hz-p200": {
        "frequency_hz": 80,
        "duty_permyriad": 2000,
        "window_position_units": 200,
    },
    "steady-65hz-p300": {
        "frequency_hz": 65,
        "duty_permyriad": 2000,
        "window_position_units": 300,
    },
    "60hz-p150": {
        "frequency_hz": 60,
        "duty_permyriad": 2000,
        "window_position_units": 150,
    },
    "60hz-p200": {
        "frequency_hz": 60,
        "duty_permyriad": 2000,
        "window_position_units": 200,
    },
    "slow-60hz-p250": {
        "frequency_hz": 60,
        "duty_permyriad": 1600,
        "window_position_units": 250,
    },
    "slow-40hz-p250": {
        "frequency_hz": 40,
        "duty_permyriad": 2000,
        "window_position_units": 250,
    },
    "slow-10hz-p100": {
        "frequency_hz": 10,
        "duty_permyriad": 1000,
        "window_position_units": 100,
    },
    "slow-15hz-p100": {
        "frequency_hz": 15,
        "duty_permyriad": 1000,
        "window_position_units": 100,
    },
    "steady-70hz-p100": {
        "frequency_hz": 70,
        "duty_permyriad": 2000,
        "window_position_units": 100,
    },
    "starch-70hz-p200": {
        "frequency_hz": 70,
        "duty_permyriad": 2000,
        "window_position_units": 100,
    },
    "slow-70hz-p300": {
        "frequency_hz": 70,
        "duty_permyriad": 2000,
        "window_position_units": 500,
    },
    "lubricant-1-80hz-p300": {
        "frequency_hz": 80,
        "duty_permyriad": 2000,
        "window_position_units": 300,
    },
    "lubricant-1-80hz-p500": {
        "frequency_hz": 80,
        "duty_permyriad": 2000,
        "window_position_units": 500,
    },
    "lubricant-1-70hz-p400": {
        "frequency_hz": 70,
        "duty_permyriad": 2000,
        "window_position_units": 400,
    },
    "80hz-22pct-p350-water-loss-agent-2": {
        "frequency_hz": 80,
        "duty_permyriad": 2200,
        "window_position_units": 250,
    },
    "80hz-22pct-p300-bentonite": {
        "frequency_hz": 80,
        "duty_permyriad": 2200,
        "window_position_units": 300,
    },
    "80hz-22pct-p350-plugging-agent-1": {
        "frequency_hz": 80,
        "duty_permyriad": 2200,
        "window_position_units": 350,
    },
    "80hz-22pct-p400-plugging-agent-1": {
        "frequency_hz": 80,
        "duty_permyriad": 2200,
        "window_position_units": 400,
    },
    "80hz-22pct-p400-plugging-agent-2": {
        "frequency_hz": 80,
        "duty_permyriad": 2200,
        "window_position_units": 250,
    },
}

DISPENSE_TARGET_PROFILES = {
    100: {
        "coarse_rate_mg_s": 15.0,
        "fine_rate_mg_s": 10.0,
        "precision_rate_mg_s": 8.0,
        "maximum_flow_rate_mg_s": 25.0,
        "precision_start_remaining_mg": 35.0,
        "tail_taper_start_remaining_mg": 45.0,
        "tail_taper_end_remaining_mg": 6.0,
    },
    300: {
        "coarse_rate_mg_s": 24.0,
        "fine_rate_mg_s": 14.0,
        "precision_rate_mg_s": 10.0,
        "maximum_flow_rate_mg_s": 50.0,
        "precision_start_remaining_mg": 55.0,
        "tail_taper_start_remaining_mg": 85.0,
        "tail_taper_end_remaining_mg": 10.0,
    },
    500: {
        "coarse_rate_mg_s": 30.0,
        "fine_rate_mg_s": 14.0,
        "precision_rate_mg_s": 9.0,
        "maximum_flow_rate_mg_s": 50.0,
        "precision_start_remaining_mg": 50.0,
        "tail_taper_start_remaining_mg": 100.0,
        "tail_taper_end_remaining_mg": 10.0,
    },
}

_ACCEPTANCE_REQUIREMENTS = load_product_requirements()["acceptance"]
DISPENSE_ALLOWED_UNDERWEIGHT_MG = abs(
    float(_ACCEPTANCE_REQUIREMENTS["minimum_offset_mg"])
)
DISPENSE_ALLOWED_OVERWEIGHT_MG = float(
    _ACCEPTANCE_REQUIREMENTS["maximum_offset_mg"]
)


POWDER_CLASSIFICATION_PARAMS = {
    "Low-flow": {
        "preset_id": "steady-70hz-p100",
        "maximum_flow_rate_mg_s": 80.0,
        "fixed_tail_mass_mg": 5.0,
        "force_stop_offset_mg": 10.0,
        "duty_step_per_update": 50,
        "emergency_duty_step_per_update": 200,
        "position_feedback_enabled": False,
    },
    "Medium-flow": {
        "preset_id": "60hz-p150",
        "maximum_flow_rate_mg_s": 120.0,
        "fixed_tail_mass_mg": 2.0,
        "force_stop_offset_mg": 10.0,
        "duty_step_per_update": 30,
        "emergency_duty_step_per_update": 80,
        "position_feedback_enabled": False,
        "profile_overrides": {
            100: {
                "coarse_rate_mg_s": 25.0,
                "fine_rate_mg_s": 15.0,
                "precision_start_remaining_mg": 40.0,
                "tail_taper_start_remaining_mg": 70.0,
                "tail_taper_end_remaining_mg": 15.0,
            },
        },
    },
    "High-flow": {
        "preset_id": "slow-10hz-p100",
        "maximum_flow_rate_mg_s": 200.0,
        "fixed_tail_mass_mg": 0.0,
        "force_stop_offset_mg": 15.0,
        # High-flow: aggressive braking, window feedback ON (duty hits floor immediately)
        "duty_step_per_update": 100,
        "emergency_duty_step_per_update": 400,
        "position_feedback_enabled": True,
        "profile_overrides": {
            100: {
                "precision_start_remaining_mg": 40.0,
                "tail_taper_start_remaining_mg": 55.0,
                "tail_taper_end_remaining_mg": 12.0,
            },
            300: {
                "precision_start_remaining_mg": 80.0,
                "tail_taper_start_remaining_mg": 120.0,
                "tail_taper_end_remaining_mg": 15.0,
            },
            500: {
                "precision_start_remaining_mg": 80.0,
                "tail_taper_start_remaining_mg": 150.0,
                "tail_taper_end_remaining_mg": 20.0,
            },
        },
    },
}

# Additional overrides applied on top of class params when unstable tag is active
UNSTABLE_TAG_OVERRIDES = {
    "settle_confirmations_delta": +1,
    "dead_zone_multiplier": 1.5,
}

# When sticky tag is active, bump preset up one tier
STICKY_PRESET_BUMP = {
    "slow-10hz-p100": "slow-40hz-p250",
    "slow-40hz-p250": "slow-60hz-p250",
    "slow-60hz-p250": "60hz-p150",
    "60hz-p150": "60hz-p200",
    "60hz-p200": "steady-65hz-p300",
    "steady-65hz-p300": "steady-70hz-p100",
    "steady-70hz-p100": "slow-70hz-p300",
    "slow-70hz-p300": "fast-80hz-p200",
    "fast-80hz-p200": "fast-80hz-p200",  # already at max, no bump
}


def powder_classification_params(category: str, tags: list[str] | None = None):
    """Return the parameter overrides for a given powder classification.

    Args:
        category: One of "Low-flow", "Medium-flow", "High-flow".
        tags: Optional list of tags like ["stable"], ["unstable"], ["sticky"].

    Returns:
        dict with preset_id, maximum_flow_rate_mg_s, fixed_tail_mass_mg,
        and optionally settle_confirmations_delta, dead_zone_multiplier.
    """
    if category not in POWDER_CLASSIFICATION_PARAMS:
        raise ValueError(f"unknown powder category: {category}; choose Low-flow, Medium-flow, or High-flow")
    tags = tags or []
    params = dict(POWDER_CLASSIFICATION_PARAMS[category])

    if "unstable" in tags:
        params.update(UNSTABLE_TAG_OVERRIDES)
    if "sticky" in tags:
        params["preset_id"] = STICKY_PRESET_BUMP.get(params["preset_id"], params["preset_id"])

    return params


def dispense_plan(target_mg):
    """Return the supported integer target and its feedback profile."""
    try:
        target = int(target_mg)
    except (TypeError, ValueError) as error:
        raise ValueError("target_mg must be an integer") from error
    if target not in DISPENSE_TARGET_PROFILES:
        raise ValueError(f"unsupported dispense target: {target}; choose 100, 300, or 500 mg")
    return target, DISPENSE_TARGET_PROFILES[target]


# ── arbitrary-mass interpolation (feedback seeds) ────────────────────────────

# Interpolatable scalar fields within DISPENSE_TARGET_PROFILES entries.
_INTERPOLATABLE_KEYS = (
    "coarse_rate_mg_s",
    "fine_rate_mg_s",
    "precision_rate_mg_s",
    "precision_start_remaining_mg",
    "tail_taper_start_remaining_mg",
    "tail_taper_end_remaining_mg",
)

# Per-field clamp bounds (min, max).
_INTERPOLATION_CLAMPS = {
    "coarse_rate_mg_s": (5.0, 35.0),
    "fine_rate_mg_s": (8.0, 30.0),
    "precision_rate_mg_s": (5.0, 20.0),
    "precision_start_remaining_mg": (10.0, None),
    "tail_taper_start_remaining_mg": (15.0, None),
    "tail_taper_end_remaining_mg": (3.0, None),
}

# Sorted anchor masses from DISPENSE_TARGET_PROFILES.
_ANCHOR_MASSES = sorted(DISPENSE_TARGET_PROFILES.keys())


def _linear_interpolate(target, anchors, values):
    """Linearly interpolate *values* at *target* between *anchors*.

    If *target* is below the smallest anchor, extrapolate downward using
    the slope of the first anchor pair.  If above the largest anchor,
    extrapolate upward using the slope of the last anchor pair.
    """
    if target in anchors:
        idx = anchors.index(target)
        return values[idx]

    if target < anchors[0]:
        # extrapolate below: use slope between anchors[0] and anchors[1]
        slope = (values[1] - values[0]) / (anchors[1] - anchors[0])
        return values[0] - slope * (anchors[0] - target)

    if target > anchors[-1]:
        # extrapolate above: use slope between anchors[-2] and anchors[-1]
        slope = (values[-1] - values[-2]) / (anchors[-1] - anchors[-2])
        return values[-1] + slope * (target - anchors[-1])

    # interior interpolation
    for i in range(len(anchors) - 1):
        if anchors[i] <= target <= anchors[i + 1]:
            frac = (target - anchors[i]) / (anchors[i + 1] - anchors[i])
            return values[i] + (values[i + 1] - values[i]) * frac

    raise RuntimeError(f"unexpected interpolation state for target={target}")  # unreachable


def interpolate_profile(target_mg):
    """Return a feedback profile dict for *target_mg* (100–1000).

    Fields from ``DISPENSE_TARGET_PROFILES`` that vary by target are
    linearly interpolated between the 100 / 300 / 500 mg anchors.
    ``maximum_flow_rate_mg_s`` is NOT interpolated — the caller must
    supply it from powder-classification parameters.
    """
    target = validate_target_mass(target_mg)

    profile = {}
    for key in _INTERPOLATABLE_KEYS:
        anchor_values = [DISPENSE_TARGET_PROFILES[m][key] for m in _ANCHOR_MASSES]
        val = _linear_interpolate(target, _ANCHOR_MASSES, anchor_values)
        lo, hi = _INTERPOLATION_CLAMPS.get(key, (None, None))
        if lo is not None:
            val = max(lo, val)
        if hi is not None:
            val = min(hi, val)
        profile[key] = float(val)

    # Guard: tail_taper_end must be strictly less than tail_taper_start.
    tts = profile["tail_taper_start_remaining_mg"]
    tte = profile["tail_taper_end_remaining_mg"]
    if tte >= tts:
        profile["tail_taper_end_remaining_mg"] = tts * 0.3

    # maximum_flow_rate_mg_s is not interpolated.  Preserve the anchor's
    # value on exact anchor matches so that interpolate_profile(anchor)
    # reproduces the full anchor profile; otherwise use a safe default.
    # The caller (start_dispense) overrides this from powder session.
    if target in DISPENSE_TARGET_PROFILES:
        profile["maximum_flow_rate_mg_s"] = float(
            DISPENSE_TARGET_PROFILES[target]["maximum_flow_rate_mg_s"]
        )
    else:
        profile["maximum_flow_rate_mg_s"] = 50.0

    return profile


def validate_dispense_target(target_mg):
    """Raise ValueError if *target_mg* is not a valid dispense target."""
    validate_target_mass(target_mg)


# ── runtime control profiles (was control_profiles.py) ───────────────────────


INTERPOLATABLE_TARGET_KEYS = (
    "coarse_rate_mg_s",
    "fine_rate_mg_s",
    "precision_rate_mg_s",
    "precision_start_remaining_mg",
    "tail_taper_start_remaining_mg",
    "tail_taper_end_remaining_mg",
)

STAGE_RATE_KEYS = (
    "coarse_rate_mg_s",
    "fine_rate_mg_s",
    "precision_rate_mg_s",
    "settle_rate_mg_s",
)

EXACT_TARGET_PROFILE_OVERRIDE_KEYS = (
    "precision_start_remaining_mg",
)

EXACT_TARGET_CONTROLLER_OVERRIDE_KEYS = (
    "fixed_tail_mass_mg",
    "force_stop_offset_mg",
    "tail_pulse_enabled",
    "tail_pulse_start_remaining_mg",
    "tail_pulse_hold_window_position_units",
    "tail_pulse_initial_window_position_units",
    "tail_pulse_max_window_position_units",
    "tail_pulse_min_window_position_units",
    "tail_pulse_window_step_units",
    "tail_pulse_frequency_hz",
    "tail_pulse_duty_permyriad",
    "tail_pulse_initial_duration_s",
    "tail_pulse_min_duration_s",
    "tail_pulse_max_duration_s",
    "tail_pulse_settle_timeout_s",
    "tail_pulse_settle_minimum_wait_s",
    "tail_pulse_settle_continuous_stable_s",
    "tail_pulse_settle_max_spread_mg",
    "tail_pulse_min_gain_mg",
    "tail_pulse_max_attempts",
    "tail_pulse_max_no_gain_attempts",
    "tail_pulse_safety_guard_gain_mg",
    "tail_pulse_safety_guard_multiplier",
    "tail_pulse_micro_initial_window_position_units",
    "tail_pulse_micro_max_window_position_units",
    "tail_pulse_micro_window_step_units",
    "tail_pulse_micro_initial_duration_s",
    "tail_pulse_micro_min_duration_s",
    "tail_pulse_micro_max_duration_s",
    "tail_pulse_micro_max_attempts",
    "tail_pulse_micro_safe_stop_min_mass_mg",
    "tail_pulse_micro_max_no_gain_attempts",
)


def normalize_target_keys(raw_profiles: dict[Any, Any]) -> dict[int, dict[str, Any]]:
    """Normalize JSON string mass keys without requiring a full profile body."""
    if not isinstance(raw_profiles, dict):
        raise ValueError("target profiles must be an object")
    normalized: dict[int, dict[str, Any]] = {}
    for raw_mass, raw_values in raw_profiles.items():
        try:
            mass = int(raw_mass)
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid target profile key: {raw_mass!r}") from error
        if str(mass) != str(raw_mass) and raw_mass != mass:
            raise ValueError(f"target profile key must be an integer mass: {raw_mass!r}")
        if mass <= 0 or not isinstance(raw_values, dict):
            raise ValueError(f"invalid target profile at {raw_mass!r}")
        normalized[mass] = dict(raw_values)
    return dict(sorted(normalized.items()))


def normalize_target_profiles(raw_profiles: dict[Any, Any]) -> dict[int, dict[str, float]]:
    """Normalize target keys and validate complete interpolation anchors."""
    if not isinstance(raw_profiles, dict) or len(raw_profiles) < 2:
        raise ValueError("target_profiles must contain at least two mass anchors")
    normalized: dict[int, dict[str, float]] = {}
    for mass, raw_values in normalize_target_keys(raw_profiles).items():
        values: dict[str, float] = {}
        for key in INTERPOLATABLE_TARGET_KEYS:
            value = raw_values.get(key)
            if not isinstance(value, (int, float)):
                raise ValueError(f"target {mass} is missing numeric {key}")
            values[key] = float(value)
        normalized[mass] = values
    return dict(sorted(normalized.items()))


def normalize_target_rate_bands(raw_bands: Any) -> list[dict[str, Any]]:
    """Validate optional stepwise stage-rate policies for integer target bands."""
    if raw_bands in (None, []):
        return []
    if not isinstance(raw_bands, list):
        raise ValueError("target_rate_bands must be an array")
    normalized: list[dict[str, Any]] = []
    for index, raw_band in enumerate(raw_bands):
        if not isinstance(raw_band, dict):
            raise ValueError(f"target rate band {index} must be an object")
        minimum = validate_target_mass(raw_band.get("minimum_target_mg"))
        maximum = validate_target_mass(raw_band.get("maximum_target_mg"))
        if minimum > maximum:
            raise ValueError(f"target rate band {index} has an inverted range")
        band: dict[str, Any] = {
            "minimum_target_mg": minimum,
            "maximum_target_mg": maximum,
        }
        for key in STAGE_RATE_KEYS:
            value = raw_band.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"target rate band {index} is missing numeric {key}")
            if key == "settle_rate_mg_s":
                if float(value) != 0.0:
                    raise ValueError("settle_rate_mg_s must be zero")
            elif float(value) <= 0.0:
                raise ValueError(f"target rate band {index} has non-positive {key}")
            band[key] = float(value)
        normalized.append(band)
    normalized.sort(key=lambda band: band["minimum_target_mg"])
    for previous, current in zip(normalized, normalized[1:]):
        if current["minimum_target_mg"] <= previous["maximum_target_mg"]:
            raise ValueError("target rate bands must not overlap")
    return normalized


def normalize_exact_target_overrides(raw_overrides: Any) -> dict[int, dict[str, Any]]:
    """Validate non-interpolated overrides that apply only to one exact target."""
    if raw_overrides in (None, {}):
        return {}
    allowed_keys = set(EXACT_TARGET_PROFILE_OVERRIDE_KEYS) | set(
        EXACT_TARGET_CONTROLLER_OVERRIDE_KEYS
    )
    normalized: dict[int, dict[str, Any]] = {}
    for mass, raw_values in normalize_target_keys(raw_overrides).items():
        validate_target_mass(mass)
        unknown_keys = set(raw_values) - allowed_keys
        if unknown_keys:
            raise ValueError(
                f"target {mass} has unsupported exact overrides: "
                + ", ".join(sorted(unknown_keys))
            )
        values: dict[str, Any] = {}
        for key, value in raw_values.items():
            if key == "tail_pulse_enabled":
                if not isinstance(value, bool):
                    raise ValueError(f"target {mass} has non-boolean exact override {key}")
                values[key] = value
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"target {mass} has non-numeric exact override {key}")
            if float(value) <= 0:
                raise ValueError(f"target {mass} has non-positive exact override {key}")
            values[key] = float(value)
        normalized[mass] = values
    return dict(sorted(normalized.items()))


def resolve_target_rate_band(raw_bands: Any, target_mg: Any) -> dict[str, Any] | None:
    """Return the single configured stage-rate band containing the target."""
    target = validate_target_mass(target_mg)
    matches = [
        band
        for band in normalize_target_rate_bands(raw_bands)
        if band["minimum_target_mg"] <= target <= band["maximum_target_mg"]
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f"multiple target rate bands match {target} mg")
    return dict(matches[0])


def resolve_default_target_rate_band(target_mg: Any) -> dict[str, Any]:
    """Resolve the product-wide rate policy used until a powder overrides it."""
    bands = load_product_requirements().get("default_target_rate_bands", [])
    resolved = resolve_target_rate_band(bands, target_mg)
    if resolved is None:
        raise ValueError(f"no default target rate band covers {target_mg} mg")
    return resolved


def _piecewise_linear(target: int, anchors: list[int], values: list[float]) -> float:
    if target in anchors:
        return values[anchors.index(target)]
    if target < anchors[0]:
        left, right = 0, 1
    elif target > anchors[-1]:
        left, right = len(anchors) - 2, len(anchors) - 1
    else:
        for left in range(len(anchors) - 1):
            right = left + 1
            if anchors[left] < target < anchors[right]:
                break
    fraction = (target - anchors[left]) / (anchors[right] - anchors[left])
    return values[left] + fraction * (values[right] - values[left])


def resolve_target_profile(raw_profiles: dict[Any, Any], target_mg: Any) -> dict[str, Any]:
    """Resolve one target and report whether it was exact/interpolated/extrapolated."""
    target = validate_target_mass(target_mg)
    profiles = normalize_target_profiles(raw_profiles)
    anchors = sorted(profiles)
    if target < anchors[0] or target > anchors[-1]:
        resolution = "extrapolated"
    elif target in profiles:
        resolution = "exact"
    else:
        resolution = "interpolated"
    values = {
        key: float(_piecewise_linear(target, anchors, [profiles[m][key] for m in anchors]))
        for key in INTERPOLATABLE_TARGET_KEYS
    }
    if values["tail_taper_end_remaining_mg"] >= values["tail_taper_start_remaining_mg"]:
        values["tail_taper_end_remaining_mg"] = (
            values["tail_taper_start_remaining_mg"] * 0.3
        )
    return {
        "target_mg": target,
        "resolution": resolution,
        "anchor_masses_mg": anchors,
        "profile": values,
    }


def resolve_partial_target_overrides(
    raw_profiles: dict[Any, Any], target_mg: Any
) -> dict[str, float]:
    """Interpolate every numeric field present in legacy partial overrides."""
    target = validate_target_mass(target_mg)
    profiles = normalize_target_keys(raw_profiles)
    result: dict[str, float] = {}
    keys = {
        key
        for values in profiles.values()
        for key, value in values.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    for key in keys:
        anchors = [mass for mass, values in profiles.items() if key in values]
        values = [float(profiles[mass][key]) for mass in anchors]
        if len(anchors) == 1:
            result[key] = values[0]
        elif anchors:
            result[key] = float(_piecewise_linear(target, anchors, values))
    return result


def validate_control_profile(profile: dict[str, Any]) -> dict[str, Any]:
    required = ("powder_id", "powder_name", "status", "recommended_preset_id")
    for key in required:
        if not isinstance(profile.get(key), str) or not profile[key].strip():
            raise ValueError(f"control profile is missing {key}")
    controller = profile.get("recommended_controller")
    if not isinstance(controller, dict):
        raise ValueError("control profile is missing recommended_controller")
    normalize_target_profiles(profile.get("target_profiles", {}))
    normalize_target_rate_bands(profile.get("target_rate_bands", []))
    normalize_exact_target_overrides(profile.get("exact_target_overrides", {}))
    return profile


def load_control_profile(
    powder_id: str,
    profile_dir: Path | str = DEFAULT_PROFILE_DIR,
) -> dict[str, Any] | None:
    if not powder_id or Path(powder_id).name != powder_id:
        return None
    path = Path(profile_dir) / f"{powder_id}.json"
    if not path.exists():
        return None
    return validate_control_profile(json.loads(path.read_text(encoding="utf-8")))


def list_control_profiles(
    profile_dir: Path | str = DEFAULT_PROFILE_DIR,
) -> list[dict[str, Any]]:
    directory = Path(profile_dir)
    if not directory.exists():
        return []
    summaries = []
    for path in sorted(directory.glob("*.json")):
        try:
            profile = validate_control_profile(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        summaries.append({
            "powder_id": profile["powder_id"],
            "powder_name": profile["powder_name"],
            "status": profile["status"],
            "recommended_preset_id": profile["recommended_preset_id"],
            "anchor_masses_mg": sorted(normalize_target_profiles(profile["target_profiles"])),
            "generation_warnings": profile.get("generation_warnings", []),
        })
    return summaries


def resolve_control_profile(profile: dict[str, Any], target_mg: Any) -> dict[str, Any]:
    validate_control_profile(profile)
    resolved = resolve_target_profile(profile["target_profiles"], target_mg)
    rate_band = resolve_target_rate_band(profile.get("target_rate_bands", []), target_mg)
    rate_band_source = "powder_profile"
    if rate_band is None:
        rate_band = resolve_default_target_rate_band(target_mg)
        rate_band_source = "product_default"
    target_profile = dict(resolved["profile"])
    if rate_band is not None:
        for key in STAGE_RATE_KEYS:
            if key != "settle_rate_mg_s":
                target_profile[key] = rate_band[key]
    recommended_controller = dict(profile["recommended_controller"])
    exact_target_overrides = normalize_exact_target_overrides(
        profile.get("exact_target_overrides", {})
    ).get(resolved["target_mg"], {})
    for key, value in exact_target_overrides.items():
        if key in EXACT_TARGET_PROFILE_OVERRIDE_KEYS:
            target_profile[key] = value
        elif key in EXACT_TARGET_CONTROLLER_OVERRIDE_KEYS:
            recommended_controller[key] = value
    return {
        "powder_id": profile["powder_id"],
        "powder_name": profile["powder_name"],
        "status": profile["status"],
        "recommended_preset_id": profile["recommended_preset_id"],
        "recommended_controller": recommended_controller,
        "target_resolution": {
            key: value for key, value in resolved.items() if key != "profile"
        },
        "target_profile": target_profile,
        "exact_target_overrides": dict(exact_target_overrides),
        "target_rate_band": rate_band,
        "target_rate_band_source": rate_band_source,
        "generation_warnings": list(profile.get("generation_warnings", [])),
    }


# ── draft generation (was method_generator.py) ───────────────────────────────


def build_candidate_control_profile(workspace: dict[str, Any]) -> dict[str, Any]:
    """Build a draft; measured-data gaps become warnings, never hidden defaults."""
    powder_id = str(workspace.get("powder_id", "")).strip()
    powder_name = str(workspace.get("powder_name", "")).strip()
    if not powder_id or not powder_name:
        raise ValueError("workspace must contain powder_id and powder_name")
    profiles = normalize_target_profiles(workspace.get("recommended_profiles", {}))
    target_rate_bands = normalize_target_rate_bands(
        workspace.get("target_rate_bands", [])
    )
    controller = workspace.get("recommended_controller")
    if not isinstance(controller, dict):
        raise ValueError("workspace must contain recommended_controller")

    warnings: list[str] = []
    scan_grid = workspace.get("scan_grid", [])
    pending_count = sum(1 for point in scan_grid if point.get("status") == "pending")
    if pending_count:
        warnings.append(f"{pending_count} scan points are still pending")
    for region_name in ("safe_coarse_region", "safe_fine_region"):
        region = workspace.get(region_name, {})
        if region.get("confidence") in (None, "low"):
            warnings.append(f"{region_name} has low or unspecified confidence")
    if not workspace.get("path_dependency", {}).get("notes"):
        warnings.append("transition/path-dependency evidence is missing")
    tail = workspace.get("tail_behavior", {})
    if not isinstance(tail.get("mean_tail_mg"), (int, float)):
        warnings.append("measured stop-tail evidence is missing")

    return {
        "schema_version": 1,
        "powder_id": powder_id,
        "powder_name": powder_name,
        "status": "draft",
        "recommended_preset_id": workspace.get("recommended_preset_id", ""),
        "recommended_controller": dict(controller),
        "target_profiles": {str(mass): values for mass, values in profiles.items()},
        "target_rate_bands": target_rate_bands,
        "generation_warnings": warnings,
        "source_workspace_updated_at": workspace.get("updated_at"),
    }
