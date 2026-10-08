# Scripts

Standalone entry points were consolidated into three subcommand CLIs plus the
long-running service. Run any file with `--help` for the full option list.

## plan_cli.py — offline algorithm previews (no hardware)

    python plan_cli.py four-stage --target-mg 500        # was plan_dispense.py
    python plan_cli.py feedback 500 0 --frequency-hz ... # was plan_feedback_dispense.py
    python plan_cli.py window-pid 480 --target-mg 500    # was plan_window_pid_dispense.py
    python plan_cli.py taper 480 --json                  # was plan_continuous_taper_dispense.py
    python plan_cli.py replay run.json                   # was replay_dynamic_rate_planner.py
    python plan_cli.py profile POWDER_ID [--write]       # was generate_control_profile.py

The control-profile workflow still follows `docs/control-profile-experiment-steps.md`
before generated values are treated as qualified control settings.

## device_maintenance.py — calibration, diagnostics, backend tests

    python device_maintenance.py calibrate-scale [--execute]   # was calibrate_at8811c_scale.py
    python device_maintenance.py calibrate-yield [--execute]   # was calibrate_feed_yield.py
    python device_maintenance.py monitor-drift                 # was monitor_at8811c_drift.py
    python device_maintenance.py diagnose-empty                # was diagnose_la10_empty_motion.py
    python device_maintenance.py scan-startup [--execute]      # was scan_low_rate_startup.py
    python device_maintenance.py vibration-test                # was test_vibration_feed.py
    python device_maintenance.py window-sweep                  # was test_window_position_sweep.py
    python device_maintenance.py save-result                   # was save_latest_test_result.py

`calibrate-scale` establishes the AT8811C engineering-unit conversion. It
requires an empty-scale zero point plus at least two certified reference
masses, captures consecutive stable raw counts, fits
`mass_mg = raw_count * scale_mg_per_count + offset_mg`, and writes
`config/devices/at8811c-calibration.json` only when residual and R-squared
validation pass. Run it without `--execute` to preview the procedure.

`calibrate-yield` performs one explicitly authorized physical calibration
sample: tare, move the window, vibrate, wait for stable mass, and save the
mass delta plus the complete action parameters under `data/calibration/`.

Serial-port rule: only one process may own COM8/COM9. Stop the dashboard
before `calibrate-scale`, `calibrate-yield`, `monitor-drift`, or
`diagnose-empty`. `vibration-test`, `window-sweep`, `scan-startup`, and
`save-result` talk to the device backend over HTTP instead, so the dashboard
can show live data while a test runs.

## dispense_500mg.py — 500 mg closed-loop workflow

    python dispense_500mg.py plan 480 --json   # offline preview (was plan_500mg_state_dispense.py)
    python dispense_500mg.py run --execute     # physical run (was execute_500mg_state_dispense.py)
    python dispense_500mg.py run --execute --serve --port 8766
                                               # executor + live monitor page

## Service

- `device_control_server.py` — the serial-owning backend and browser dashboard.
  It polls both devices every 250 ms and shows the AT8811C live weight, state,
  diagnostic configuration, and all LA10 registers 0 through 14. It provides no
  device-control buttons.
- `device_dashboard.py` — dashboard HTML/telemetry module used by the server.

## CAD

- `cad/generate_active_powder_head.bas` — SolidWorks VBA macro that builds the
  active powder dosing head V0.1 parts, assembly, drawing, and PDF.
