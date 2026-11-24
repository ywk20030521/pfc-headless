from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pfc_headless.common import HeadlessError  # noqa: E402
from pfc_headless.contracts import (  # noqa: E402
    make_case,
    make_feedback,
    make_instance,
    make_project,
    make_run,
    validate_document,
)


class HeadlessContractTests(unittest.TestCase):
    def test_all_entity_contracts_validate(self) -> None:
        project = make_project(
            project_id="project_test",
            project_name="Test",
            project_root=r"D:\project",
        )
        case = make_case(
            case_id=0,
            case_name="Case 0",
            engine_dimension=2,
            config_path="cases/case_0/case_config.json",
        )
        instance = make_instance(
            instance_id="instance_test",
            engine_type="PFC2D_CONSOLE",
            executable_path=r"D:\Itasca\pfc2d9_console.exe",
            pid=123,
            bridge_port=9001,
            bootstrap_path=r"D:\instance\.pfc-console\bridge_bootstrap.py",
            state="ATTACHED",
        )
        run = make_run(
            run_id="run_test",
            case_id=0,
            instance_id="instance_test",
            input_snapshot="input",
            script_version="sha256:" + "a" * 64,
            output_path="deliveries/run_test",
        )
        feedback = make_feedback(
            run_id="run_test",
            source="pfc-scientific-visualization",
            findings=[],
            missing_data=[],
            recommended_sampling={"mode": "cycle", "interval": 1},
            recommended_actions=[],
        )
        for name, value in (
            ("project", project),
            ("case", case),
            ("instance", instance),
            ("run", run),
            ("feedback", feedback),
        ):
            self.assertEqual(validate_document(name, value)["validation_status"], "PASS")

    def test_invalid_console_state_is_rejected(self) -> None:
        instance = make_instance(
            instance_id="instance_test",
            engine_type="PFC2D_CONSOLE",
            executable_path="engine.exe",
            pid=1,
            bridge_port=9001,
            bootstrap_path="bootstrap.py",
            state="READY",
        )
        instance["state"] = "GUI_ACTIVE"
        with self.assertRaises(HeadlessError):
            validate_document("instance", instance)


if __name__ == "__main__":
    unittest.main()

