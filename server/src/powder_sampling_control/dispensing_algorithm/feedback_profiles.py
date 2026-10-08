"""Shared initial profiles for mass-feedback dispensing targets.

These values are software seeds for the live feedback controller. They are not
calibration results and should be updated only from completed, stable runs.
"""

from __future__ import annotations

from .product_requirements import load_product_requirements, validate_target_mass


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


# ── arbitrary-mass interpolation ──

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
