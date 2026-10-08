# Dispensing Algorithm

This package plans bounded LA10 window/vibration actions. It does not open a
serial port or bypass the safety state machine.

`models.py` (L0Repository) selects an approved 100 mg / 500 mg L0 row and interpolates
only between profiles with the same powder, batch, head, and recipe version.
`four_stage_planner.py` produces coarse, slow, fine, or settle decisions from
the stable mass and predicted tail mass. `models.py` (LocalYieldEstimator) estimates local yield
from approved calibration samples. `ilc.py` provides a bounded, shadow-mode
recommendation for the next task's coarse duration.

The legacy continuous 500 mg controller is split into two pure algorithm modules:

- `mass_motion_estimator.py` applies a variable-time alpha-beta-gamma observer
  to the 1 mg balance measurements. It estimates mass, flow, acceleration and
  filtered jerk, then predicts mass and flow 0.75 seconds ahead. Raw balance
  values are never differentiated repeatedly.
- `dynamic_rate_planner.py` maps that estimated state to exactly one of three
  frequency commands: `-1 Hz`, hold, or `+1 Hz`. Predicted mass selects the
  10/7/5 mg/s control stage early. Positive acceleration blocks an unnecessary
  increase, predictive overspeed requests a decrease, and jerk is used only as
  a post-command transient guard.

ILC remains the between-run feed-forward layer: it selects the initial action.
The mass-motion estimator and rate planner are the within-run feedback layer.
The newer target-mass-independent feedback controller is in
`feedback_controller.py`. It selects a coarse threshold of 70% for targets below
100 mg, 75% for 100-200 mg, and 80% above 200 mg. After the initial L0/ILC seed,
it keeps frequency fixed, uses a fast bounded duty loop, and uses a slower
persistent-error window-position loop. Both loops consume live mass, predicted
mass, flow, acceleration, and jerk; they never open a serial port or issue
device commands. The executor remains responsible for applying duty and window
updates and for stopping vibration after the target is accepted.

The current 500 mg executor does not require the feeder to sustain an
unrealistically low 5 mg/s flow. It monitors a realizable 15 mg/s tail flow and
applies remaining-mass gain scheduling from 400 to 490 mg: duty is tapered by
up to 200 permyriad and window position by up to 50 units. The purpose is to
feed already loosened powder with progressively weaker parameters, then use the
observer's 0.75 s tail prediction for a bounded early stop.

The example L0 data in `config/algorithm/l0_profiles.example.json` is not a
production calibration. Replace it with measured stable mass deltas before
using the planner to command equipment.

## Powder control profiles

`data/control_profiles/{powder_id}.json` is the runtime bridge between a fixed
powder workspace and the common feedback controller.  Each file stores common
controller settings plus a small set of target-mass anchors.  The resolver in
`profiles.py` accepts every integer target from 100 through 1000 mg and
piecewise-linearly resolves continuous target parameters.  JSON anchor keys are
normalized to integers when loaded.

The current files are `draft` configurations derived from incomplete
workspaces.  The dashboard exposes their warnings and each submitted run logs
the profile status and whether its target was exact, interpolated, or
extrapolated.  Use `scripts/plan_cli.py profile POWDER_ID` to preview a
new draft after updating a workspace.

Use `scripts/device_maintenance.py calibrate-yield` to collect a physical
stable mass-delta sample. It is preview-only unless `--execute` is supplied.
