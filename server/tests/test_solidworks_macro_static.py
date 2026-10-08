from __future__ import annotations

import re
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MACRO = ROOT / "scripts" / "cad" / "generate_active_powder_head.bas"


class SolidWorksMacroStaticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(MACRO.exists(), f"macro missing: {MACRO}")
        self.source = MACRO.read_text(encoding="utf-8")

    def test_approved_geometry_and_entry_points_are_present(self) -> None:
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
            with self.subTest(token=token):
                self.assertIn(token, self.source)

    def test_all_parts_are_saved_through_common_helper(self) -> None:
        part_procedures = (
            "CreateReservoir",
            "CreateThroatInsert",
            "CreateValvePlug",
            "CreateAgitatorShaft",
            "CreateUpperBlade",
            "CreateLowerBlade",
            "CreateOutletGuide",
            "CreateMotorBracket",
            "CreateMachineAdapter",
        )
        for name in part_procedures:
            match = re.search(
                rf"(?is)Sub\s+{name}\b(.*?)End\s+Sub",
                self.source,
            )
            self.assertIsNotNone(match, name)
            self.assertIn("SavePart", match.group(1), name)

    def test_assembly_has_configurations_and_mates(self) -> None:
        match = re.search(
            r"(?is)Sub\s+CreateActiveHeadAssembly\b(.*?)End\s+Sub",
            self.source,
        )
        self.assertIsNotNone(match)
        assembly = match.group(1)
        for config in ("CLOSED", "FINE", "TRANSITION", "COARSE"):
            self.assertIn(config, assembly)
        self.assertRegex(assembly, r"(?i)concentric")
        self.assertRegex(assembly, r"(?i)coincident")

    def test_drawing_contains_assumption_note_and_pdf_export(self) -> None:
        match = re.search(
            r"(?is)Sub\s+CreateEngineeringDrawing\b(.*?)End\s+Sub",
            self.source,
        )
        self.assertIsNotNone(match)
        drawing = match.group(1)
        self.assertIn("VERIFY_ON_MACHINE", drawing)
        self.assertRegex(drawing, r"(?i)pdf")

    def test_vba_subroutine_pairs_are_balanced(self) -> None:
        starts = re.findall(r"(?im)^\s*(?:Public\s+|Private\s+)?(?:Sub|Function)\s+", self.source)
        ends = re.findall(r"(?im)^\s*End\s+(?:Sub|Function)\b", self.source)
        self.assertEqual(len(starts), len(ends))

    def test_revolved_reservoir_matches_declared_cone_angle(self) -> None:
        def constant(name: str) -> float:
            match = re.search(
                rf"(?im)^Private Const {name} As Double = ([0-9.]+)#?\s*$",
                self.source,
            )
            self.assertIsNotNone(match, name)
            return float(match.group(1))

        cone_height = constant("RESERVOIR_TOTAL_HEIGHT_MM") - constant(
            "RESERVOIR_WALL_HEIGHT_MM"
        )
        radial_run = (
            constant("RESERVOIR_OD_MM") - constant("THROAT_OD_MM")
        ) / 2
        actual_angle = math.degrees(math.atan2(cone_height, radial_run))
        self.assertAlmostEqual(actual_angle, constant("CONE_ANGLE_DEG"), delta=0.5)

    def test_finished_sketch_is_found_without_unsupported_active_sketch_api(self) -> None:
        match = re.search(
            r"(?is)Sub\s+EndActiveSketch\b(.*?)End\s+Sub",
            self.source,
        )
        self.assertIsNotNone(match)
        helper = match.group(1)
        self.assertIn("FindLatestSketchFeature", helper)
        self.assertRegex(helper, r"(?i)sketchFeature\.Select2")

        finder = re.search(
            r"(?is)Function\s+FindLatestSketchFeature\b(.*?)End\s+Function",
            self.source,
        )
        self.assertIsNotNone(finder)
        self.assertIn("GetTypeName2", finder.group(1))
        self.assertIn("GetNextFeature", finder.group(1))
        self.assertNotIn(".ActiveSketch", self.source)
        self.assertNotIn("GetActiveSketch2", self.source)


if __name__ == "__main__":
    unittest.main()
