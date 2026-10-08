"""Run continuous closed-loop dispensing to 500 mg on COM9 and COM8.

The vibration enable register is written once at feed start and once at the
final stop. During feeding, the local rate planner updates only frequency
register 12; duty and enable remain unchanged.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import threading
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from plan_500mg_state_dispense import TARGET_MG, calibration_profile  # noqa: E402
from dispense_500mg_dashboard import HTML  # noqa: E402
from powder_sampling_control.device_adapters import (  # noqa: E402
    AT8811CConfig,
    AT8811CModbusRTU,
    LA10Config,
    LA10ModbusRTU,
)
from powder_sampling_control.dispensing_algorithm import (  # noqa: E402
    DynamicRatePlanner,
    MassMotionEstimator,
    MassMotionEstimatorSettings,
    RatePlannerSettings,
)


POSITION_UNITS_PER_MM = 200
MOTION_UNITS_PER_MM = 100
POSITION_TOLERANCE_UNITS = 100
HARD_OVERWEIGHT_MG = 510.0
SLOW_ENTRY_MG = 420.0
FINE_ENTRY_MG = 470.0
PREDICTION_HORIZON_S = 0.75


class LiveState:
    """Thread-safe task state shared by the HTTP monitor and worker."""

    def __init__(self, args):
        self.args = args
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._snapshot = self._empty_snapshot()

    @staticmethod
    def _empty_snapshot():
        return {
            "status": "idle",
            "phase_label": "IDLE",
            "current_mass_mg": None,
            "filtered_mass_mg": None,
            "estimated_flow_mg_s": 0.0,
            "estimated_acceleration_mg_s2": 0.0,
            "estimated_jerk_mg_s3": 0.0,
            "predicted_flow_mg_s": 0.0,
            "predicted_mass_mg": None,
            "target_flow_mg_s": 10.0,
            "frequency_update_count": 0,
            "overspeed_active": False,
            "predicted_tail_mg": 0.0,
            "steps": [],
            "elapsed_s": 0.0,
            "task_elapsed_s": 0.0,
            "vibration_elapsed_s": 0.0,
            "current_action_elapsed_s": 0.0,
        }

    @property
    def cancel_event(self):
        return self._cancel

    def update(self, **values):
        with self._lock:
            self._snapshot.update(values)

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def start(self):
        with self._lock:
            if self._snapshot.get("status") == "running":
                raise RuntimeError("a 500 mg task is already running")
            if not self.args.execute:
                raise RuntimeError("server must be launched with --execute for physical control")
            self._cancel.clear()
            self._snapshot = self._empty_snapshot()
            self._snapshot.update(status="running", phase_label="STARTING")
        threading.Thread(target=self._run, daemon=True).start()
        return {"accepted": True, "monitor_url": f"http://{self.args.host}:{self.args.port}"}

    def cancel(self):
        self._cancel.set()
        return {"accepted": True}

    def _run(self):
        try:
            execute(self.args, monitor=self)
        except Exception as error:
            self.update(status="failed", phase_label="FAILED", error=str(error))


def make_handler(state: LiveState):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, payload, content_type="application/json; charset=utf-8"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/snapshot":
                self._send(200, state.snapshot())
            else:
                self.send_error(404)

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                if path == "/api/start":
                    self._send(202, state.start())
                elif path == "/api/cancel":
                    self._send(202, state.cancel())
                else:
                    self.send_error(404)
            except Exception as error:
                self._send(409, {"error": str(error)})

        def log_message(self, _format, *_args):
            return

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="authorize physical movement, tare, and vibration")
    parser.add_argument("--at-port", default="COM9")
    parser.add_argument("--la10-port", default="COM8")
    parser.add_argument("--task-timeout-s", type=float, default=240.0)
    parser.add_argument("--stable-timeout-s", type=float, default=15.0)
    parser.add_argument("--sample-interval-s", type=float, default=0.25)
    parser.add_argument("--no-flow-timeout-s", type=float, default=15.0)
    parser.add_argument("--serve", action="store_true", help="serve the live monitor and wait for its Start button")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    return parser.parse_args()


def measurement_record(measurement) -> dict:
    record = asdict(measurement)
    record["captured_at"] = measurement.captured_at.isoformat()
    return record


def wait_for_stable(balance, timeout_s, *, on_sample=None, cancel_event=None):
    deadline = time.monotonic() + timeout_s
    stable_samples = []
    latest = None
    while time.monotonic() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("task cancelled by operator")
        latest = balance.read_measurement()
        if on_sample is not None:
            on_sample(latest)
        if latest.stable:
            stable_samples.append(latest)
            stable_samples = stable_samples[-3:]
            if len(stable_samples) == 3:
                masses = [sample.mass_mg for sample in stable_samples]
                if None not in masses and max(masses) - min(masses) <= 2.0:
                    return stable_samples[-1]
        else:
            stable_samples.clear()
        time.sleep(0.25)
    raise TimeoutError(f"balance stability timeout; latest={latest}")


def ensure_window(la10: LA10ModbusRTU, target_units: int, timeout_s: float = 30.0):
    before = la10.read_status()
    if before.fault_bits:
        raise RuntimeError(f"LA10 fault bits before motion: 0x{before.fault_bits:04X}")
    if before.is_running:
        raise RuntimeError("LA10 is already moving")
    error_units = abs(target_units - before.position_units)
    distance_register = round(error_units / POSITION_UNITS_PER_MM * MOTION_UNITS_PER_MM)
    if error_units <= POSITION_TOLERANCE_UNITS:
        return before, before, 0
    la10.enable()
    la10.move_relative(
        extend=target_units > before.position_units,
        distance_mm=distance_register / MOTION_UNITS_PER_MM,
        speed_mm_s=1.0,
    )
    after = la10.wait_until_stopped(timeout_s=timeout_s, require_running_transition=True)
    if after.fault_bits:
        raise RuntimeError(f"LA10 fault bits after motion: 0x{after.fault_bits:04X}")
    if after.last_result != 0:
        raise RuntimeError(f"LA10 motion result code: {after.last_result}")
    if abs(after.position_units - target_units) > POSITION_TOLERANCE_UNITS:
        raise RuntimeError(f"LA10 window outside tolerance: actual={after.position_units}, target={target_units}")
    return before, after, distance_register


def stage_action(profile, stage: str) -> dict:
    parameters = profile.coarse
    return {
        "window_position_units": parameters.window_position_units,
        "frequency_hz": parameters.frequency_hz,
        "duty_permyriad": parameters.duty_permyriad,
        "duration_ms": None,
        "control_mode": "continuous",
    }


def dashboard_steps(steps: list[dict]) -> list[dict]:
    return [
        {
            "index": step["index"],
            "state": step["state"],
            "action": step["action"],
            "mass_before_mg": step["mass_before_mg"],
            "mass_after_mg": step.get("mass_after_mg"),
            "actual_mass_gain_mg": step.get("actual_mass_gain_mg"),
            "actual_duration_s": step.get("actual_duration_s"),
            "outcome": step.get("outcome", "running"),
        }
        for step in steps
    ]


def execute(args: argparse.Namespace, monitor: LiveState | None = None) -> dict:
    if not args.execute:
        raise PermissionError("physical dispensing requires --execute")
    if min(args.task_timeout_s, args.stable_timeout_s, args.sample_interval_s, args.no_flow_timeout_s) <= 0:
        raise ValueError("timeouts and sample interval must be positive")

    profile = calibration_profile()
    rate_planner = DynamicRatePlanner(
        RatePlannerSettings(
            coarse_end_mg=SLOW_ENTRY_MG,
            slow_end_mg=FINE_ENTRY_MG,
            coarse_target_mg_s=10.0,
            slow_target_mg_s=7.0,
            fine_target_mg_s=5.0,
            min_frequency_hz=10,
            max_frequency_hz=80,
            # Keep one-hertz commands, but let severe predictive overspeed
            # unwind at roughly one command per balance sample.
            severe_update_interval_s=0.25,
            medium_update_interval_s=0.5,
            small_update_interval_s=1.0,
            near_target_update_interval_s=1.5,
        )
    )
    motion_estimator = MassMotionEstimator(
        MassMotionEstimatorSettings(prediction_horizon_s=PREDICTION_HORIZON_S)
    )
    balance = AT8811CModbusRTU(
        AT8811CConfig(port=args.at_port, scale_mg_per_count=1.0, timeout_s=1.0, retries=2)
    )
    la10 = LA10ModbusRTU(LA10Config(port=args.la10_port, timeout_s=1.0, retries=2))
    result = {
        "run_id": f"dispense-500mg-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "control_mode": "continuous_vibration",
        "target_mass_mg": TARGET_MG,
        "hard_overweight_mg": HARD_OVERWEIGHT_MG,
        "profile_id": profile.profile_id,
        "rate_planner": asdict(rate_planner.settings),
        "mass_motion_estimator": asdict(motion_estimator.settings),
        "frequency_updates": [],
        "steps": [],
        "samples": [],
    }
    started = time.monotonic()
    vibration_started_at = None
    stage_started_at = None
    vibration_enabled = False
    failure = None
    last_measurement_mg = None

    def publish(**values):
        if monitor is None:
            return
        now = time.monotonic()
        task_elapsed = round(now - started, 3)
        vibration_elapsed = round(now - vibration_started_at, 3) if vibration_started_at is not None else 0.0
        action_elapsed = round(now - stage_started_at, 3) if stage_started_at is not None else 0.0
        values.setdefault("elapsed_s", task_elapsed)
        values.setdefault("task_elapsed_s", task_elapsed)
        values.setdefault("vibration_elapsed_s", vibration_elapsed)
        values.setdefault("current_action_elapsed_s", action_elapsed)
        monitor.update(**values)

    def publish_measurement(measurement):
        publish(current_mass_mg=measurement.mass_mg, balance_stable=measurement.stable)

    cancel_event = monitor.cancel_event if monitor is not None else None

    try:
        publish(status="running", phase_label="CONNECTING", reason="Connecting to COM9 and COM8")
        vibration = la10.read_vibration_settings()
        if vibration.enabled:
            la10.stop_vibration()
            raise RuntimeError("vibration was already enabled and has been stopped; inspect before retrying")

        publish(phase_label="WINDOW", reason="Moving and verifying the LA10 window")
        window_before, window_after, distance_register = ensure_window(
            la10, profile.coarse.window_position_units
        )
        result["window_before"] = asdict(window_before)
        result["window_after"] = asdict(window_after)
        result["window_distance_register"] = distance_register
        publish(
            position_units=window_after.position_units,
            fault_bits=window_after.fault_bits,
            last_result=window_after.last_result,
            vibration_enabled=False,
        )

        publish(phase_label="TARE", reason="Taring before the single continuous vibration run")
        balance.zero(authorized=True)
        tare_after = wait_for_stable(
            balance, args.stable_timeout_s, on_sample=publish_measurement, cancel_event=cancel_event
        )
        result["tare_after"] = measurement_record(tare_after)

        initial_mass = max(0.0, float(tare_after.mass_mg))
        current_stage = "COARSE"
        current_action = stage_action(profile, current_stage)
        current_step = {
            "index": 1,
            "state": current_stage,
            "action": current_action,
            "mass_before_mg": initial_mass,
        }
        result["steps"].append(current_step)

        status = la10.read_status()
        if status.fault_bits or status.is_running:
            raise RuntimeError(
                f"LA10 unsafe before vibration: fault=0x{status.fault_bits:04X}, running={status.is_running}"
            )
        la10.start_vibration(
            frequency_hz=current_action["frequency_hz"],
            duty_permyriad=current_action["duty_permyriad"],
        )
        vibration_enabled = True
        vibration_started_at = time.monotonic()
        stage_started_at = vibration_started_at
        publish(
            phase_label="COARSE FEED",
            stage=current_stage,
            reason="ILC initial frequency applied; live flow controls frequency only",
            action=current_action,
            vibration_enabled=True,
            steps=dashboard_steps(result["steps"]),
        )

        peak_mass = initial_mass
        last_flow_at = vibration_started_at
        last_device_check = vibration_started_at
        last_frequency_update = vibration_started_at
        stop_votes = 0

        while True:
            now = time.monotonic()
            if now - started >= args.task_timeout_s:
                raise TimeoutError("500 mg continuous dispense task timeout")
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("task cancelled by operator")

            measurement = balance.read_measurement()
            raw_mass = max(0.0, float(measurement.mass_mg))
            last_measurement_mg = raw_mass
            motion = motion_estimator.update(now, raw_mass)
            filtered_mass = motion.filtered_mass_mg
            flow_mg_s = motion.rate_mg_s
            predicted_tail_mg = max(0.0, motion.predicted_mass_mg - filtered_mass)
            projected_mass = motion.predicted_mass_mg

            if raw_mass >= peak_mass + 1.0:
                peak_mass = raw_mass
                last_flow_at = now
            if now - last_flow_at >= args.no_flow_timeout_s:
                raise RuntimeError(f"no powder flow detected for {args.no_flow_timeout_s:.1f} s")
            if raw_mass > HARD_OVERWEIGHT_MG:
                raise RuntimeError(f"hard overweight boundary exceeded: {raw_mass:.1f} mg")

            rate_decision = rate_planner.decide(
                filtered_mass_mg=filtered_mass,
                measured_rate_mg_s=flow_mg_s,
                current_frequency_hz=current_action["frequency_hz"],
                acceleration_mg_s2=motion.acceleration_mg_s2,
                jerk_mg_s3=motion.jerk_mg_s3,
                predicted_mass_mg=motion.predicted_mass_mg,
                predicted_rate_mg_s=motion.predicted_rate_mg_s,
                seconds_since_frequency_change=now - last_frequency_update,
                rate_valid=motion.valid,
            )
            overspeed_active = (
                motion.valid
                and max(flow_mg_s, motion.predicted_rate_mg_s)
                > rate_decision.target_rate_mg_s * rate_planner.settings.overspeed_multiple
            )
            next_stage = rate_decision.stage.value
            stage_changed = next_stage != current_stage
            adjustment_due = (
                stage_changed
                or now - last_frequency_update >= rate_decision.next_update_interval_s
            )
            if adjustment_due and rate_decision.frequency_changed:
                previous_frequency = current_action["frequency_hz"]
                la10.update_vibration_frequency(rate_decision.next_frequency_hz)
                current_action = {
                    **current_action,
                    "frequency_hz": rate_decision.next_frequency_hz,
                }
                result["frequency_updates"].append(
                    {
                        "elapsed_s": round(now - vibration_started_at, 3),
                        "stage": next_stage,
                        "mass_mg": round(filtered_mass, 3),
                        "measured_rate_mg_s": round(flow_mg_s, 3),
                        "predicted_rate_mg_s": round(motion.predicted_rate_mg_s, 3),
                        "acceleration_mg_s2": round(motion.acceleration_mg_s2, 3),
                        "jerk_mg_s3": round(motion.jerk_mg_s3, 3),
                        "predicted_mass_mg": round(motion.predicted_mass_mg, 3),
                        "target_rate_mg_s": rate_decision.target_rate_mg_s,
                        "frequency_before_hz": previous_frequency,
                        "frequency_after_hz": rate_decision.next_frequency_hz,
                        "duty_permyriad": current_action["duty_permyriad"],
                        "reason": rate_decision.reason,
                    }
                )
                last_frequency_update = time.monotonic()

            sample = {
                "elapsed_s": round(now - vibration_started_at, 3),
                "mass_mg": raw_mass,
                "filtered_mass_mg": round(filtered_mass, 3),
                "stable": measurement.stable,
                "estimated_flow_mg_s": round(flow_mg_s, 3),
                "estimated_acceleration_mg_s2": round(motion.acceleration_mg_s2, 3),
                "estimated_jerk_mg_s3": round(motion.jerk_mg_s3, 3),
                "predicted_flow_mg_s": round(motion.predicted_rate_mg_s, 3),
                "target_flow_mg_s": rate_decision.target_rate_mg_s,
                "rate_valid": motion.valid,
                "overspeed_active": overspeed_active,
                "predicted_tail_mg": round(predicted_tail_mg, 3),
                "projected_mass_mg": round(projected_mass, 3),
                "predicted_mass_mg": round(motion.predicted_mass_mg, 3),
                "innovation_mg": round(motion.innovation_mg, 3),
                "stage": current_stage,
                "frequency_hz": current_action["frequency_hz"],
                "duty_permyriad": current_action["duty_permyriad"],
            }
            result["samples"].append(sample)

            if stage_changed:
                current_step["mass_after_mg"] = filtered_mass
                current_step["actual_mass_gain_mg"] = filtered_mass - current_step["mass_before_mg"]
                current_step["actual_duration_s"] = round(now - stage_started_at, 3)
                current_step["outcome"] = "parameters_changed"

                current_stage = next_stage
                stage_started_at = time.monotonic()
                current_step = {
                    "index": len(result["steps"]) + 1,
                    "state": current_stage,
                    "action": current_action,
                    "mass_before_mg": filtered_mass,
                }
                result["steps"].append(current_step)

            # Tail prediction slows the feeder early, but never authorizes an
            # under-target stop. Two filtered samples at/above target suppress
            # a one-sample vibration spike without waiting for hardware stable.
            stop_candidate = filtered_mass >= TARGET_MG
            stop_votes = stop_votes + 1 if stop_candidate else 0

            publish(
                phase_label=f"{current_stage} FEED",
                stage=current_stage,
                reason=rate_decision.reason,
                action=current_action,
                current_mass_mg=raw_mass,
                filtered_mass_mg=round(filtered_mass, 3),
                estimated_flow_mg_s=round(flow_mg_s, 3),
                estimated_acceleration_mg_s2=round(motion.acceleration_mg_s2, 3),
                estimated_jerk_mg_s3=round(motion.jerk_mg_s3, 3),
                predicted_flow_mg_s=round(motion.predicted_rate_mg_s, 3),
                predicted_mass_mg=round(motion.predicted_mass_mg, 3),
                target_flow_mg_s=rate_decision.target_rate_mg_s,
                planner_reason=rate_decision.reason,
                frequency_update_count=len(result["frequency_updates"]),
                frequency_updates=result["frequency_updates"][-50:],
                overspeed_active=overspeed_active,
                predicted_tail_mg=round(predicted_tail_mg, 3),
                remaining_mg=round(TARGET_MG - projected_mass, 3),
                balance_stable=measurement.stable,
                vibration_enabled=True,
                steps=dashboard_steps(result["steps"]),
            )

            if stop_votes >= 2:
                current_step["mass_after_mg"] = filtered_mass
                current_step["actual_mass_gain_mg"] = filtered_mass - current_step["mass_before_mg"]
                current_step["actual_duration_s"] = round(time.monotonic() - stage_started_at, 3)
                current_step["outcome"] = "stop_threshold_reached"
                result["stop_control"] = sample
                break

            if now - last_device_check >= 2.0:
                device_status = la10.read_status()
                if device_status.fault_bits:
                    raise RuntimeError(f"LA10 fault during feed: 0x{device_status.fault_bits:04X}")
                settings = la10.read_vibration_settings()
                if not settings.enabled:
                    raise RuntimeError("vibration enable unexpectedly cleared during continuous feed")
                last_device_check = time.monotonic()

            time.sleep(args.sample_interval_s)

        publish(phase_label="STOPPING", reason="Final stop threshold reached; disabling vibration")
        la10.stop_vibration()
        vibration_enabled = False
        stopped_at = time.monotonic()
        result["vibration_elapsed_s"] = round(stopped_at - vibration_started_at, 3)
        publish(
            phase_label="SETTLING",
            reason="Vibration stopped once; waiting for final stable mass",
            vibration_enabled=False,
            steps=dashboard_steps(result["steps"]),
        )

        final = wait_for_stable(
            balance, args.stable_timeout_s, on_sample=publish_measurement, cancel_event=cancel_event
        )
        result["final_measurement"] = measurement_record(final)
        result["final_mass_mg"] = float(final.mass_mg)
        if not TARGET_MG <= result["final_mass_mg"] <= HARD_OVERWEIGHT_MG:
            raise RuntimeError(f"final mass outside acceptance range: {result['final_mass_mg']:.1f} mg")
        result["result"] = "completed"
        publish(
            status="completed",
            phase_label="ACCEPTED",
            stage="SETTLE",
            reason="Final stable mass is within 500-510 mg",
            current_mass_mg=result["final_mass_mg"],
            filtered_mass_mg=result["final_mass_mg"],
            remaining_mg=TARGET_MG - result["final_mass_mg"],
            action=None,
            steps=dashboard_steps(result["steps"]),
        )
    except Exception as error:
        result["result"] = "failed"
        result["error"] = str(error)
        result["error_type"] = type(error).__name__
        result["error_traceback"] = traceback.format_exc()
        if last_measurement_mg is not None:
            result["last_measurement_mg"] = last_measurement_mg
        failure = error
        publish(status="failed", phase_label="FAILED", reason="Task stopped", error=str(error))
    finally:
        if vibration_enabled:
            try:
                la10.stop_vibration()
                vibration_enabled = False
            except Exception as stop_error:
                result["stop_error"] = str(stop_error)
        try:
            result["vibration_final"] = asdict(la10.read_vibration_settings())
        except Exception as read_error:
            result["vibration_final_read_error"] = str(read_error)
        result["elapsed_s"] = round(time.monotonic() - started, 3)
        result["task_elapsed_s"] = result["elapsed_s"]
        if vibration_started_at is not None and "vibration_elapsed_s" not in result:
            result["vibration_elapsed_s"] = round(time.monotonic() - vibration_started_at, 3)
        result["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        output_dir = PROJECT_ROOT / "data" / "processed"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{result['run_id']}.json"
            output_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result["output_path"] = str(output_path)
        except OSError as output_error:
            result["output_error"] = str(output_error)
        balance.close()
        la10.close()

    publish(
        status=result["result"],
        current_mass_mg=result.get("final_mass_mg", result.get("last_measurement_mg")),
        vibration_enabled=result.get("vibration_final", {}).get("enabled", False),
        steps=dashboard_steps(result["steps"]),
        elapsed_s=result["elapsed_s"],
        task_elapsed_s=result["task_elapsed_s"],
        vibration_elapsed_s=result.get("vibration_elapsed_s", 0.0),
        error=result.get("error"),
        error_type=result.get("error_type"),
        output_path=result.get("output_path"),
    )
    try:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except OSError:
        pass
    if failure is not None:
        raise failure
    return result


def main() -> int:
    args = parse_args()
    if args.serve:
        state = LiveState(args)
        server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
        print(f"500 mg continuous monitor: http://{args.host}:{args.port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            state.cancel()
        finally:
            server.server_close()
        return 0
    execute(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
