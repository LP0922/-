# Powder control profiles

Runtime candidate configurations for the common dispensing controller.

- One file represents one fixed powder type.
- `target_profiles` stores only calibration anchors; every integer target from
  100 through 1000 mg is resolved by piecewise linear interpolation or, while
  the current data remains incomplete, explicit extrapolation.
- `status: draft` means that the values are development seeds and require
  supervised experiments.  The API includes the status and warnings in every
  submitted run so draft data cannot be mistaken for qualified evidence.
- These files are derived from `data/powder_library`; experiment results remain
  in the workspaces and do not silently overwrite runtime configuration.
