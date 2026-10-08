# Active Powder Dosing Head SolidWorks Macro Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with checkpoints.

**Goal:** Create a SolidWorks VBA macro that builds the approved V0.1 active powder dosing head as native parts, a native assembly, and a drawing template, with all assumed interface dimensions centralized for later replacement.

**Architecture:** The macro is a self-contained VBA module intended to run from SolidWorks. It creates each part from sketches and standard features, saves them into a selected output folder, inserts the parts into an assembly, adds basic concentric/coincident mates, and creates a drawing with a section and a dimension/assumption note. A separate text-based validator checks that required procedures, dimensions, output names, and safety notes are present before the macro is handed off.

**Tech Stack:** SolidWorks VBA/API (`SldWorks`, `SwConst`), VBA file I/O, repository-side PowerShell/Python static validation.

---

### Task 1: Define macro parameters and output contract

**Files:**
- Create: `scripts/cad/generate_active_powder_head.bas`
- Create: `scripts/cad/README.md`
- Test: `tests/test_solidworks_macro_static.py`

- [ ] **Step 1: Write the failing validator**

Create a Python test that loads the `.bas` file and asserts the presence of:

```python
required_tokens = (
    "RESERVOIR_ID_MM",
    "THROAT_ID_MM",
    "VALVE_STROKE_MM",
    "TARGET_MASS_MIN_MG",
    "CreateReservoir",
    "CreateValvePlug",
    "CreateActiveHeadAssembly",
    "VERIFY_ON_MACHINE",
)
for token in required_tokens:
    assert token in source
```

- [ ] **Step 2: Run the validator and confirm the expected failure**

Run `python -m pytest tests/test_solidworks_macro_static.py -q`. It must fail because the macro does not exist yet.

- [ ] **Step 3: Add the macro header and constants**

The macro shall define `Option Explicit`, SolidWorks document constants, the approved V0.1 geometry, the target range, and an output-folder picker. All machine-fit assumptions shall be labeled `VERIFY_ON_MACHINE` in both code comments and generated drawing notes.

- [ ] **Step 4: Add operator instructions**

`scripts/cad/README.md` shall explain: open the `.bas` in SolidWorks VBA editor, run `Main`, choose an output folder, select the part template if prompted, and inspect the generated `active_powder_head_V01.SLDASM` and drawing. It shall state that SolidWorks execution is required and that the interface slots are assumed.

- [ ] **Step 5: Run the validator and confirm it passes**

Run `python -m pytest tests/test_solidworks_macro_static.py -q` and require a passing result.

### Task 2: Generate native parts

**Files:**
- Modify: `scripts/cad/generate_active_powder_head.bas`
- Test: `tests/test_solidworks_macro_static.py`

- [ ] **Step 1: Add reservoir and throat procedures**

`CreateReservoir` shall create a cylindrical chamber, a 65-degree conical floor, and a 10 mm throat with a separate throat insert. `CreateThroatInsert` shall create the replaceable insert and a 60-degree sealing seat.

- [ ] **Step 2: Add valve and agitator procedures**

`CreateValvePlug` shall create the 9.6 mm plug, 4 mm stroke reference, and PTFE-tip placeholder geometry. `CreateAgitatorShaft`, `CreateUpperBlade`, and `CreateLowerBlade` shall create the 6 mm shaft and two blades with the 1 mm nominal wall clearance.

- [ ] **Step 3: Add outlet, bracket, and adapter procedures**

`CreateOutletGuide` shall create the 8 mm ID, 25 mm long guide. `CreateMotorBracket` and `CreateMachineAdapter` shall create the assumed 80 mm adapter plate and three 4.5 x 12 mm radial slots.

- [ ] **Step 4: Add deterministic save helpers**

Each part procedure shall call a common `SavePart` helper and produce stable filenames under `<selected folder>\parts\`. Existing files are not overwritten without an explicit confirmation from the macro.

- [ ] **Step 5: Extend the static validator**

Assert that every part procedure calls `SavePart`, that the required filenames are present, and that no hard-coded output path exists.

### Task 3: Build the native assembly and mates

**Files:**
- Modify: `scripts/cad/generate_active_powder_head.bas`
- Test: `tests/test_solidworks_macro_static.py`

- [ ] **Step 1: Add assembly creation**

`CreateActiveHeadAssembly` shall create an assembly document and insert the reservoir, throat insert, valve plug, agitator shaft/blades, outlet guide, motor bracket, and machine adapter.

- [ ] **Step 2: Add basic mates**

Add coincident/concentric mates for the common vertical axis, coincident mates for the throat/guide and adapter stack, and a distance mate representing the nominal valve lift. Leave the motor bracket as an assumed interface with slots rather than pretending to know the LA10 bolt pattern.

- [ ] **Step 3: Add configurations**

Create `CLOSED`, `FINE`, `TRANSITION`, and `COARSE` configurations with valve lifts 0.00, 0.50, 1.25, and 3.00 mm respectively. Save the assembly after switching back to `CLOSED`.

- [ ] **Step 4: Extend the validator**

Assert that the assembly procedure contains all component filenames, all four configuration names, and at least one concentric and one coincident mate call.

### Task 4: Generate a native drawing and assumptions note

**Files:**
- Modify: `scripts/cad/generate_active_powder_head.bas`
- Test: `tests/test_solidworks_macro_static.py`

- [ ] **Step 1: Add drawing creation**

`CreateEngineeringDrawing` shall create a drawing document using the default drawing template, place front/top/section views of the assembly, and save `active_powder_head_V01.SLDDRW` and `active_powder_head_V01.pdf` under `<selected folder>\drawings\`.

- [ ] **Step 2: Add explicit assumption annotations**

Add a general note containing `VERIFY_ON_MACHINE` and the assumed 80 mm adapter envelope, slot pattern, throat diameter, and valve stroke. Do not dimension the unknown LA10 mounting pattern as if it were measured.

- [ ] **Step 3: Extend the validator**

Assert that drawing creation, PDF export, `VERIFY_ON_MACHINE`, and all four valve configuration labels exist in the macro source.

### Task 5: Static verification and handoff

**Files:**
- Modify: `scripts/cad/README.md`
- Test: `tests/test_solidworks_macro_static.py`

- [ ] **Step 1: Run syntax-oriented checks**

Run `python -m pytest tests/test_solidworks_macro_static.py -q` and a PowerShell check that the macro contains balanced `Sub`/`End Sub` and `Function`/`End Function` pairs.

- [ ] **Step 2: Run a macro-independent output check**

Run the repository test suite to ensure the new CAD artifacts do not modify runtime behavior: `python -m pytest -q`.

- [ ] **Step 3: Document SolidWorks execution verification**

The README shall list the manual verification sequence: run the macro, inspect the four assembly configurations, rebuild, rotate the agitator, move the valve through the stroke, verify no interference, and open the PDF drawing.

- [ ] **Step 4: Report the environment boundary**

The handoff must state that native SolidWorks execution cannot be run in this environment and that the macro must be executed in SolidWorks before claiming native-file validity.
