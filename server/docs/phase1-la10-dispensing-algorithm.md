# Phase-One LA10 Dispensing Algorithm Framework

## Scope

The algorithm controls powder output with four adjustable variables: LA10
window position, vibration frequency, vibration duty cycle, and vibration
duration. Window position is treated as the feeder opening command, not as a
mass command. A higher opening, frequency, duty cycle, or duration may produce
more powder, but the relationship is powder- and head-dependent and must be
measured.

The framework supports 100 mg and 500 mg recipes first. It does not send
serial commands. The state machine must perform all interlocks, tare, movement
confirmation, stop confirmation, and exception handling.

## Parameterization

The action vector is:

```text
u = [window_position_units, frequency_hz, duty_permyriad, duration_ms]
```

The initial approved window range is 350 to 800 position units, centered on
the current operating region near 500. Frequency is 10 to 80 Hz and duty is
1000 to 5000 (10% to 50%). A noise budget couples frequency and duty:

```text
frequency_hz * duty_permyriad <= noise_budget_hz_permyriad
```

The default budget is 90000. It preserves 30 Hz / 30% while reducing the
maximum duty to 15% at 60 Hz. The budget is a conservative safety and noise
constraint, not a physical yield model.

## Four-Stage Decision

For each stable measurement, the planner calculates:

```text
remaining_predicted = target_mg - measured_mg - predicted_tail_mg
```

COARSE commands the L0 high-throughput action while preserving the slow-stage
reserve. SLOW commands one bounded lower-yield action while preserving the
fine-stage reserve. FINE commands no more than half of the predicted remaining
mass using low frequency, low duty, and a short pulse. SETTLE issues no powder
command and waits for the weighing layer's stability rule.

No predicted value can accept a task. Final acceptance requires a stable,
communication-valid mass from AT8811C and recipe-specific overweight limits.

## 100 mg And 500 mg Profiles

`config/algorithm/l0_profiles.example.json` contains two example L0 rows.
The 100 mg profile begins with position 500, 30 Hz, 30%, and a reference yield
of 25 mg/s. The 500 mg profile begins with position 550, 40 Hz, 22%, and a
reference yield of 50 mg/s. These are placeholders for the calibration plan,
not validated production settings.

Profiles are selected by powder type, powder batch, feeder head, recipe
version, and target mass. Intermediate targets use linear interpolation only
between rows with the same first four keys. A new powder or head has no valid
profile and must fall back to a controlled calibration procedure.

## Calibration And Optimization

Each calibration observation records the action, stable mass delta,
communication state, stability, and alarms. Only valid observations contribute
to the local yield estimate in mg/s. The estimate uses nearby samples in the
position/frequency/duty space; it is intentionally simple and explainable.

The collection entry point is `scripts/calibrate_feed_yield.py`. It defaults to
one low-energy 10 Hz / 10% / 1 s preview and requires `--execute` to touch
hardware. It tares first, validates the LA10 window position, reads stable mass
before and after vibration, verifies vibration stop, and writes a complete JSON
record under `data/calibration/`.
`LocalYieldEstimator.from_directory()` loads only completed, stable records from
that directory. `plan_dispense.py` uses those records automatically when they
are present.

ILC is task-to-task only. After an accepted, stable, alarm-free task, it can
recommend a bounded coarse-duration scale for the next task. It does not alter
window position, frequency, or duty automatically in phase one. The default is
shadow mode with a 5% maximum update per task. Any communication fault,
instability, alarm, manual intervention, or rejection freezes learning.

## Integration Contract

The task state machine should call `FourStagePlanner.next_decision()` only
after a valid stable sample, execute the returned `FeedAction`, then capture
the actual command and resulting mass trace. The data layer must persist the
selected L0 profile ID, calibration version, command trace, mass trace,
predicted tail mass, and ILC recommendation for replay.
