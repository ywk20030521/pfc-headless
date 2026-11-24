"""Regression tests for the 2026-11-22 reliability upgrades."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pfc_headless.common import HeadlessError
from pfc_headless.preflight import preflight_config
from pfc_headless.project import init_project


class PreflightTests(unittest.TestCase):
    def test_rejects_xvelocity_alias(self):
        cfg = {"setup": ["ball attribute xvelocity 0.1 range id 1"], "solve": "model solve time 0.1"}
        with self.assertRaises(HeadlessError) as ctx:
            preflight_config(cfg)
        self.assertIn("velocity-x", str(ctx.exception))

    def test_accepts_valid_attribute_with_range(self):
        cfg = {"setup": ["ball attribute velocity-x 0.1 range id 1"], "solve": "model solve time 0.1"}
        report = preflight_config(cfg)
        self.assertIn(report["status"], ("PASS", "PASS_WITH_WARNINGS"))
        self.assertEqual(report["errors"], [])
        # range/id are selectors, not attribute keywords
        self.assertFalse(any("unrecognised attribute" in w for w in report["warnings"]))

    def test_warns_unsegmented_long_solve(self):
        cfg = {"solve": "model solve time 0.2"}
        report = preflight_config(cfg)
        self.assertTrue(any("segment" in w for w in report["warnings"]))

    def test_no_warning_when_segmented(self):
        cfg = {"solve": "model solve time 0.2", "solve_segment_cycles": 500}
        report = preflight_config(cfg)
        self.assertFalse(any("segment" in w for w in report["warnings"]))
        self.assertTrue(report["timestep_budget"]["segmented"])


class FailureEvidenceTests(unittest.TestCase):
    def test_engine_error_is_extracted_from_embedded_result(self):
        import json

        from pfc_headless.mcp_evidence import extract_task_error

        output = json.dumps({
            "status": "FAILED",
            "errors": [{"type": "ValueError", "message": "Bad conversion of parameter 3 (kn)."}],
        })
        evidence = {
            "response": {
                "ok": True,
                "data": {
                    "task_status": "failed",
                    "output": output,
                    "error": "Script execution failed",
                },
            }
        }
        summary = extract_task_error(evidence)
        self.assertIsNotNone(summary)
        self.assertEqual(summary["source"], "engine_result")
        self.assertIn("Bad conversion", summary["message"])
        self.assertNotIn("SyntaxError", summary["message"])


class RollbackTests(unittest.TestCase):
    def test_failed_new_run_leaves_no_partial_directory(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "proj"
            project = init_project(root, name="rollback-test", project_id="rollback_test")
            cfg = root / "case.json"
            cfg.write_text(
                '{"case_id":0,"run_id":"x","project_dir":".","source_files":'
                '{"missing.dat":"0"*64},"setup":[],"solve":"model solve time 0.1"}'.replace('"0"*64', '"' + "0"*64 + '"'),
                encoding="utf-8",
            )
            project.add_case(cfg, case_id=0, dimension=3)
            with self.assertRaises(HeadlessError):
                project.new_run(0, run_id="run_should_rollback")
            self.assertFalse((root / "runs" / "run_should_rollback").exists())


if __name__ == "__main__":
    unittest.main()
