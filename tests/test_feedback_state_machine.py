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
    finalize_feedback_attempt,
    ingest_feedback,
    mark_feedback_running,
    prepare_feedback_run,
)
from pfc_headless.project import init_project  # noqa: E402
from standardize import standardize_experiment  # noqa: E402


class FeedbackStateMachineTests(unittest.TestCase):
    def test_proposed_running_validated_and_retryable_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "case.json"
            config.write_text(
                json.dumps(
                    {
                        "project_dir": str(root),
                        "setup": ["model new"],
                        "solve": "model solve time 0.01",
                    }
                ),
                encoding="utf-8",
            )
            project = init_project(root / "project", name="Feedback")
            project.add_case(config, dimension=2)
            project.new_run(0, run_id="source")
            standardize_experiment(
                ROOT / "examples" / "sample_data" / "Mock_Experiment",
                project.root / "deliveries" / "source",
                title="source",
                execution_mode="OFFLINE",
            )
            artifact = project.root / "analysis" / "analysis.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text('{"status":"GENERATED"}\n', encoding="utf-8")
            feedback = {
                "schema_version": "1.0.0",
                "feedback_id": "feedback_state",
                "run_id": "source",
                "source": "pfc-scientific-visualization",
                "referenced_artifacts": ["analysis/analysis.json"],
                "findings": [],
                "missing_data": [],
                "recommended_sampling": {"mode": "cycle", "interval": 1},
                "recommended_parameters": {},
                "recommended_actions": [],
                "status": "RECEIVED",
                "review": None,
                "produced_utc": "2026-11-16T00:00:00+00:00",
            }
            source = root / "findings.json"
            source.write_text(json.dumps(feedback), encoding="utf-8")
            ingest_feedback(project, source)
            approve_feedback(
                project,
                "feedback_state",
                approved_by="reviewer",
                rationale="valid",
            )
            first = prepare_feedback_run(
                project,
                "feedback_state",
                run_id="attempt_1",
            )
            self.assertEqual(first["run"]["task_status"], "PREPARED")
            state = json.loads(
                Path(first["feedback_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(state["status"], "PROPOSED")
            self.assertNotEqual(state["status"], "USED")
            with self.assertRaises(Exception):
                prepare_feedback_run(project, "feedback_state")
            mark_feedback_running(
                project,
                "feedback_state",
                run_id="attempt_1",
            )
            finalized = finalize_feedback_attempt(
                project,
                "feedback_state",
                run_id="attempt_1",
                status="VALIDATED",
                delivery=project.root / "deliveries" / "source",
            )
            self.assertEqual(finalized["feedback"]["status"], "VALIDATED")

    def test_failed_attempt_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "case.json"
            config.write_text(
                json.dumps(
                    {
                        "project_dir": str(root),
                        "setup": ["model new"],
                        "solve": "model solve time 0.01",
                    }
                ),
                encoding="utf-8",
            )
            project = init_project(root / "project", name="Retry")
            project.add_case(config, dimension=2)
            project.new_run(0, run_id="source")
            from standardize import standardize_experiment

            standardize_experiment(
                ROOT / "examples" / "sample_data" / "Mock_Experiment",
                project.root / "deliveries" / "source",
                title="source",
                execution_mode="OFFLINE",
            )
            artifact = project.root / "analysis" / "analysis.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text("{}\n", encoding="utf-8")
            payload = {
                "schema_version": "1.0.0",
                "feedback_id": "feedback_retry",
                "run_id": "source",
                "source": "pfc-scientific-visualization",
                "referenced_artifacts": ["analysis/analysis.json"],
                "findings": [],
                "missing_data": [],
                "recommended_sampling": {"mode": "cycle", "interval": 1},
                "recommended_parameters": {},
                "recommended_actions": [],
                "status": "RECEIVED",
                "review": None,
                "produced_utc": "2026-11-16T00:00:00+00:00",
            }
            path = root / "findings.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            ingest_feedback(project, path)
            approve_feedback(
                project,
                "feedback_retry",
                approved_by="reviewer",
                rationale="valid",
            )
            prepare_feedback_run(
                project,
                "feedback_retry",
                run_id="attempt_fail",
            )
            finalize_feedback_attempt(
                project,
                "feedback_retry",
                run_id="attempt_fail",
                status="FAILED",
                error={"type": "ExecutionError", "message": "failed"},
            )
            retry = prepare_feedback_run(
                project,
                "feedback_retry",
                run_id="attempt_retry",
            )
            self.assertEqual(retry["run"]["task_status"], "PREPARED")


if __name__ == "__main__":
    unittest.main()
