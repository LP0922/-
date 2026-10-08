"""Target-rate band searcher — find parameters that hold a steady 10–30 mg/s flow.

Unlike the 40 Hz single-point probe (which only yields a Low/Medium/High label),
this engine directly *searches* the (frequency, window, duty) space for the
combinations that keep the steady flow rate inside a target band.  The result is
a concrete, repeatable parameter window that the closed-loop dispenser can start
from and fine-tune locally — no unstable classification in the loop.

Search strategy (4 stages)
--------------------------
1. **STARTUP**   — vibrate at the start point; if nothing flows, step frequency
                   up then open the window until powder reliably starts.
2. **APPROACH**  — steer frequency (then window/duty at the bounds) toward the
                   band with adaptive step sizes, so a High-flow powder drops
                   fast while a Low-flow powder climbs.
3. **VERIFY**    — hold a candidate point for several repeats and confirm the
                   rate is stable (CV + interruption fraction).
4. **EXPLORE**   — probe a few neighbouring frequencies to bound the band.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

# --- Safety limits (per-step, relative to the step's own start mass) ---
SAFETY_RATE_LIMIT_MG_S = 120.0
SAFETY_MASS_LIMIT_MG = 3000.0
SAFETY_STEP_MASS_CAP_MG = 1500.0  # stop one step early if it dispenses this much

# --- Target band (the whole point of the search) ---
TARGET_RATE_RANGE_MG_S = (10.0, 30.0)

# --- Search start point + steering parameters ---
START_FREQUENCY_HZ = 40
START_DUTY_PERMYRIAD = 2000
START_WINDOW_POSITION = 250

STARTUP_LADDER_HZ = [40, 55, 70, 80]
STARTUP_STEP_DURATION_S = 4.0
APPROACH_STEP_DURATION_S = 6.0
VERIFY_STEP_DURATION_S = 8.0
VERIFY_REPEAT_COUNT = 2
EXPLORE_FREQ_OFFSET_HZ = 10

# Dual-lever steering step sizes:
#   frequency owns continuity (breaks internal bridging),
#   window owns rate, duty is the last-resort lever at a bound.
FREQUENCY_STEP_HZ = 10
WINDOW_STEP_UNITS = 50
DUTY_STEP_PERMYRIAD = 500
APPROACH_MAX_STEPS = 20

SEARCH_TIMEOUT_S = 180.0

# --- Flow-start detection ---
STARTUP_MASS_THRESHOLD_MG = 1.0

# --- Stability criteria (tunable against real scans) ---
STABLE_RATE_CV_MAX_PCT = 30.0
STABLE_RATE_INTERRUPTION_MAX_FRACTION = 0.20
INTERRUPTION_RATE_EPSILON_MG_S = 0.5
# Smooth raw rate samples before judging stability so a pulsing powder is
# judged at the scale the feedback controller actually sees, not at the 100 ms
# raw-sample scale: 5 samples × 0.1 s = 0.5 s = duty_update_interval_s.
RATE_SMOOTH_WINDOW_SAMPLES = 5

# --- Hardware bounds (mirror server validation) ---
MIN_FREQUENCY_HZ = 10
MAX_FREQUENCY_HZ = 80
MIN_DUTY_PERMYRIAD = 1000
MAX_DUTY_PERMYRIAD = 5000
MIN_WINDOW_UNITS = 100
MAX_WINDOW_UNITS = 750

# --- Window / motion constants ---
_POSITION_UNITS_PER_MM = 200
_MOTION_REGISTER_UNITS_PER_MM = 100
_POSITION_TOLERANCE_UNITS = 100
_WINDOW_MOVE_SPEED_MM_S = 1.0
_WINDOW_MOVE_TIMEOUT_S = 10.0


@dataclass
class RateSearchResult:
    powder_id: str = ""
    powder_name: str = ""
    created_at: str = ""
    target_rate_range_mg_s: list[float] = field(
        default_factory=lambda: list(TARGET_RATE_RANGE_MG_S)
    )
    search_start_params: dict = field(default_factory=dict)
    search_trace: list[dict] = field(default_factory=list)
    locked_point: dict | None = None
    stable_band: dict | None = None

    def to_dict(self) -> dict:
        return {
            "powder_id": self.powder_id,
            "powder_name": self.powder_name,
            "created_at": self.created_at,
            "target_rate_range_mg_s": self.target_rate_range_mg_s,
            "search_start_params": self.search_start_params,
            "search_trace": self.search_trace,
            "locked_point": self.locked_point,
            "stable_band": self.stable_band,
        }


def _read_mass(reader) -> float:
    """Read balance mass in mg, clamped to >= 0.

    Falls back to raw count when ``mass_mg`` is None (scale_mg_per_count not yet
    configured), matching the historical probe behaviour.
    """
    raw = reader._at.read_measurement()
    if raw.mass_mg is not None:
        return max(0.0, float(raw.mass_mg))
    return max(0.0, float(raw.raw_count))


def _move_window_to_position(reader, window_units: int, cancel_event) -> None:
    """Move the dosing-head window to *window_units* (absolute)."""
    with reader._lock:
        window_status = reader._la10.read_status()
    current_pos = window_status.position_units
    delta = abs(window_units - current_pos)
    if delta <= _POSITION_TOLERANCE_UNITS:
        return
    extend = window_units > current_pos
    dist_reg = max(1, round(delta / _POSITION_UNITS_PER_MM * _MOTION_REGISTER_UNITS_PER_MM))
    with reader._lock:
        reader._la10.enable()
        reader._la10.move_relative(
            extend=extend,
            distance_mm=dist_reg / _MOTION_REGISTER_UNITS_PER_MM,
            speed_mm_s=_WINDOW_MOVE_SPEED_MM_S,
        )
    if cancel_event.is_set():
        raise RuntimeError("速率搜索被取消")
    # Wait for the motion to actually start AND stop before reading the settled
    # position. Reading is_running immediately after move_relative returns a
    # false "stopped" (the actuator hasn't latched the run bit yet), which made
    # the old loop break early and misread the pre-move position.
    with reader._lock:
        final = reader._la10.wait_until_stopped(
            timeout_s=_WINDOW_MOVE_TIMEOUT_S,
            poll_interval_s=0.1,
            require_running_transition=True,
        )
    if abs(final.position_units - window_units) > _POSITION_TOLERANCE_UNITS:
        raise RuntimeError(f"窗口未到位: 实际 {final.position_units}, 目标 {window_units}")


def _tare_balance(reader, cancel_event, settle_s: float = 1.0) -> None:
    """Re-zero the balance and wait briefly for it to settle (per-point)."""
    with reader._lock:
        reader._at.zero(authorized=True)
    deadline = time.monotonic() + settle_s
    while time.monotonic() < deadline:
        if cancel_event.is_set():
            raise RuntimeError("速率搜索被取消")
        time.sleep(0.1)


def _moving_average(values: list[float], window: int) -> list[float]:
    """Backward moving average of *values* over *window* samples.

    Keeps the input length so downstream indices stay aligned. The first
    ``window - 1`` samples average over a shorter tail of history.
    """
    if window <= 1 or not values:
        return list(values)
    out = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        out.append(sum(values[start:i + 1]) / (i - start + 1))
    return out


def _run_step(reader, frequency_hz: int, duty_permyriad: int,
              cancel_event, duration_s: float) -> dict:
    """Vibrate at *frequency_hz* for *duration_s* and characterise the flow.

    Returns a summary dict (raw samples are discarded after feature computation):
        frequency_hz, flow_started, startup_delay_s, peak_rate_mg_s,
        mean_rate_mg_s, steady_rate_mg_s, cv_pct, interruption_fraction
    """
    summary = {
        "frequency_hz": frequency_hz,
        "duty_permyriad": duty_permyriad,
        "flow_started": False,
        "startup_delay_s": None,
        "peak_rate_mg_s": 0.0,
        "mean_rate_mg_s": 0.0,
        "steady_rate_mg_s": 0.0,
        "cv_pct": None,
        "interruption_fraction": None,
    }

    with reader._lock:
        reader._la10.start_vibration(frequency_hz=frequency_hz, duty_permyriad=duty_permyriad)
        enabled = reader._la10.read_vibration_settings()
    if not enabled.enabled:
        raise RuntimeError(f"LA10 振动未能启动确认（{frequency_hz}Hz）")

    vib_started = time.monotonic()
    base_mass = None
    last_mass = None
    last_t = None
    startup_delay = None
    rates: list[tuple[float, float]] = []  # (elapsed_s, rate)

    try:
        while time.monotonic() - vib_started < duration_s:
            if cancel_event.is_set():
                raise RuntimeError("速率搜索被取消")
            with reader._lock:
                mass = _read_mass(reader)
            now = time.monotonic()
            elapsed = now - vib_started

            if base_mass is None:
                base_mass = mass
            if startup_delay is None and (mass - base_mass) >= STARTUP_MASS_THRESHOLD_MG:
                startup_delay = elapsed
            if last_mass is not None and (now - last_t) > 0:
                rate = (mass - last_mass) / (now - last_t)
                rates.append((elapsed, rate))
            last_mass = mass
            last_t = now

            # Per-step safety: a runaway within one step is what we guard against.
            if base_mass is not None and (mass - base_mass) >= SAFETY_MASS_LIMIT_MG:
                raise RuntimeError(f"单步质量增益达到 {mass - base_mass:.0f} mg，触发安全停机")
            if base_mass is not None and (mass - base_mass) >= SAFETY_STEP_MASS_CAP_MG:
                break  # dispensing far too much — stop early, keep partial data
            time.sleep(0.1)
    finally:
        with reader._lock:
            reader._la10.stop_vibration()

    if startup_delay is not None:
        summary["flow_started"] = True
        summary["startup_delay_s"] = round(startup_delay, 3)

    if rates:
        rate_values = [r for _, r in rates]
        summary["peak_rate_mg_s"] = round(max(rate_values), 3)
        summary["mean_rate_mg_s"] = round(sum(rate_values) / len(rate_values), 3)
        steady_anchor = (startup_delay if startup_delay is not None else 0.0) + 1.0
        steady_rates = [r for t, r in rates if t >= steady_anchor]
        if steady_rates:
            smoothed = _moving_average(steady_rates, RATE_SMOOTH_WINDOW_SAMPLES)
            mean = sum(smoothed) / len(smoothed)
            summary["steady_rate_mg_s"] = round(mean, 3)
            if len(smoothed) >= 2 and mean > 0:
                variance = sum((r - mean) ** 2 for r in smoothed) / (len(smoothed) - 1)
                summary["cv_pct"] = round((variance ** 0.5) / mean * 100, 1)
            jammed = [r for r in smoothed if r <= INTERRUPTION_RATE_EPSILON_MG_S]
            summary["interruption_fraction"] = round(len(jammed) / len(smoothed), 3)

    return summary


def _is_stable(step: dict) -> bool:
    """True if *step* sits inside the target band and is stable enough."""
    lo, hi = TARGET_RATE_RANGE_MG_S
    rate = step.get("steady_rate_mg_s") or 0.0
    if not (lo <= rate <= hi):
        return False
    cv = step.get("cv_pct")
    if cv is not None and cv > STABLE_RATE_CV_MAX_PCT:
        return False
    frac = step.get("interruption_fraction")
    if frac is not None and frac > STABLE_RATE_INTERRUPTION_MAX_FRACTION:
        return False
    return True


def _steer_next(rate: float, interruption_fraction, freq: int, window: int, duty: int):
    """Return the next ``(freq, window, duty, note)`` steering a point toward the
    target band, or ``None`` if the point is a stable candidate (verify now).

    Dual-lever policy — frequency owns continuity, window owns rate, duty is the
    last-resort lever when frequency/window hit a bound:

      * interruption/bridging → raise energy (frequency first, then duty);
      * too fast (continuous)  → close window (then duty, then frequency);
      * too slow (continuous)  → open window (then duty, then frequency).
    """
    lo, hi = TARGET_RATE_RANGE_MG_S

    if interruption_fraction is not None and interruption_fraction > STABLE_RATE_INTERRUPTION_MAX_FRACTION:
        if freq < MAX_FREQUENCY_HZ:
            return freq + FREQUENCY_STEP_HZ, window, duty, f"升频解架桥 {freq + FREQUENCY_STEP_HZ}Hz"
        if duty < MAX_DUTY_PERMYRIAD:
            return freq, window, duty + DUTY_STEP_PERMYRIAD, f"升占空比解架桥 {duty + DUTY_STEP_PERMYRIAD}"
        raise RuntimeError("频率与占空比均到上限仍断流，粉末无法连续出粉")

    if rate > hi:
        if window > MIN_WINDOW_UNITS:
            return freq, window - WINDOW_STEP_UNITS, duty, f"关窗压流速 窗{window - WINDOW_STEP_UNITS}"
        if duty > MIN_DUTY_PERMYRIAD:
            return freq, window, duty - DUTY_STEP_PERMYRIAD, f"降占空比压流速 {duty - DUTY_STEP_PERMYRIAD}"
        if freq > MIN_FREQUENCY_HZ:
            return freq - FREQUENCY_STEP_HZ, window, duty, f"降频压流速 {freq - FREQUENCY_STEP_HZ}Hz"
        raise RuntimeError("窗口/占空比/频率均到下限仍超速")

    if rate < lo:
        if window < MAX_WINDOW_UNITS:
            return freq, window + WINDOW_STEP_UNITS, duty, f"开窗提流速 窗{window + WINDOW_STEP_UNITS}"
        if duty < MAX_DUTY_PERMYRIAD:
            return freq, window, duty + DUTY_STEP_PERMYRIAD, f"升占空比提流速 {duty + DUTY_STEP_PERMYRIAD}"
        if freq < MAX_FREQUENCY_HZ:
            return freq + FREQUENCY_STEP_HZ, window, duty, f"升频提流速 {freq + FREQUENCY_STEP_HZ}Hz"
        raise RuntimeError("窗口/占空比/频率均到上限仍低速")

    return None


def _run_point(reader, frequency_hz: int, duty_permyriad: int,
               window_units: int, cancel_event, duration_s: float) -> dict:
    """Move window, re-tare, vibrate, and return one measurement point."""
    _move_window_to_position(reader, window_units, cancel_event)
    _tare_balance(reader, cancel_event)
    step = _run_step(reader, frequency_hz, duty_permyriad, cancel_event, duration_s)
    step["window_units"] = window_units
    return step


def execute_rate_search(
    reader,
    cancel_event,
    progress_callback: Callable[[str, float], None],
    target_lo: float = TARGET_RATE_RANGE_MG_S[0],
    target_hi: float = TARGET_RATE_RANGE_MG_S[1],
    start_freq_hz: int = START_FREQUENCY_HZ,
    start_duty_permyriad: int = START_DUTY_PERMYRIAD,
    start_window_units: int = START_WINDOW_POSITION,
) -> RateSearchResult:
    """Run the target-rate search synchronously (caller runs this in a thread)."""
    started_at = time.monotonic()
    band = (target_lo, target_hi)
    result = RateSearchResult(
        target_rate_range_mg_s=list(band),
        search_start_params={
            "frequency_hz": start_freq_hz,
            "duty_permyriad": start_duty_permyriad,
            "window_position_units": start_window_units,
        },
    )

    freq = start_freq_hz
    duty = start_duty_permyriad
    window = start_window_units

    def _check():
        if time.monotonic() - started_at > SEARCH_TIMEOUT_S:
            raise RuntimeError("速率搜索超时")
        if cancel_event.is_set():
            raise RuntimeError("速率搜索被取消")

    def _record(phase: str, step: dict):
        result.search_trace.append({
            "phase": phase,
            "frequency_hz": step.get("frequency_hz"),
            "duty_permyriad": step.get("duty_permyriad"),
            "window_units": step.get("window_units"),
            "mean_rate_mg_s": step.get("mean_rate_mg_s"),
            "steady_rate_mg_s": step.get("steady_rate_mg_s"),
            "cv_pct": step.get("cv_pct"),
            "interruption_fraction": step.get("interruption_fraction"),
            "flow_started": step.get("flow_started"),
        })

    try:
        # ---- 0. Tare + move to start window ----
        progress_callback("去皮中", 2.0)
        _tare_balance(reader, cancel_event)
        progress_callback("窗口定位", 5.0)
        _move_window_to_position(reader, window, cancel_event)

        # ---- 1. STARTUP: establish flow ----
        progress_callback("启动定位", 6.0)
        step = _run_step(reader, freq, duty, cancel_event, STARTUP_STEP_DURATION_S)
        _record("startup", step)
        if not step["flow_started"]:
            # Step frequency up the ladder until powder starts flowing.
            for candidate in STARTUP_LADDER_HZ:
                if candidate <= freq:
                    continue
                _check()
                freq = candidate
                progress_callback(f"启动定位 {freq}Hz", 10.0 + 15.0 * (candidate / 80))
                step = _run_step(reader, freq, duty, cancel_event, STARTUP_STEP_DURATION_S)
                _record("startup", step)
                if step["flow_started"]:
                    break
            # Still nothing: open the window and retry at a high frequency.
            if not step["flow_started"]:
                while window < MAX_WINDOW_UNITS and not step["flow_started"]:
                    _check()
                    window = min(MAX_WINDOW_UNITS, window + 100)
                    _move_window_to_position(reader, window, cancel_event)
                    step = _run_step(reader, freq, duty, cancel_event, STARTUP_STEP_DURATION_S)
                    _record("startup", step)
                if not step["flow_started"]:
                    raise RuntimeError("启动失败：最高参数下仍无流量，粉末无法起振")

        # ---- 2. APPROACH: dual-lever steering ----
        # Frequency owns continuity (breaks internal bridging), window owns rate,
        # duty is the last-resort lever. See _steer_next for the decision table.
        progress_callback("双杠杆逼近", 30.0)
        approach_guard = 0
        while True:
            _check()
            approach_guard += 1
            if approach_guard > APPROACH_MAX_STEPS:
                raise RuntimeError("双杠杆逼近未收敛（步数耗尽）")

            rate = step["steady_rate_mg_s"] or 0.0
            frac = step.get("interruption_fraction")
            nxt = _steer_next(rate, frac, freq, window, duty)
            if nxt is None:
                break  # continuous + in band → verify

            freq, window, duty, note = nxt
            progress_callback(note, 30.0 + 25.0 * min(approach_guard, APPROACH_MAX_STEPS) / APPROACH_MAX_STEPS)
            step = _run_point(reader, freq, duty, window, cancel_event, APPROACH_STEP_DURATION_S)
            _record("approach", step)

        # ---- 3. VERIFY: confirm stability over repeats ----
        progress_callback("锁定验证", 65.0)
        verify_steps = [step]
        for i in range(VERIFY_REPEAT_COUNT):
            _check()
            progress_callback(f"锁定验证 {i + 1}/{VERIFY_REPEAT_COUNT}", 65.0 + 15.0 * (i + 1) / VERIFY_REPEAT_COUNT)
            s = _run_point(reader, freq, duty, window, cancel_event, VERIFY_STEP_DURATION_S)
            _record("verify", s)
            verify_steps.append(s)

        stable_steps = [s for s in verify_steps if _is_stable(s)]
        # Verification failed to hold the band → report not-converged.
        if len(stable_steps) < VERIFY_REPEAT_COUNT // 2 + 1:
            progress_callback("未锁定", 90.0)
            result.stable_band = _not_converged_band(freq, window)
            return result

        rates = [s["steady_rate_mg_s"] for s in stable_steps]
        cvs = [s["cv_pct"] for s in stable_steps if s["cv_pct"] is not None]
        locked_point = {
            "frequency_hz": freq,
            "duty_permyriad": duty,
            "window_units": window,
            "mean_rate_mg_s": round(sum(rates) / len(rates), 3),
            "cv_pct": round(sum(cvs) / len(cvs), 1) if cvs else None,
            "stable": True,
        }

        # ---- 4. EXPLORE: bound the band at neighbouring frequencies ----
        progress_callback("邻域确认", 85.0)
        neighbours = [locked_point]
        for offset in (EXPLORE_FREQ_OFFSET_HZ, -EXPLORE_FREQ_OFFSET_HZ):
            nf = freq + offset
            if not (MIN_FREQUENCY_HZ <= nf <= MAX_FREQUENCY_HZ):
                continue
            _check()
            progress_callback(f"邻域确认 {nf}Hz", 88.0)
            s = _run_point(reader, nf, duty, window, cancel_event, VERIFY_STEP_DURATION_S)
            _record("explore", s)
            if _is_stable(s):
                neighbours.append(s)

        stable_freqs = sorted({n["frequency_hz"] for n in neighbours})
        stable_windows = sorted({n.get("window_units", window) for n in neighbours})
        recommended = min(
            neighbours,
            key=lambda n: (
                n["cv_pct"] if n["cv_pct"] is not None else 999.0,
                abs(n["mean_rate_mg_s"] - (target_lo + target_hi) / 2),
            ),
        )
        result.stable_band = {
            "target_rate_range_mg_s": list(band),
            "found": True,
            "stable_point_count": len(neighbours),
            "frequency_hz_range": [stable_freqs[0], stable_freqs[-1]],
            "window_units_range": [stable_windows[0], stable_windows[-1]],
            "recommended": recommended,
            "notes": (
                f"稳定 {target_lo:.0f}–{target_hi:.0f} mg/s：频率 "
                f"{stable_freqs[0]}–{stable_freqs[-1]} Hz；推荐 {recommended['frequency_hz']} Hz / "
                f"窗 {recommended.get('window_units', window)}（CV {recommended['cv_pct']}%）"
            ),
        }
        result.locked_point = locked_point

        progress_callback("完成", 100.0)
        return result

    finally:
        try:
            with reader._lock:
                reader._la10.stop_vibration()
        except Exception:
            pass


def _not_converged_band(freq: int, window: int) -> dict:
    """Build a not-found stable_band dict for a failed verification."""
    return {
        "target_rate_range_mg_s": list(TARGET_RATE_RANGE_MG_S),
        "found": False,
        "stable_point_count": 0,
        "frequency_hz_range": None,
        "window_units_range": None,
        "recommended": None,
        "notes": (
            f"锁定验证未稳：{freq}Hz / 窗{window} 下 CV 或断流率超限，"
            f"需缩小占空比步进或更换搜索起点"
        ),
    }


def apply_rate_search(result: RateSearchResult) -> dict:
    """Map a search result to a powder-session dict for the dispenser.

    ``start_dispense`` reads ``initial`` to override the preset-derived starting
    vibration parameters, so the search's locked point becomes the dispense
    start point instead of the Low/Medium/High classification.
    """
    lo, hi = result.target_rate_range_mg_s
    point = None
    if result.stable_band and result.stable_band.get("recommended"):
        point = result.stable_band["recommended"]
    elif result.locked_point:
        point = result.locked_point
    if point is None:
        return {}

    initial = {
        "frequency_hz": int(point["frequency_hz"]),
        "duty_permyriad": int(point.get("duty_permyriad", START_DUTY_PERMYRIAD)),
        "window_position_units": int(point.get("window_units", START_WINDOW_POSITION)),
    }
    mean_rate = point.get("mean_rate_mg_s") or (lo + hi) / 2
    coarse = round(max(lo, min(hi, mean_rate)), 1)
    fine = round(max(lo * 0.6, coarse * 0.6), 1)
    profile_overrides = {
        m: {"coarse_rate_mg_s": coarse, "fine_rate_mg_s": fine}
        for m in (100, 300, 500)
    }
    band = result.stable_band or {}
    return {
        "powder_id": result.powder_id,
        "powder_name": result.powder_name,
        "category": "rate-search",
        "tags": [],
        "preset_id": None,
        "initial": initial,
        "maximum_flow_rate_mg_s": float(hi * 2.0),
        "fixed_tail_mass_mg": 3.0,
        "profile_overrides": profile_overrides,
        "duty_step_per_update": 50,
        "emergency_duty_step_per_update": 200,
        "position_feedback_enabled": False,
        "force_stop_offset_mg": 10.0,
        # Carry the search's stable band so the dashboard can render the
        # recommended frequency/window ranges (not just the single initial point).
        "rate_search": {
            "found": bool(band.get("found")),
            "frequency_hz_range": band.get("frequency_hz_range"),
            "window_units_range": band.get("window_units_range"),
            "recommended": point,
        },
    }
