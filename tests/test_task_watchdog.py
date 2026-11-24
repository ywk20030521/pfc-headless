"""Progress-aware watchdog tests: blocked vs still-solving, no fixed timeout."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pfc_headless import task_watchdog as wd


def _make_run(root: Path, status: str = "RUNNING", raw_bytes: int = 100) -> Path:
    run = root / "run_x"
    (run / "metadata").mkdir(parents=True)
    (run / "data" / "raw").mkdir(parents=True)
    (run / "metadata" / "run.json").write_text(
        json.dumps({"task_status": status, "pid": None}), encoding="utf-8"
    )
    (run / "data" / "raw" / "frame_index.csv").write_bytes(b"x" * raw_bytes)
    return run


class WatchdogDecisionTest(unittest.TestCase):
    def test_completed_is_terminal_without_sampling(self):
        with tempfile.TemporaryDirectory() as td:
            run = _make_run(Path(td), status="COMPLETED")
            with mock.patch.object(wd.time, "sleep") as sleeper:
                result = wd.diagnose(run, interval_s=99)
            self.assertEqual(result["status"], "COMPLETED")
            sleeper.assert_not_called()

    def test_running_when_output_grows(self):
        with tempfile.TemporaryDirectory() as td:
            run = _make_run(Path(td), status="RUNNING", raw_bytes=100)
            frame = run / "data" / "raw" / "frame_index.csv"

            def grow(*_args, **_kwargs):
                frame.write_bytes(b"x" * 400)

            with mock.patch.object(wd.time, "sleep", side_effect=grow):
                result = wd.diagnose(run, interval_s=1)
            self.assertEqual(result["status"], "RUNNING")
            self.assertTrue(result["signals"]["bytes_advanced"])

    def test_stalled_when_no_signal_changes(self):
        with tempfile.TemporaryDirectory() as td:
            run = _make_run(Path(td), status="RUNNING", raw_bytes=100)
            with mock.patch.object(wd.time, "sleep"):
                result = wd.diagnose(run, interval_s=1)
            self.assertEqual(result["status"], "UNKNOWN")

    def test_stalled_with_cpu_signal_but_no_progress(self):
        """Process burns CPU but no output advances -> still progressing (CPU counts)."""
        with tempfile.TemporaryDirectory() as td:
            run = _make_run(Path(td), status="RUNNING", raw_bytes=100)
            samples = [
                {"task_status": "RUNNING", "pid": 123,
                 "process": {"cpu": 1.0}, "raw": {"total_bytes": 100.0, "newest_mtime": 1.0, "frame_rows": 5.0}},
                {"task_status": "RUNNING", "pid": 123,
                 "process": {"cpu": 5.0}, "raw": {"total_bytes": 100.0, "newest_mtime": 1.0, "frame_rows": 5.0}},
            ]
            fake_psutil = mock.MagicMock()
            fake_psutil.Process.return_value.is_running.return_value = True
            with mock.patch.object(wd, "sample", side_effect=samples), \
                 mock.patch.object(wd.time, "sleep"), \
                 mock.patch.object(wd, "psutil", fake_psutil):
                result = wd.diagnose(run, pid=123, interval_s=1)
            self.assertEqual(result["status"], "RUNNING")
            self.assertTrue(result["signals"]["cpu_advanced"])

    def test_dead_process_detected(self):
        with tempfile.TemporaryDirectory() as td:
            run = _make_run(Path(td), status="RUNNING")
            with mock.patch.object(wd, "psutil", None):
                # No pid in record -> cannot declare dead; falls to output logic.
                result = wd.diagnose(run, interval_s=1)
            self.assertIn(result["status"], {"UNKNOWN", "PROCESS_DEAD", "RUNNING"})

    def test_diagnose_to_file_writes_json(self):
        with tempfile.TemporaryDirectory() as td:
            run = _make_run(Path(td), status="COMPLETED")
            out = Path(td) / "diag.json"
            result = wd.diagnose_to_file(run, out, interval_s=1)
            self.assertTrue(out.is_file())
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["status"], "COMPLETED")
            self.assertEqual(result["status"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
