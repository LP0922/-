"""Powder fingerprint engine — probe execution, feature extraction, classification, storage.

Features are computed directly from raw balance mass readings (no model-based
estimator) to keep the probe simple and transparent.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from powder_sampling_control.dispensing_algorithm.feedback_profiles import (
    powder_classification_params,
)
from powder_sampling_control.dispensing_algorithm.control_profiles import (
    normalize_target_keys,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FINGERPRINTS_DIR = PROJECT_ROOT / "data" / "powder_fingerprints"
MAX_VERSIONS = 3

# --- Safety limits ---
PROBE_SAFETY_RATE_LIMIT_MG_S = 120.0
PROBE_SAFETY_MASS_LIMIT_MG = 3000.0
PROBE_TIMEOUT_S = 30.0
PROBE_DEFAULT_DURATION_S = 10.0
PROBE_DEFAULT_FREQUENCY_HZ = 40
PROBE_DEFAULT_DUTY_PERMYRIAD = 2000
PROBE_DEFAULT_WINDOW_POSITION = 250

# --- Window / motion constants ---
_POSITION_UNITS_PER_MM = 200
_MOTION_REGISTER_UNITS_PER_MM = 100
_POSITION_TOLERANCE_UNITS = 100
_WINDOW_MOVE_SPEED_MM_S = 1.0
_WINDOW_MOVE_TIMEOUT_S = 10.0

# --- Feature extraction ---
STEADY_EXCLUDE_FRACTION = 0.20  # exclude first 20% of vibration data
SETTLE_MASS_CHANGE_THRESHOLD_MG = 0.5  # mass change < 0.5 mg over a window → settled
SETTLE_WINDOW_S = 1.0
SETTLE_TIMEOUT_S = 5.0

# --- Classification thresholds ---
LOW_FLOW_THRESHOLD_MG_S = 25.0
HIGH_FLOW_THRESHOLD_MG_S = 60.0
CV_STABLE_THRESHOLD_PCT = 20.0
CV_UNSTABLE_THRESHOLD_PCT = 40.0
STARTUP_STICKY_THRESHOLD_S = 4.0
STARTUP_MASS_THRESHOLD_MG = 1.0  # mass gain threshold for startup detection


def _powder_id_from_name(name: str) -> str:
    safe = name.strip().lower().replace(" ", "-")
    suffix = uuid.uuid4().hex[:6]
    return f"{safe}-{suffix}"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ProbeParameters:
    frequency_hz: int = PROBE_DEFAULT_FREQUENCY_HZ
    duty_permyriad: int = PROBE_DEFAULT_DUTY_PERMYRIAD
    window_position_units: int = PROBE_DEFAULT_WINDOW_POSITION
    duration_s: float = PROBE_DEFAULT_DURATION_S


@dataclass
class FeatureVector:
    startup_delay_s: float = 0.0
    steady_rate_mg_s: float = 0.0
    rate_cv_pct: float = 0.0
    tail_mass_mg: float = 0.0
    settling_time_s: float = 0.0


@dataclass
class Classification:
    category: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class ProbeRawSummary:
    startup_phase: list[dict] = field(default_factory=list)
    steady_phase: list[dict] = field(default_factory=list)
    settling_phase: list[dict] = field(default_factory=list)


@dataclass
class PowderFingerprint:
    powder_id: str = ""
    powder_name: str = ""
    created_at: str = ""
    probe_parameters: ProbeParameters = field(default_factory=ProbeParameters)
    feature_vector: FeatureVector = field(default_factory=FeatureVector)
    classification: Classification = field(default_factory=Classification)
    applied_profile: dict = field(default_factory=dict)
    probe_raw_summary: ProbeRawSummary = field(default_factory=ProbeRawSummary)

    def to_dict(self) -> dict:
        return {
            "powder_id": self.powder_id,
            "powder_name": self.powder_name,
            "created_at": self.created_at,
            "probe_parameters": asdict(self.probe_parameters),
            "feature_vector": asdict(self.feature_vector),
            "classification": asdict(self.classification),
            "applied_profile": self.applied_profile,
            "probe_raw_summary": asdict(self.probe_raw_summary),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PowderFingerprint":
        applied_profile = dict(d.get("applied_profile", {}))
        raw_overrides = applied_profile.get("profile_overrides")
        if raw_overrides:
            applied_profile["profile_overrides"] = normalize_target_keys(
                raw_overrides
            )
        return cls(
            powder_id=d.get("powder_id", ""),
            powder_name=d.get("powder_name", ""),
            created_at=d.get("created_at", ""),
            probe_parameters=ProbeParameters(**d.get("probe_parameters", {})),
            feature_vector=FeatureVector(**d.get("feature_vector", {})),
            classification=Classification(**d.get("classification", {})),
            applied_profile=applied_profile,
            probe_raw_summary=ProbeRawSummary(**d.get("probe_raw_summary", {})),
        )


# ---------------------------------------------------------------------------
# Probe execution
# ---------------------------------------------------------------------------

def _read_mass(reader) -> float:
    """Read balance mass in mg, clamped to >= 0."""
    raw = reader._at.read_measurement()
    if raw.mass_mg is not None:
        return max(0.0, float(raw.mass_mg))
    # Fallback: use raw count when mass_mg is None
    return max(0.0, float(raw.raw_count))


def execute_probe(
    reader,
    probe_params: ProbeParameters,
    cancel_event,
    progress_callback: Callable[[str, float], None],
) -> PowderFingerprint:
    """Run a powder probe test synchronously (caller runs this in a thread)."""
    started_at = time.monotonic()
    samples: list[dict] = []
    settling_samples: list[dict] = []
    vibration_started_at: float | None = None
    vibration_started = False

    try:
        # ---- 1. Tare ----
        progress_callback("去皮中", 3.0)
        with reader._lock:
            reader._at.zero(authorized=True)
        tare_deadline = time.monotonic() + 5.0
        while time.monotonic() < tare_deadline:
            if cancel_event.is_set():
                raise RuntimeError("探针被取消")
            time.sleep(0.1)

        # ---- 2. Move window to probe position ----
        progress_callback("窗口定位", 7.0)
        with reader._lock:
            window_status = reader._la10.read_status()
        current_pos = window_status.position_units
        delta = abs(probe_params.window_position_units - current_pos)
        if delta > _POSITION_TOLERANCE_UNITS:
            extend = probe_params.window_position_units > current_pos
            dist_reg = max(1, round(delta / _POSITION_UNITS_PER_MM * _MOTION_REGISTER_UNITS_PER_MM))
            with reader._lock:
                reader._la10.enable()
                reader._la10.move_relative(
                    extend=extend,
                    distance_mm=dist_reg / _MOTION_REGISTER_UNITS_PER_MM,
                    speed_mm_s=_WINDOW_MOVE_SPEED_MM_S,
                )
            move_deadline = time.monotonic() + _WINDOW_MOVE_TIMEOUT_S
            while time.monotonic() < move_deadline:
                if cancel_event.is_set():
                    raise RuntimeError("探针被取消")
                with reader._lock:
                    cur = reader._la10.read_status()
                if not cur.is_running:
                    break
                time.sleep(0.1)
            with reader._lock:
                final = reader._la10.read_status()
            if abs(final.position_units - probe_params.window_position_units) > _POSITION_TOLERANCE_UNITS:
                raise RuntimeError(f"窗口未到位: 实际 {final.position_units}, 目标 {probe_params.window_position_units}")

        # ---- 3. Start vibration ----
        progress_callback("振动中", 10.0)
        with reader._lock:
            reader._la10.start_vibration(
                frequency_hz=probe_params.frequency_hz,
                duty_permyriad=probe_params.duty_permyriad,
            )
            vibration_check = reader._la10.read_vibration_settings()
        if not vibration_check.enabled:
            raise RuntimeError("LA10 振动未能启动确认")
        vibration_started = True
        vibration_started_at = time.monotonic()

        # ---- 4. Collect raw mass during vibration ----
        while time.monotonic() - vibration_started_at < probe_params.duration_s:
            elapsed = time.monotonic() - started_at
            if elapsed > PROBE_TIMEOUT_S:
                raise RuntimeError("探针超时")
            if cancel_event.is_set():
                raise RuntimeError("探针被取消")

            with reader._lock:
                mass_mg = _read_mass(reader)
            now = time.monotonic()

            samples.append({
                "elapsed_s": round(now - vibration_started_at, 3),
                "mass_mg": round(mass_mg, 2),
            })

            # Safety checks
            if mass_mg >= PROBE_SAFETY_MASS_LIMIT_MG:
                raise RuntimeError(f"质量达到 {mass_mg:.0f} mg，触发安全停机")

            # Progress: 10% → 80%
            vib_pct = (time.monotonic() - vibration_started_at) / probe_params.duration_s
            progress_callback("振动中", 10.0 + 70.0 * min(vib_pct, 1.0))
            time.sleep(0.1)

        # ---- 5. Stop vibration ----
        progress_callback("停振中", 82.0)
        with reader._lock:
            reader._la10.stop_vibration()
        vibration_stopped_at = time.monotonic()
        mass_at_stop = samples[-1]["mass_mg"] if samples else 0.0

        # ---- 6. Settling phase ----
        progress_callback("沉降等待", 85.0)
        settle_deadline = time.monotonic() + SETTLE_TIMEOUT_S
        settle_started_at = None

        while time.monotonic() < settle_deadline:
            if cancel_event.is_set():
                raise RuntimeError("探针被取消")

            with reader._lock:
                mass_mg = _read_mass(reader)
            now = time.monotonic()

            settling_samples.append({
                "elapsed_s": round(now - vibration_stopped_at, 3),
                "mass_mg": round(mass_mg, 2),
            })

            # Check if mass has stabilized: last {SETTLE_WINDOW_S}s spread < threshold
            if len(settling_samples) >= 5:
                recent = [s["mass_mg"] for s in settling_samples
                          if now - (vibration_stopped_at + s["elapsed_s"]) < SETTLE_WINDOW_S]
                if recent and (max(recent) - min(recent)) < SETTLE_MASS_CHANGE_THRESHOLD_MG:
                    if settle_started_at is None:
                        settle_started_at = now
                    # Need 5 consecutive stable points
                    recent_check = settling_samples[-5:]
                    if len(recent_check) >= 5:
                        masses = [s["mass_mg"] for s in recent_check]
                        if (max(masses) - min(masses)) < SETTLE_MASS_CHANGE_THRESHOLD_MG:
                            break
                else:
                    settle_started_at = None

            settle_pct = (time.monotonic() - vibration_stopped_at) / SETTLE_TIMEOUT_S
            progress_callback("沉降等待", 85.0 + 10.0 * min(settle_pct, 1.0))
            time.sleep(0.1)

        final_mass = settling_samples[-1]["mass_mg"] if settling_samples else mass_at_stop
        tail_mass = final_mass - mass_at_stop
        settling_time = (settle_started_at - vibration_stopped_at) if settle_started_at is not None else SETTLE_TIMEOUT_S

        # ---- 7. Feature extraction from raw mass data ----
        progress_callback("特征提取", 96.0)
        features = _extract_features(samples, mass_at_stop, tail_mass, settling_time, vibration_started_at)

        # ---- 8. Classification ----
        classification = _classify(features, probe_params)

        # ---- 9. Build fingerprint ----
        progress_callback("分类完成", 99.0)
        applied_profile = powder_classification_params(classification.category, classification.tags)

        raw_summary = ProbeRawSummary(
            startup_phase=samples[:max(1, int(len(samples) * STEADY_EXCLUDE_FRACTION))],
            steady_phase=samples,
            settling_phase=settling_samples,
        )

        fingerprint = PowderFingerprint(
            powder_id="",
            powder_name="",
            created_at=datetime.now(timezone.utc).isoformat(),
            probe_parameters=probe_params,
            feature_vector=features,
            classification=classification,
            applied_profile=applied_profile,
            probe_raw_summary=raw_summary,
        )

        progress_callback("完成", 100.0)
        return fingerprint

    finally:
        if vibration_started:
            try:
                with reader._lock:
                    reader._la10.stop_vibration()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Feature extraction (raw mass based)
# ---------------------------------------------------------------------------

def _extract_features(
    samples: list[dict],
    mass_at_stop: float,
    tail_mass: float,
    settling_time: float,
    vibration_started_at: float | None,
) -> FeatureVector:
    """Extract 5 features from raw mass vs time data."""

    if not samples or len(samples) < 3:
        return FeatureVector()

    # --- startup_delay: first sample where mass has increased by > 1 mg ---
    startup_delay = 0.0
    base_mass = samples[0]["mass_mg"]
    for s in samples:
        if s["mass_mg"] - base_mass >= STARTUP_MASS_THRESHOLD_MG:
            startup_delay = s["elapsed_s"]
            break

    # --- steady_rate: linear regression on the steady (last 80%) portion ---
    n = len(samples)
    start_idx = max(1, int(n * STEADY_EXCLUDE_FRACTION))
    steady = samples[start_idx:]
    mean_rate = 0.0
    cv_pct = 0.0

    if len(steady) >= 3:
        # Linear regression: mass = rate * time + intercept
        times = [s["elapsed_s"] for s in steady]
        masses = [s["mass_mg"] for s in steady]
        n_steady = len(steady)
        sum_t = sum(times)
        sum_m = sum(masses)
        sum_tt = sum(t * t for t in times)
        sum_tm = sum(t * m for t, m in zip(times, masses))

        denominator = n_steady * sum_tt - sum_t * sum_t
        if denominator > 0:
            mean_rate = (n_steady * sum_tm - sum_t * sum_m) / denominator
            mean_rate = max(0.0, mean_rate)

        # --- rate_cv: from per-second rate segments ---
        if n_steady > 1:
            # Compute per-second rates
            seg_rates = []
            duration = times[-1] - times[0]
            if duration >= 1.0:
                seg_count = max(2, int(duration))
                seg_width = duration / seg_count
                for i in range(seg_count):
                    seg_start = times[0] + i * seg_width
                    seg_end = seg_start + seg_width
                    seg_masses = [m for t, m in zip(times, masses) if seg_start <= t < seg_end]
                    if len(seg_masses) >= 2:
                        seg_rate = (seg_masses[-1] - seg_masses[0]) / seg_width
                        seg_rates.append(max(0.0, seg_rate))
            if seg_rates and len(seg_rates) >= 2:
                seg_mean = sum(seg_rates) / len(seg_rates)
                if seg_mean > 0:
                    seg_var = sum((r - seg_mean) ** 2 for r in seg_rates) / (len(seg_rates) - 1)
                    cv_pct = (seg_var ** 0.5) / seg_mean * 100.0

    return FeatureVector(
        startup_delay_s=round(startup_delay, 3),
        steady_rate_mg_s=round(mean_rate, 2),
        rate_cv_pct=round(cv_pct, 1),
        tail_mass_mg=round(max(0.0, tail_mass), 2),
        settling_time_s=round(max(0.0, settling_time), 3),
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _classify(features: FeatureVector, probe_params: ProbeParameters) -> Classification:
    """Rule-based classification from feature vector."""
    rate = features.steady_rate_mg_s
    if probe_params.frequency_hz != PROBE_DEFAULT_FREQUENCY_HZ:
        rate = rate * (PROBE_DEFAULT_FREQUENCY_HZ / probe_params.frequency_hz)

    if rate < LOW_FLOW_THRESHOLD_MG_S:
        category = "Low-flow"
    elif rate > HIGH_FLOW_THRESHOLD_MG_S:
        category = "High-flow"
    else:
        category = "Medium-flow"

    tags: list[str] = []
    if features.rate_cv_pct < CV_STABLE_THRESHOLD_PCT:
        tags.append("stable")
    if features.rate_cv_pct > CV_UNSTABLE_THRESHOLD_PCT:
        tags.append("unstable")
    if features.startup_delay_s > STARTUP_STICKY_THRESHOLD_S:
        tags.append("sticky")

    return Classification(category=category, tags=tags)


# ---------------------------------------------------------------------------
# Storage (file I/O)
# ---------------------------------------------------------------------------

def _fingerprint_path(powder_id: str, version: int = 0) -> Path:
    FINGERPRINTS_DIR.mkdir(parents=True, exist_ok=True)
    if version == 0:
        return FINGERPRINTS_DIR / f"{powder_id}.json"
    return FINGERPRINTS_DIR / f"{powder_id}.{version}.json"


def save_fingerprint(fingerprint: PowderFingerprint) -> Path:
    path_latest = _fingerprint_path(fingerprint.powder_id, 0)
    path_v2 = _fingerprint_path(fingerprint.powder_id, 2)
    if path_v2.exists():
        path_v2.unlink()
    path_v1 = _fingerprint_path(fingerprint.powder_id, 1)
    if path_v1.exists():
        shutil.copy2(path_v1, path_v2)
    if path_latest.exists():
        shutil.copy2(path_latest, path_v1)
    path_latest.write_text(
        json.dumps(fingerprint.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path_latest


def load_fingerprint(powder_id: str) -> PowderFingerprint | None:
    path = _fingerprint_path(powder_id, 0)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return PowderFingerprint.from_dict(data)
    except Exception:
        return None


def list_fingerprints() -> list[dict]:
    FINGERPRINTS_DIR.mkdir(parents=True, exist_ok=True)
    result = []
    for path in sorted(FINGERPRINTS_DIR.glob("*.json")):
        if path.name.endswith((".1.json", ".2.json")):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result.append({
                "powder_id": data.get("powder_id", ""),
                "powder_name": data.get("powder_name", ""),
                "created_at": data.get("created_at", ""),
                "category": data.get("classification", {}).get("category", ""),
                "tags": data.get("classification", {}).get("tags", []),
                "steady_rate_mg_s": data.get("feature_vector", {}).get("steady_rate_mg_s", 0),
            })
        except Exception:
            continue
    return result


def delete_fingerprint(powder_id: str) -> bool:
    deleted = False
    for version in (0, 1, 2):
        path = _fingerprint_path(powder_id, version)
        if path.exists():
            path.unlink()
            deleted = True
    return deleted


def apply_fingerprint(fingerprint: PowderFingerprint) -> dict:
    return {
        "powder_id": fingerprint.powder_id,
        "powder_name": fingerprint.powder_name,
        "category": fingerprint.classification.category,
        "tags": fingerprint.classification.tags,
        "preset_id": fingerprint.applied_profile.get("preset_id", ""),
        "initial": fingerprint.applied_profile.get("initial", {}),
        "maximum_flow_rate_mg_s": fingerprint.applied_profile.get("maximum_flow_rate_mg_s", 30.0),
        "fixed_tail_mass_mg": fingerprint.applied_profile.get("fixed_tail_mass_mg", 2.0),
        "settle_confirmations_delta": fingerprint.applied_profile.get("settle_confirmations_delta", 0),
        "dead_zone_multiplier": fingerprint.applied_profile.get("dead_zone_multiplier", 1.0),
        "profile_overrides": fingerprint.applied_profile.get("profile_overrides", {}),
        "duty_step_per_update": fingerprint.applied_profile.get("duty_step_per_update", 50),
        "emergency_duty_step_per_update": fingerprint.applied_profile.get("emergency_duty_step_per_update", 200),
        "position_feedback_enabled": fingerprint.applied_profile.get("position_feedback_enabled", False),
        "force_stop_offset_mg": fingerprint.applied_profile.get("force_stop_offset_mg", 10.0),
        "stall_recovery_enabled": fingerprint.applied_profile.get("stall_recovery_enabled", False),
        "stall_recovery_observation_window_s": fingerprint.applied_profile.get("stall_recovery_observation_window_s", 3.0),
        "stall_recovery_min_gain_mg": fingerprint.applied_profile.get("stall_recovery_min_gain_mg", 2.0),
        "stall_recovery_rate_threshold_mg_s": fingerprint.applied_profile.get("stall_recovery_rate_threshold_mg_s", 1.0),
        "stall_recovery_resume_rate_mg_s": fingerprint.applied_profile.get("stall_recovery_resume_rate_mg_s", 2.0),
        "stall_recovery_retry_s": fingerprint.applied_profile.get("stall_recovery_retry_s", 3.0),
        "stall_recovery_window_step_units": fingerprint.applied_profile.get("stall_recovery_window_step_units", 25),
        "stall_recovery_max_window_position_units": fingerprint.applied_profile.get("stall_recovery_max_window_position_units", 400),
        "stall_recovery_max_attempts": fingerprint.applied_profile.get("stall_recovery_max_attempts", 2),
        "stall_recovery_disable_remaining_mg": fingerprint.applied_profile.get("stall_recovery_disable_remaining_mg", 50.0),
    }
