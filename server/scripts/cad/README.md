# SolidWorks CAD Macro

`generate_active_powder_head.bas` is a SolidWorks VBA macro for the active powder dosing head V0.1.

## What It Creates

Running `Main` from SolidWorks creates:

- nine native parts under `parts\`;
- `active_powder_head_V01.SLDASM` at the selected output-folder root;
- `drawings\active_powder_head_V01.SLDDRW`;
- `drawings\active_powder_head_V01.pdf`.

The assembly includes `CLOSED`, `FINE`, `TRANSITION`, and `COARSE` configurations with nominal valve lifts of 0.00, 0.50, 1.25, and 3.00 mm. The macro uses two coincident reference-plane mates to align the common longitudinal axis; this is the localization-safe equivalent of a concentric axis mate for the generated prototype.

## Running In SolidWorks

1. Open SolidWorks and create a blank macro from `Tools > Macro > New`.
2. Open the generated `.bas` file in the VBA editor and import or paste the module.
3. Run `Main`.
4. Choose an empty output folder. The macro will create `parts` and `drawings` subfolders.
5. Rebuild the assembly and inspect all four configurations.
6. Rotate the agitator, move the valve through its stroke, and check for interference before manufacturing.
7. Open the PDF drawing and verify that all notes marked `VERIFY_ON_MACHINE` match the physical LA10 interface.

## Environment Boundary

The repository environment does not contain SolidWorks, so native-file creation cannot be executed or visually verified here. The macro is statically validated in the repository; the final native SolidWorks rebuild, mate solve, drawing render, and PDF export must be verified in an installed SolidWorks version.

## Assumed Interface Values

The first model uses an 80 mm adapter envelope with three 4.5 x 12 mm radial slots. These dimensions are deliberately labeled `VERIFY_ON_MACHINE` in the macro and drawing because the LA10 mechanical bolt pattern was not available in the project files.
