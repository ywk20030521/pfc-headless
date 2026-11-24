from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CaptureBoundaryTests(unittest.TestCase):
    def test_console_only_capability_declaration(self):
        source = (ROOT / "scripts" / "console_runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Console-only", source)
        self.assertIn("pfc2d9_console", source)
        self.assertIn("pfc3d9_console", source)
        self.assertNotIn("gui_autostart", source)

    def test_capture_and_standardized_delivery_are_owned_here(self):
        required = (
            "scripts/run_case.py",
            "scripts/capture_case.py",
            "scripts/capture_store.py",
            "scripts/validate_capture.py",
            "scripts/run_standardization.py",
            "scripts/standardize/converter.py",
        )
        for relative in required:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_standard_contract_schemas_are_declared(self):
        expected = {
            "experiment.schema.json",
            "case.schema.json",
            "channel.schema.json",
            "frame.schema.json",
        }
        actual = {
            path.name for path in (ROOT / "schema").glob("*.json")
        }
        self.assertTrue(expected <= actual)
        for name in expected:
            json.loads((ROOT / "schema" / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
