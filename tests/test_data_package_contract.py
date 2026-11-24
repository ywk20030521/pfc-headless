from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pfc_headless.data import verify_delivery  # noqa: E402
from standardize import standardize_experiment  # noqa: E402


class DataPackageContractTests(unittest.TestCase):
    def test_metadata_manifest_and_downstream_contract_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "delivery"
            standardize_experiment(
                ROOT / "examples" / "sample_data" / "Mock_Experiment",
                output,
                title="Contract test",
                execution_mode="OFFLINE",
                pfc_version="9.0",
            )
            report = verify_delivery(output)
            self.assertEqual(report["status"], "PASS", report["errors"])
            self.assertTrue((output / "metadata.json").is_file())
            self.assertTrue((output / "manifest.json").is_file())
            self.assertTrue((output / "validation_report.json").is_file())
            metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["engine_dimension"], 3)
            self.assertIn("file_hashes", metadata)
            self.assertIn("record_counts", metadata)

    def test_tampered_package_fails_hash_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "delivery"
            standardize_experiment(
                ROOT / "examples" / "sample_data" / "Mock_Experiment",
                output,
                title="Contract test",
                execution_mode="OFFLINE",
                pfc_version="9.0",
            )
            target = output / "cases" / "case_0" / "frame_summary.csv"
            target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            report = verify_delivery(output)
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(
                any(
                    "hash" in error.lower() or "mismatch" in error.lower()
                    for error in report["errors"]
                ),
                report["errors"],
            )


if __name__ == "__main__":
    unittest.main()

