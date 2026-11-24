from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from console_runtime import BridgeClient, find_console_engine  # noqa: E402
from run_case import prepare_run_directory  # noqa: E402
from standardize.converter import _sample_geometry  # noqa: E402


class ConsoleRuntimeContractTests(unittest.TestCase):
    def test_explicit_gui_engine_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            gui = Path(temp) / "pfc3d9_gui.exe"
            gui.write_bytes(b"not executable")
            with self.assertRaisesRegex(ValueError, "Console"):
                find_console_engine(3, gui)

    def test_bridge_client_is_loopback_only(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            BridgeClient("http://192.0.2.2:9001")

    def test_prepare_marks_console_and_does_not_rewrite_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "case.json"
            config.write_text(
                json.dumps(
                    {
                        "case_id": 4,
                        "run_id": "unit",
                        "project_dir": str(root),
                        "restore_initial": False,
                        "setup": [],
                        "solve": "model solve time 0.001",
                        "post_solve": [],
                        "save": "model save 'unit'",
                    }
                ),
                encoding="utf-8",
            )
            launch = prepare_run_directory(config, root / "run")
            prepared = json.loads(Path(launch["config"]).read_text(encoding="utf-8"))
            self.assertEqual(prepared["execution_mode"], "CONSOLE")
            self.assertEqual(prepared["case_id"], 4)
            self.assertTrue(Path(launch["entry_script"]).is_file())

    def test_removed_gui_execution_files_stay_absent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        forbidden = (
            "assets/gui_usercustomize.py",
            "scripts/gui_autostart.py",
            "scripts/gui_controller.py",
            "scripts/install_gui_autostart.py",
            "tests/gui_acceptance_driver.py",
        )
        for relative in forbidden:
            self.assertFalse((root / relative).exists(), relative)

    def test_pfc2d_geometry_uses_line_length_not_area(self) -> None:
        static = {
            "source": {"dimension": 2, "load_axis": "y"},
            "balls": [{"id": 1, "radius": 0.1}],
            "walls": [
                {
                    "id": 10,
                    "name": "top",
                    "position": [0.0, 1.0, 0.0],
                    "vertices": [
                        {"id": 1, "position": [-2.0, 1.0, 0.0]},
                        {"id": 2, "position": [2.0, 1.0, 0.0]},
                    ],
                },
                {
                    "id": 20,
                    "name": "bottom",
                    "position": [0.0, -1.0, 0.0],
                    "vertices": [
                        {"id": 3, "position": [-2.0, -1.0, 0.0]},
                        {"id": 4, "position": [2.0, -1.0, 0.0]},
                    ],
                },
            ],
        }
        geometry = _sample_geometry(static)
        self.assertIsNotNone(geometry)
        self.assertEqual(geometry["dimension"], 2)
        self.assertEqual(geometry["area_kind"], "unit_thickness_length")
        self.assertAlmostEqual(geometry["area0"], 4.0)


if __name__ == "__main__":
    unittest.main()
