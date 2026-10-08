# Active Powder Dosing Head CAD Design

Date: 2026-08-10
Status: Approved concept, assumed-interface prototype V0.1

## 1. Objective

Design a powder dosing head for the existing `powder_sampling_control` system that improves adaptability across dry free-flowing and moderately cohesive powders. The head shall replace gravity-only metering with active agitation and a physical variable-area shutoff while retaining the existing LA10 vibration actuator as an auxiliary flow aid.

The primary dosing range is 50-1000 mg with an acceptance band of +/-10 mg. The V0.1 target for minimum controllable delivered increment is no more than 5 mg after calibration.

## 2. Evidence And Design Choice

The selected concept combines:

- a rotating wall-sweeping agitator to disrupt bridges, loosen agglomerates, and reduce wall buildup;
- an axially translated central valve plug to provide continuous outlet-area control and physical shutoff;
- optional LA10 vibration for startup and bounded recovery pulses;
- a short conductive outlet guide to constrain the falling powder stream.

This choice incorporates the useful mechanisms observed in US20180178937A1 and the 2026 SLAS Technology evaluation while remaining compatible with this project's existing window-position, vibration-frequency, duty-cycle, balance-feedback, and tail-mass control architecture.

The alternatives considered were a micro-auger feeder and a low-change shutter plus external bridge breaker. The auger offers strong nominal metering linearity but has higher compaction, dead-volume, cleaning, and small-dose risks. The low-change option is suitable as a quick experiment but preserves the existing gravity dependence. The rotating agitator and axial valve are therefore selected for V0.1.

## 3. Intended Operating Envelope

- Target dose: 50-1000 mg.
- Acceptance band: target +/-10 mg.
- Powder class: dry free-flowing through moderately cohesive laboratory powders.
- Environment: atmospheric laboratory conditions with moderate humidity.
- Excluded from V0.1 acceptance: wet pastes, severely hygroscopic powders, and hard agglomerates larger than the outlet throat.
- Contact-surface intent: cleanable, low-retention geometry with no horizontal ledges in the powder path.

## 4. Assembly Architecture

The assembly is divided into independently replaceable units:

1. Reservoir body: cylindrical storage chamber with a steep conical floor.
2. Agitator module: central shaft and two flexible sweeping blades at different elevations.
3. Valve module: axially moving plug, replaceable PTFE sealing tip, and throat insert.
4. Outlet guide: short grounded or conductive tube below the throat.
5. Drive interface: rotary motor mount and LA10-to-valve motion adapter.
6. Machine adapter: parameterized mounting plate with slotted holes for the first physical fit check.

Powder-contact modules shall be removable without disassembling the motor or LA10 actuator.

## 5. Assumed Geometry

These dimensions define the V0.1 CAD model. Machine-interface dimensions are assumptions and must be replaced after physical measurement.

| Feature | V0.1 value | Design intent |
| --- | ---: | --- |
| Reservoir internal diameter | 60 mm | About 100 mL useful capacity with the assumed body height |
| Reservoir straight-wall height | 50 mm | Compact prototype envelope |
| Conical wall angle | 65 degrees from horizontal | Reduce stagnant zones for cohesive powders |
| Throat diameter | 10.0 mm | Balance coarse flow and small-dose control |
| Agitator shaft diameter | 6.0 mm | Stiff, readily manufactured shaft |
| Upper blade sweep radius | 28.5 mm | Nominal 1.5 mm radial wall clearance |
| Lower blade sweep radius | 22.0 mm | Sweep the converging cone without binding |
| Valve plug diameter | 9.6 mm | Nominal 0.2 mm radial clearance in the throat |
| Valve effective stroke | 0-4.0 mm | Closed, fine, transition, and coarse positions |
| Seal interface | 60-degree PTFE conical tip | Compliant physical shutoff |
| Outlet guide internal diameter | 8.0 mm | Constrain the powder stream and reduce scatter |
| Outlet guide length | 25 mm | Limit free fall while retaining container clearance |
| Adapter plate outside diameter | 80 mm | Assumed fit-check envelope |
| Adapter slots | 3 x radial slots, 4.5 x 12 mm | Tolerate unknown initial mounting pattern |
| Maximum head outside diameter | 80 mm | Excludes attached reservoir bottle |
| Approximate head height | 150 mm | Excludes external motor/actuator projections |

General prototype clearances:

- Printed sliding interfaces: 0.25-0.35 mm per side.
- Machined valve/throat radial clearance: 0.15-0.20 mm per side before coating.
- Static powder-contact joints: use captured food/lab-compatible O-rings outside the direct flow path.
- Avoid threads in the direct powder path.

## 6. Motion And Control Mapping

### 6.1 Rotary Agitator

- Normal speed range: 5-30 rpm.
- Startup: 5-10 rpm to establish flow without compacting powder.
- Bridge recovery: one to three bounded 20-30 rpm bursts, optionally combined with LA10 vibration.
- Rotation stops before the valve reaches its fully closed sealing position.

The blades are flexible or spring-mounted so they sweep near the wall without creating a hard interference condition.

### 6.2 Axial Valve

The current project uses 200 LA10 position units per millimetre. The V0.1 mechanical adapter maps LA10 window motion to the 0-4 mm valve stroke at 1:1 displacement.

Initial control landmarks:

| Valve state | Physical lift | Relative LA10 units | Purpose |
| --- | ---: | ---: | --- |
| Closed | 0.00 mm | 0 | PTFE tip seated |
| Fine | 0.25-0.60 mm | 50-120 | Pulse dosing near target |
| Transition | 0.75-1.50 mm | 150-300 | Controlled medium flow |
| Coarse | 2.00-4.00 mm | 400-800 | Startup test and bulk approach |

The existing software's absolute window positions must be converted through a configurable closed-position offset. The current operational range of 100-750 units can cover most of the assumed stroke; the final 4 mm coarse endpoint may require extending the approved software range to 800 units after collision and flow testing.

### 6.3 Vibration

Vibration remains auxiliary rather than the primary metering mechanism:

- normal operation: disabled or the lowest validated setting;
- startup aid: bounded 40-80 Hz pulse with calibrated duty;
- no-flow recovery: at most three bounded pulses with the valve partially open;
- emergency stop: valve closes first, followed by agitator and vibration stop.

## 7. Operating Sequence

1. Precheck: confirm valve home, actuator status, balance communication, and target container presence.
2. Condition: start agitator at low speed with the valve closed.
3. Probe: open to the fine or transition landmark and measure startup delay and flow.
4. Coarse feed: use valve lift as the primary flow command; use vibration only when calibrated.
5. Precision feed: reduce valve lift and issue bounded pulses, waiting for balance-state updates between pulses.
6. Shutoff: stop rotary motion, seat the valve, then stop vibration and wait for stable mass.
7. Recovery: if flow remains below threshold, close the valve, execute a bounded agitator/vibration recovery, reopen at transition lift, and retry. Exceeding the retry limit enters fault state.

## 8. Materials And Manufacturing

Recommended powder-contact materials:

- shaft and throat insert: 316L stainless steel;
- sealing tip and optional blade edge: virgin PTFE;
- prototype reservoir and outer housing: PETG or nylon for fit/flow testing;
- production reservoir: 316L, PEEK, or another validated low-retention material.

All product-contact surfaces should target Ra <= 0.8 micrometre for production metal parts. Printed V0.1 parts are for geometry and flow testing, not final contamination-controlled use.

## 9. CAD Deliverables

The approved package will contain:

- individual STEP files for the reservoir body, throat insert, valve plug, agitator shaft, upper blade, lower blade, outlet guide, motor bracket, LA10 motion adapter, and machine adapter plate;
- one STEP assembly showing the nominal closed position;
- DXF profiles for the adapter plate, flexible blades, and bracket plates;
- a PDF engineering drawing set with overall, section, exploded, interface, and part-detail sheets;
- a bill of materials and assumptions register;
- source model/build files used to generate the neutral CAD artifacts.

The PDF shall mark assumed LA10 mounting dimensions as `VERIFY ON MACHINE` and distinguish them from frozen internal geometry.

## 10. Verification Plan

### 10.1 CAD Verification

- no solid-body intersections in closed, fine, transition, or coarse positions;
- valve stroke clears the throat without exposing trapping ledges;
- blades maintain the specified wall and cone clearances through a complete revolution;
- removable contact parts can be extracted without removing fixed drive components;
- STEP files reopen successfully and preserve solid bodies;
- DXF profiles are closed and dimensionally consistent with their source parts;
- every PDF sheet renders without clipped dimensions or unreadable annotations.

### 10.2 Prototype Verification

- dry-cycle the valve for at least 1000 cycles without binding;
- verify physical shutoff with the most free-flowing test powder;
- measure delivered increment distributions at fine-lift settings;
- compare no-flow and blockage frequency against the existing head for at least three powder classes;
- run at least 30 repeats at 50, 100, 500, and 1000 mg before claiming the +/-10 mg objective;
- record startup delay, steady flow, tail mass, overshoot, recovery count, and cleaning time.

## 11. Risks And Boundaries

- Assumed machine-interface dimensions prevent direct-fit claims until the LA10 head is measured.
- A 10 mm throat may pass soft agglomerates but not hard lumps near or above that size.
- Excessive vibration or agitator speed can compact cohesive fine powder; recovery actions are bounded.
- The 5 mg controllable-increment target is a validation target, not a geometric guarantee.
- Patent freedom-to-operate is outside this engineering design. Commercialization requires a separate patent review.

## 12. Acceptance Of V0.1 CAD Package

The V0.1 CAD package is accepted when all listed files are present, neutral CAD files reopen as valid solids/profiles, the drawing set clearly separates assumed from frozen dimensions, and the closed/fine/coarse assembly configurations pass interference checks. Physical dosing performance remains subject to prototype testing and calibration.
