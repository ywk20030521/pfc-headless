"""Formal Runs require a bound user authorization; pilots are explicit.

Regression coverage for PFC_INTERACTION_FAILURE_DIAGNOSIS_2026-11-27:
a Run must not reach ``itasca_execute_task`` without a user-approved
authorization, and a legacy/unauthorized Run must be rejected at submission.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pfc_headless.authorization import (  # noqa: E402
    FORMAL,
    PILOT,
    RunAuthorization,
    gate_run_record,
    resolve_authorization,
)
from pfc_headless.common import HeadlessError  # noqa: E402
from pfc_headless.project import init_project  # noqa: E402
from pfc_headless.simulation import execute_planned_run  # noqa: E402


def formal_auth(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "authorization_id": "auth-abc12345",
        "research_task_id": "task-triax",
        "decision_id": "dec-abc12345",
        "model_version": "model-v1",
        "parameter_version": "param-v1",
        "matrix_version": "matrix-v1",
    }
    values.update(overrides)
    return values


class AuthorizationRecordTests(unittest.TestCase):
    def test_no_authorization_rejects_formal_run(self):
        with self.assertRaises(HeadlessError) as ctx:
            resolve_authorization(None)
        self.assertIn("no execution authorization", str(ctx.exception))

    def test_formal_run_requires_full_binding(self):
        for field in ("authorization_id", "research_task_id", "decision_id",
                      "model_version", "parameter_version", "matrix_version"):
            partial = formal_auth()
            partial.pop(field)
            with self.assertRaises(HeadlessError) as ctx:
                resolve_authorization(partial)
            self.assertIn(field, str(ctx.exception))

    def test_pilot_requires_explicit_reason_and_excludes_authorization(self):
        with self.assertRaises(HeadlessError):
            resolve_authorization({"pilot": True, "pilot_reason": ""})
        with self.assertRaises(HeadlessError):
            resolve_authorization({
                "pilot": True, "pilot_reason": "valid",
                "authorization_id": "auth-x",
            })
        pilot = resolve_authorization({"pilot": True, "pilot_reason": "method smoke"})
        self.assertEqual(pilot.to_record()["status"], PILOT)

    def test_formal_record_is_bound_to_versions(self):
        record = resolve_authorization(formal_auth()).to_record()
        self.assertEqual(record["status"], FORMAL)
        self.assertEqual(record["model_version"], "model-v1")
        self.assertEqual(record["parameter_version"], "param-v1")
        self.assertEqual(record["matrix_version"], "matrix-v1")


class CliGateTests(unittest.TestCase):
    def test_run_prepare_without_authorization_fails(self):
        import headless

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = init_project(root / "project", name="CLI gate")
            config = root / "case.json"
            config.write_text(json.dumps({
                "run_id": "source", "project_dir": str(root),
                "setup": ["model new"], "solve": "model solve time 0.01",
            }), encoding="utf-8")
            project.add_case(config, dimension=2)
            argv = [
                "headless.py", "run", "prepare", "--project", str(root / "project"),
                "--case-id", "0", "--instance-id", "pfc2d_test",
            ]
            with patch.object(sys, "argv", argv):
                with self.assertRaises(HeadlessError) as ctx:
                    headless.main()
            self.assertIn("Formal Run requires user authorization", str(ctx.exception))


class RunRecordGateTests(unittest.TestCase):
    def test_legacy_run_without_authorization_is_blocked_at_submission(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = init_project(root / "project", name="Gate")
            config = root / "case.json"
            config.write_text(json.dumps({
                "run_id": "source", "project_dir": str(root),
                "setup": ["model new"], "solve": "model solve time 0.01",
            }), encoding="utf-8")
            project.add_case(config, dimension=2)
            created = project.new_run(0, run_id="run_legacy")
            run_id = str(created["record"]["run_id"])
            with self.assertRaises(HeadlessError) as ctx:
                execute_planned_run(project, run_id)
            self.assertIn("no execution authorization", str(ctx.exception))

    def test_authorized_run_and_pilot_pass_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = init_project(root / "project", name="Gate")
            config = root / "case.json"
            config.write_text(json.dumps({
                "run_id": "source", "project_dir": str(root),
                "setup": ["model new"], "solve": "model solve time 0.01",
            }), encoding="utf-8")
            project.add_case(config, dimension=2)
            for name, authorization in (
                ("run_formal", resolve_authorization(formal_auth()).to_record()),
                ("run_pilot", resolve_authorization({
                    "pilot": True, "pilot_reason": "method smoke",
                }).to_record()),
            ):
                record = project.new_run(
                    0, run_id=name, authorization=authorization)["record"]
                self.assertEqual(record["authorization"]["status"],
                                 FORMAL if name == "run_formal" else PILOT)
                self.assertEqual(gate_run_record(record), authorization)

    def test_incomplete_persisted_authorization_is_blocked(self):
        record = {"run_id": "run_tampered", "authorization": {
            "status": FORMAL, "authorization_id": "auth-x",
        }}
        with self.assertRaises(HeadlessError) as ctx:
            gate_run_record(record)
        self.assertIn("incomplete", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
