from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pfc_headless.project import Project, init_project  # noqa: E402


class ProjectAndRunContractTests(unittest.TestCase):
    def test_unique_runs_and_parameter_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "case.json"
            config.write_text(
                json.dumps(
                    {
                        "case_id": 0,
                        "run_id": "source-run",
                        "project_dir": str(root),
                        "setup": [
                            "model new",
                            "ball attribute density ${density} damp 0.7",
                        ],
                        "solve": "model solve time ${duration}",
                        "post_solve": [],
                        "save": "model save 'unit'",
                        "sample_stride_cycles": 2,
                    }
                ),
                encoding="utf-8",
            )
            project = init_project(root / "project", name="Project")
            case = project.add_case(
                config,
                dimension=2,
                parameters={"density": 2500, "duration": 0.01},
            )
            first = project.new_run(
                case["case_id"],
                run_id="run_first",
                sampling={"mode": "cycle", "interval": 1},
            )
            second = project.new_run(
                case["case_id"],
                run_id="run_second",
                parameters={"density": 3000},
            )
            self.assertNotEqual(first["run_root"], second["run_root"])
            self.assertIn("2500", first["config"]["setup"][1])
            self.assertIn("3000", second["config"]["setup"][1])
            self.assertEqual(second["config"]["sample_stride_cycles"], 2)
            self.assertTrue(
                (first["run_root"] / "input" / "snapshot_manifest.json").is_file()
            )
            reopened = Project.open(root / "project")
            self.assertEqual(len(reopened.list_runs()), 2)

    def test_existing_run_cannot_be_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "case.json"
            config.write_text(
                json.dumps(
                    {
                        "run_id": "x",
                        "project_dir": str(root),
                        "setup": [],
                        "solve": "model solve time 0.001",
                    }
                ),
                encoding="utf-8",
            )
            project = init_project(root / "project", name="Project")
            case = project.add_case(config, dimension=2)
            project.new_run(case["case_id"], run_id="fixed")
            with self.assertRaises(FileExistsError):
                project.new_run(case["case_id"], run_id="fixed")


if __name__ == "__main__":
    unittest.main()

