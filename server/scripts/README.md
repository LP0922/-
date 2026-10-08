# Scripts

## Control-profile workflow

- `generate_control_profile.py POWDER_ID` previews a draft runtime profile from
  `data/powder_library`.
- Add `--write` to create a profile and `--force` to replace an existing draft.
- Follow `docs/control-profile-experiment-steps.md` before treating generated
  values as qualified control settings.

Calibration, device diagnostics, data collection, and offline analysis helpers.

`monitor_at8811c_drift.py` clears an AT8811C reference reading, samples it for
five minutes by default, and writes CSV plus JSON drift logs to `logs/`.

`calibrate_at8811c_scale.py` establishes the AT8811C engineering-unit
conversion. It requires an empty-scale zero point plus at least two certified
reference masses, captures consecutive stable raw counts, fits
`mass_mg = raw_count * scale_mg_per_count + offset_mg`, and writes
`config/devices/at8811c-calibration.json` only when residual and R-squared
validation pass. Run it without `--execute` to preview the procedure. Stop the
dashboard before physical capture because only one process may own the port.

`device_dashboard.py` is the serial-owning backend and browser dashboard. It
polls both devices every 250 ms. `test_vibration_feed.py` no longer opens a
serial port; it submits a window-move and vibration test to that backend, so
the dashboard can show live data while the test is running.

The browser dashboard shows the AT8811C live weight, state, diagnostic
configuration, and all LA10 registers from 0 through 14. It provides no
device-control buttons.

`plan_dispense.py` previews an L0/four-stage algorithm decision without
opening either serial port. It is intended for offline checks and replay.

`calibrate_feed_yield.py` performs one explicitly authorized physical
calibration sample: tare, move the window, vibrate, wait for stable mass, and
save the mass delta plus the complete action parameters under `data/calibration/`.
It now requires the validated balance calibration JSON instead of assuming
that one raw count equals one milligram.
