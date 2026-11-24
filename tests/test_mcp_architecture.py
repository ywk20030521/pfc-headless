from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pfc_headless import simulation  # noqa: E402
from pfc_headless.common import HeadlessError  # noqa: E402
from pfc_headless.connection import (  # noqa: E402
    make_mcp_evidence,
    verify_connection,
)
from pfc_headless.instance import identity_fingerprint  # noqa: E402
from pfc_headless.project import Project, init_project  # noqa: E402


IDENTITY = {
    "pid": 4321,
    "executable": r"D:\Itasca\PFC900\exe64\pfc2d9_console.exe",
    "command_line": [
        r"D:\Itasca\PFC900\exe64\pfc2d9_console.exe",
        "--run",
        "bridge_bootstrap.py",
    ],
    "create_time": 123.0,
}


def fake_instance() -> dict:
    fingerprint = identity_fingerprint(
        IDENTITY,
        instance_id="pfc2d_test",
        engine_type="PFC2D_CONSOLE",
        bridge_port=9011,
    )
    return {
        "schema_version": "1.0.0",
        "instance_id": "pfc2d_test",
        "engine_type": "PFC2D_CONSOLE",
        "executable_path": IDENTITY["executable"],
        "pid": IDENTITY["pid"],
        "bridge_port": 9011,
        "state": "READY",
        "bootstrap_path": "bridge_bootstrap.py",
        "identity_verified": True,
        "health_verified": True,
        "execution_verified": True,
        "mcp_verified": True,
        "identity_fingerprint": fingerprint,
        "mcp_connection_id": "mcp_pfc2d_test",
        "readiness_nonce": "nonce-current",
        "started_utc": "2026-11-16T00:00:00+00:00",
        "stopped_utc": None,
    }


def evidence_payload(
    *,
    tool: str,
    run_id: str,
    task_id: str,
    task_state: str,
    request: dict | None = None,
) -> dict:
    instance = fake_instance()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "schema_version": "1.0.0",
        "tool": tool,
        "run_id": run_id,
        "instance_id": instance["instance_id"],
        "task_id": task_id,
        "task_state": task_state,
        "connection_id": instance["mcp_connection_id"],
        "identity_fingerprint": instance["identity_fingerprint"],
        "request": request or {"task_id": task_id},
        "response": {"task_id": task_id, "status": task_state},
        "observed_utc": now.isoformat(timespec="seconds"),
    }


class McpArchitectureTests(unittest.TestCase):
    def test_simulation_module_has_no_bridge_or_http_execution_path(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "pfc_headless"
            / "simulation.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("BridgeClient", source)
        self.assertNotIn("urllib", source)
        self.assertNotIn("http://", source)

    def _project(self, root: Path) -> Project:
        config = root / "case.json"
        config.write_text(
            json.dumps(
                {
                    "run_id": "source",
                    "project_dir": str(root),
                    "setup": ["model new"],
                    "solve": "model solve time 0.01",
                    "source_files": {},
                }
            ),
            encoding="utf-8",
        )
        project = init_project(root / "project", name="MCP project")
        project.add_case(config, dimension=2)
        return project

    def test_prepare_bind_and_record_status_without_bridge_client(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self._project(root)
            instance = fake_instance()
            route_result = (
                instance,
                object(),
                IDENTITY,
                instance["identity_fingerprint"],
            )
            with patch.object(
                simulation,
                "load_instance",
                return_value=instance,
            ), patch.object(
                simulation,
                "verified_instance_identity",
                return_value=route_result,
            ):
                prepared = simulation.prepare_project_case(
                    project,
                    case_id=0,
                    run_id="run_mcp",
                    instance_id=instance["instance_id"],
                )
                operation = prepared["mcp_operation"]
                self.assertEqual(operation["tool"], "itasca_execute_task")
                evidence = evidence_payload(
                    tool="itasca_execute_task",
                    run_id="run_mcp",
                    task_id="abc123",
                    task_state="pending",
                    request=operation["arguments"],
                )
                evidence_path = root / "execute.json"
                evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
                attached = simulation.attach_task(
                    project,
                    "run_mcp",
                    evidence_path=evidence_path,
                )
                self.assertEqual(attached["run"]["task_status"], "SUBMITTED")
                status = simulation.status_operation(project, "run_mcp")
                self.assertEqual(
                    status["mcp_operation"]["tool"],
                    "itasca_check_task_status",
                )
                status_evidence = evidence_payload(
                    tool="itasca_check_task_status",
                    run_id="run_mcp",
                    task_id="abc123",
                    task_state="running",
                )
                status_path = root / "status.json"
                status_path.write_text(
                    json.dumps(status_evidence),
                    encoding="utf-8",
                )
                recorded = simulation.record_status(
                    project,
                    "run_mcp",
                    evidence_path=status_path,
                )
                self.assertEqual(recorded["run"]["task_status"], "RUNNING")

    def test_wrong_script_or_duplicate_task_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self._project(root)
            instance = fake_instance()
            route_result = (
                instance,
                object(),
                IDENTITY,
                instance["identity_fingerprint"],
            )
            with patch.object(
                simulation,
                "load_instance",
                return_value=instance,
            ), patch.object(
                simulation,
                "verified_instance_identity",
                return_value=route_result,
            ):
                prepared = simulation.prepare_project_case(
                    project,
                    case_id=0,
                    run_id="run_a",
                    instance_id=instance["instance_id"],
                )
                wrong = evidence_payload(
                    tool="itasca_execute_task",
                    run_id="run_a",
                    task_id="task_a",
                    task_state="pending",
                    request={
                        "entry_script": str(root / "wrong.py"),
                        "description": prepared["mcp_operation"]["arguments"][
                            "description"
                        ],
                    },
                )
                path = root / "wrong.json"
                path.write_text(json.dumps(wrong), encoding="utf-8")
                with self.assertRaises(HeadlessError):
                    simulation.attach_task(
                        project,
                        "run_a",
                        evidence_path=path,
                    )

    def test_unresolved_timeout_is_recorded_without_resubmission(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self._project(root)
            instance = fake_instance()
            route_result = (
                instance,
                object(),
                IDENTITY,
                instance["identity_fingerprint"],
            )
            with patch.object(
                simulation,
                "load_instance",
                return_value=instance,
            ), patch.object(
                simulation,
                "verified_instance_identity",
                return_value=route_result,
            ):
                prepared = simulation.prepare_project_case(
                    project,
                    case_id=0,
                    run_id="run_timeout",
                    instance_id=instance["instance_id"],
                )
                execute_evidence = evidence_payload(
                    tool="itasca_execute_task",
                    run_id="run_timeout",
                    task_id="timeout_task",
                    task_state="pending",
                    request=prepared["mcp_operation"]["arguments"],
                )
                execute_path = root / "execute_timeout.json"
                execute_path.write_text(
                    json.dumps(execute_evidence),
                    encoding="utf-8",
                )
                simulation.attach_task(
                    project,
                    "run_timeout",
                    evidence_path=execute_path,
                )
                timeout_evidence = evidence_payload(
                    tool="itasca_check_task_status",
                    run_id="run_timeout",
                    task_id="timeout_task",
                    task_state="timeout_unknown",
                )
                timeout_path = root / "timeout.json"
                timeout_path.write_text(
                    json.dumps(timeout_evidence),
                    encoding="utf-8",
                )
                result = simulation.record_status(
                    project,
                    "run_timeout",
                    evidence_path=timeout_path,
                )
                self.assertEqual(
                    result["run"]["task_status"],
                    "TIMEOUT_UNKNOWN",
                )
                self.assertEqual(
                    result["run"]["mcp_task_id"],
                    "timeout_task",
                )

    def test_ready_evidence_is_bound_to_current_identity(self) -> None:
        class Runtime:
            port = 9011

            def state(self) -> dict:
                return {}

            def process_identity(self, state=None) -> dict:
                return dict(IDENTITY)

            def preflight(self) -> dict:
                return {
                    "health": {"status": "success", "runtime_mode": "console"},
                    "probe": {"pid": IDENTITY["pid"], "dimension": 2},
                }

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            instance = fake_instance()
            runtime = Runtime()
            evidence = make_mcp_evidence(
                runtime,
                instance,
                tool="itasca_execute_code",
                output="PFC_HEADLESS_READY nonce-current",
            )
            self.assertIn("nonce-current", evidence["output"])
            path = root / "ready.json"
            path.write_text(json.dumps(evidence), encoding="utf-8")
            result = verify_connection(
                runtime,
                instance,
                mcp_evidence_path=path,
            )
            self.assertTrue(result["ready"])
            evidence["pid"] = 9999
            path.write_text(json.dumps(evidence), encoding="utf-8")
            with self.assertRaises(HeadlessError):
                verify_connection(runtime, instance, mcp_evidence_path=path)


if __name__ == "__main__":
    unittest.main()
