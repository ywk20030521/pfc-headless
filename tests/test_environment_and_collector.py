from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pfc_headless.environment import (  # noqa: E402
    classify_console_executable,
    discover_console_engines,
)


class EnvironmentAndCollectorContractTests(unittest.TestCase):
    def test_dynamic_console_name_is_accepted_by_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "PFC910" / "exe64"
            root.mkdir(parents=True)
            engine = root / "pfc2d_console_release_candidate.exe"
            engine.write_bytes(b"MZ PFC2D Console Terminal " + b"\0" * 64)
            record = classify_console_executable(engine)
            self.assertEqual(record["dimension"], 2)
            self.assertEqual(record["engine_type"], "PFC2D_CONSOLE")
            self.assertEqual(
                discover_console_engines(dimension=2, roots=[root])[0][
                    "executable_path"
                ],
                str(engine.resolve()),
            )

    def test_collector_declares_missing_contact_and_velocity_fields(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "scripts" / "capture_case.py"
        ).read_text(encoding="utf-8")
        self.assertIn("particle_velocity", source)
        self.assertIn("particle_spin", source)
        self.assertIn("NOT_CAPTURED", source)
        self.assertIn("sample_mode", source)
        self.assertIn("contact_frames.csv", source)


if __name__ == "__main__":
    unittest.main()

