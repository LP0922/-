"""One supervised empty-feeder diagnostic; never starts vibration or retries a move.

The dashboard must be stopped first to release COM8. Output is a JSON report.
This tool does not change the production motion/dispensing algorithm.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from powder_sampling_control.device_adapters.la10_modbus_rtu import LA10Config, LA10ModbusRTU


def diagnose(device, *, clock=time):
    started = clock.monotonic()
    report = {
        "test_type": "empty_window_diagnostic",
        "started_at": datetime.now().astimezone().isoformat(),
        "user_confirmed_empty": True,
        "targets": [350, 370, 350],
        "speed_mm_s": 1.0,
        "tolerance_units": 10,
        "serial_retries": 0,
        "motion_retries": 0,
        "vibration_start_commands": 0,
        "result": "running",
        "commands": [],
        "samples": [],
        "segments": [],
    }

    def read(phase):
        begin = clock.monotonic()
        status = device.read_status()
        report["samples"].append({
            "elapsed_s": round(clock.monotonic() - started, 4),
            "read_duration_s": round(clock.monotonic() - begin, 4),
            "phase": phase, **asdict(status),
        })
        if status.fault_bits:
            raise RuntimeError(f"fault bits 0x{status.fault_bits:04X}")
        if not 330 <= status.position_units <= 390:
            raise RuntimeError(f"outside diagnostic safety envelope: {status.position_units}")
        return status

    def observe(phase, seconds):
        deadline = clock.monotonic() + seconds
        offset = len(report["samples"])
        status = None
        while clock.monotonic() < deadline:
            status = read(phase)
            clock.sleep(0.1)
        return status, report["samples"][offset:]

    def require_stopped(status, samples, target=None):
        tail = samples[-3:]
        if len(tail) < 3 or any(s["is_running"] for s in tail):
            raise RuntimeError("window was not stopped at end of observation")
        if max(s["position_units"] for s in tail) - min(s["position_units"] for s in tail) > 3:
            raise RuntimeError("position was not stable at end of observation")
        if target is not None and abs(status.position_units - target) > 10:
            raise RuntimeError(f"off target: requested={target}, actual={status.position_units}")

    def record_write(kind, action, **details):
        item = {"kind": kind, "elapsed_s": round(clock.monotonic() - started, 4), **details}
        report["commands"].append(item)
        action()
        item["acknowledged"] = True

    try:
        initial = read("initial")
        vibration = device.read_vibration_settings()
        report["vibration_before"] = asdict(vibration)
        if initial.is_running or vibration.enabled:
            raise RuntimeError("device is not idle; no diagnostic motion permitted")
        status, baseline = observe("baseline", 2.0)
        require_stopped(status, baseline, 350)
        report["baseline_result_codes"] = sorted({s["last_result"] for s in baseline})
        if status.last_result != 0:
            raise RuntimeError("nonzero result at final baseline read; no motion issued")

        for index, target in enumerate(report["targets"]):
            segment = {"target": target, "before": status.position_units}
            report["segments"].append(segment)
            if abs(target - status.position_units) <= 10:
                segment.update({"skipped_within_tolerance": True, "after": status.position_units})
                continue
            # Recheck the actual device directly immediately before the ONLY command.
            status = read(f"pre_command_{index}")
            if status.is_running or status.last_result != 0:
                raise RuntimeError("running/nonzero result before command; no motion issued")
            if device.read_vibration_settings().enabled:
                raise RuntimeError("unexpected vibration before motion")
            delta = target - status.position_units
            distance_register = max(1, round(abs(delta) / 2))
            if distance_register > 20:
                raise RuntimeError("diagnostic relative travel exceeds 0.20 mm")
            record_write("enable", device.enable)
            record_write(
                "relative_motion_0x10",
                lambda: device.move_relative(
                    extend=delta > 0, distance_mm=distance_register / 100, speed_mm_s=1.0,
                ), target=target, from_position=status.position_units,
                distance_register=distance_register, extend=delta > 0,
            )
            status, samples = observe(f"move_to_{target}", 4.0)
            require_stopped(status, samples, target)
            codes = sorted({s["last_result"] for s in samples})
            segment.update({"after": status.position_units, "result_codes": codes,
                            "position_reached": True, "saw_running": any(s["is_running"] for s in samples)})
            if any(codes):
                report["result"] = "result_code_anomaly"
                report["reason"] = "nonzero code observed; no subsequent move/correction issued"
                break
        else:
            report["result"] = "position_round_trip_completed"
    except Exception as error:
        report["result"] = "aborted"
        report["error"] = str(error)
    finally:
        # Stop-only cleanup. Never attempt an automatic return/correction on failure.
        try:
            status = device.read_status()
            vibration = device.read_vibration_settings()
            if vibration.enabled:
                record_write("stop_vibration", device.stop_vibration)
            if status.is_running or report["result"] == "aborted":
                record_write("emergency_stop", device.emergency_stop)
            status, cleanup = observe("final_observation", 1.0)
            require_stopped(status, cleanup)
            vibration = device.read_vibration_settings()
            report["final_status"] = asdict(status)
            report["vibration_after"] = asdict(vibration)
            report["stopped_confirmed"] = not status.is_running and not vibration.enabled
        except Exception as error:
            report["cleanup_error"] = str(error)
            report["stopped_confirmed"] = False
            # Communication may have failed; make best-effort stop-only writes.
            for kind, action in (("stop_vibration", device.stop_vibration),
                                 ("emergency_stop", device.emergency_stop)):
                try:
                    record_write(kind, action)
                except Exception as stop_error:
                    report.setdefault("stop_errors", []).append(str(stop_error))
        report["elapsed_s"] = round(clock.monotonic() - started, 4)
        report["finished_at"] = datetime.now().astimezone().isoformat()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="COM8")
    parser.add_argument("--confirm-empty-and-clear", action="store_true")
    args = parser.parse_args()
    if not args.confirm_empty_and_clear:
        parser.error("explicit empty feeder and clear motion area confirmation is required")
    device = LA10ModbusRTU(LA10Config(port=args.port, timeout_s=0.5, retries=0))
    try:
        report = diagnose(device)
        report["port"] = args.port
        print(json.dumps(report, ensure_ascii=False))
    finally:
        device.close()


if __name__ == "__main__":
    main()
