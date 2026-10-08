# Stage-One Research Plan

## Goal

Build a reliable software foundation for 10 mg-scale powder dispensing. Each run must be controllable, verifiable, traceable, and reviewable.

## Architecture

`ui_recipe -> task_state_machine -> dispensing_algorithm -> device_adapters -> data`

## Research Deliverables

- Device interface specifications and communication timing
- Weighing signal analysis and stability rules
- Four-stage state machine and exception flow
- L0 feed-forward calibration plan and parameter table
- Data dictionary, test plan, and acceptance report template

## Control Stages

1. Coarse feed
2. Slow feed A
3. Fine feed B
4. Final stabilization and acceptance
