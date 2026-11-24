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

from pfc_headless.feedback import (  # noqa: E402
    approve_feedback,
    ingest_feedback,
    prepare_feedback_run,
)
from pfc_headless.project import init_project  # noqa: E402
from pfc_headless.simulation import retry_failed_run  # noqa: E402
from standardize import standardize_experiment  # noqa: E402


class FeedbackManagerTests(unittest.TestCase):
    def test_feedback_creates_new_approved_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "case.json"
            config.write_text(
                json.dumps(
                    {
                        "run_id": "source",
                        "project_dir": str(root),
                        "setup": ["model new"],
                        "solve": "model solve time ${duration}",
                    }
                ),
                encoding="utf-8",
            )
            project = init_project(root / "project", name="Feedback project")
            project.add_case(
                config,
                dimension=3,
                parameters={"duration": 0.01},
            )
            project.new_run(0, run_id="mock_case_0")
            delivery = project.root / "deliveries" / "mock_case_0"
            standardize_experiment(
                ROOT / "examples" / "sample_data" / "Mock_Experiment",
                delivery,
                title="Source run",
                execution_mode="OFFLINE",
                pfc_version="9.0",
            )
            evidence = project.root / "analysis" / "analysis.json"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_text('{"status":"GENERATED"}\n', encoding="utf-8")
            feedback = {
                "schema_version": "1.0.0",
                "feedback_id": "feedback_test",
                "run_id": "mock_case_0",
                "source": "pfc-scientific-visualization",
                "referenced_artifacts": ["analysis/analysis.json"],
                "findings": [
                    {
                        "finding_id": "F1",
                        "statement": "Contact data was not captured.",
                        "evidence": ["analysis/analysis.json"],
                    }
                ],
                "missing_data": ["contact_id"],
                "recommended_sampling": {
                    "mode": "cycle",
                    "interval": 1,
                    "capture_contacts": True,
                },
                "recommended_parameters": {"duration": 0.02},
                "recommended_time_range": [0.0, 0.03],
                "recommended_actions": ["Rerun with contact capture enabled."],
                "status": "RECEIVED",
                "review": None,
                "produced_utc": "2026-11-16T00:00:00+00:00",
            }
            feedback_path = root / "findings.json"
            feedback_path.write_text(
                json.dumps(feedback),
                encoding="utf-8",
            )
            ingested = ingest_feedback(project, feedback_path)
            self.assertEqual(ingested["feedback"]["status"], "PENDING_APPROVAL")
            approve_feedback(
                project,
                "feedback_test",
                approved_by="reviewer",
                rationale="Finite, relevant and non-destructive.",
            )
            created = prepare_feedback_run(project, "feedback_test")
            self.assertNotEqual(created["run"]["run_id"], "mock_case_0")
            self.assertEqual(created["run"]["task_status"], "PREPARED")
            config_record = json.loads(
                (Path(created["run_root"]) / "input" / "config.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(config_record["capture_contacts"])
            self.assertIn("0.02", config_record["solve"])


class FailedRunRetryTests(unittest.TestCase):
    def test_failed_run_creates_fresh_immutable_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "case.json"
            config.write_text(
                json.dumps({
                    "run_id": "source",
                    "project_dir": str(root),
                    "setup": ["model new"],
                    "solve": "model solve time 0.01",
                    "capture_contacts": True,
                }),
                encoding="utf-8",
            )
            project = init_project(root / "project", name="Retry project")
            project.add_case(config, dimension=2)
            source = project.new_run(0, run_id="run_failed")
            project.update_run("run_failed", task_status="FAILED")
            created = retry_failed_run(
                project,
                "run_failed",
                new_run_id="run_retry",
                reason="Fixed PFC2D command syntax",
            )
            self.assertEqual(created["source_run_id"], "run_failed")
            self.assertEqual(created["run"]["run_id"], "run_retry")
            self.assertEqual(created["run"]["case_id"], source["record"]["case_id"])
            retry_config = json.loads(
                (Path(created["run_root"]) / "input" / "config.json").read_text(encoding="utf-8")
            )
            self.assertTrue(retry_config["capture_contacts"])
            self.assertEqual(
                project.get_run("run_failed")["task_status"], "FAILED"
            )


if __name__ == "__main__":
    unittest.main()

