# Predictive stop v2 — 2026-08-18

## Scope

This change only adjusts predictive stopping for closed-loop dispensing. It does
not reintroduce clog recovery, enable window feedback, or alter the earlier
30%-50% duty-range fix.

## Baseline evidence

- 108 feedback runs were recorded on 2026-08-18.
- 76 complete 1000 mg runs had a mean final error of +13.14 mg.
- All complete runs stopped at the measured force-stop boundary; none used the
  predictive stop reason.
- In 57 complete 1000 mg runs without clog-recovery fields, a grid fit of the
  existing tail equation reduced mean absolute tail-model error from 10.26 mg
  (`horizon=1.0`, `fixed=3.0`) to 6.76 mg (`horizon=0.7`, `fixed=2.0`). The
  service keeps powder-specific fixed-tail overrides and changes the horizon to
  0.7 seconds.

## Changes

1. `feedback_controller.py`
   - Removed the unreachable requirement that predictive stopping must already
     be at or above the measured force-stop boundary.
   - Removed the high-rate veto after consecutive predictive confirmations.
   - Added an enable flag and decision diagnostics for candidate state and
     confirmation progress.
   - Kept the measured force stop immediate and independent of confirmations.

2. `device_control_server.py`
   - Enabled predictive stopping with two consecutive samples for targets of
     1000 mg or greater. Smaller targets remain on the existing measured-stop
     path until target-specific tail data is available.
   - Changed the prediction horizon from 1.0 s to 0.7 s.
   - Kept the 3 mg prediction target offset and target-minus-10 mg measured
     safety stop.
   - Added `algorithm_version`, `predictive_stop_config`, and per-sample
     confirmation diagnostics to JSON logs.

3. Tests
   - Replaced the obsolete test that required reaching the force-stop boundary.
   - Added tests for early predictive stop, confirmation reset, immediate force
     stop, and service-level safety settings.

## Rollback boundary

If the user requests "撤回本次修改", revert only the changes listed above and
delete this record. Preserve all unrelated working-tree changes and preserve the
earlier duty-range fix in `device_control_server.py`.

## Hardware validation

Run controlled 1000 mg trials and compare:

- predictive-stop versus force-stop counts;
- final stable mass and signed error;
- candidate mass, estimated tail and final tail;
- underweight and overweight frequency.

The measured 990 mg safety stop remains active if prediction never confirms.
