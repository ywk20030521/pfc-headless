"""Managed isolated Console instance registry."""
from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

from console_runtime import ConsoleRuntime

from .common import (
    HeadlessError,
    append_audit,
    atomic_write_json,
    new_id,
    read_json,
    utc_now,
    validate_id,
)
from .contracts import make_instance, validate_document
from .project import INSTANCES_DIR, Project


def instance_dir(project: Project, instance_id: str) -> Path:
    return project.root / INSTANCES_DIR / validate_id(instance_id, "instance_id")


def identity_fingerprint(
    identity: dict[str, Any],
    *,
    instance_id: str,
    engine_type: str,
    bridge_port: int,
) -> str:
    payload = {
        "instance_id": instance_id,
        "engine_type": engine_type,
        "bridge_port": int(bridge_port),
        "pid": int(identity["pid"]),
        "executable": str(Path(identity["executable"]).resolve()),
        "command_line": [str(item) for item in identity.get("command_line", [])],
        "create_time": float(identity.get("create_time", 0.0)),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def start_instance(
    project: Project,
    *,
    dimension: int,
    port: int,
    engine: str | Path | None = None,
    instance_id: str | None = None,
    mcp_connection_id: str | None = None,
) -> dict[str, Any]:
    instance_id = validate_id(instance_id or new_id("instance"), "instance_id")
    root = instance_dir(project, instance_id)
    if root.exists():
        raise FileExistsError(f"Instance already exists: {root}")
    root.mkdir(parents=True)
    runtime = ConsoleRuntime(
        root,
        dimension=dimension,
        port=port,
        engine=engine,
        instance_id=instance_id,
    )
    state = runtime.start()
    identity = runtime.process_identity(state)
    nonce = secrets.token_hex(16)
    nonce_path = root / "readiness_nonce.txt"
    nonce_path.write_text(nonce + "\n", encoding="utf-8", newline="\n")
    connection_id = (
        mcp_connection_id or f"mcp_{instance_id}_{port}"
    )
    record = make_instance(
        instance_id=instance_id,
        engine_type=runtime.engine_info["engine_type"],
        executable_path=str(runtime.engine),
        pid=int(state["pid"]),
        bridge_port=port,
        bootstrap_path=str(runtime.bootstrap_path),
        state="ATTACHED",
    )
    record.update(
        {
            "engine_version": runtime.engine_info.get("engine_version"),
            "workdir": str(root),
            "command_line": state.get("command_line"),
            "executable_sha256": runtime.engine_info["file"]["sha256"],
            "started_utc": state.get("started_utc") or utc_now(),
            "identity_fingerprint": identity_fingerprint(
                identity,
                instance_id=instance_id,
                engine_type=runtime.engine_info["engine_type"],
                bridge_port=port,
            ),
            "mcp_connection_id": connection_id,
            "readiness_nonce": nonce,
            "readiness_nonce_path": str(nonce_path),
            "mcp_verified_utc": None,
            "mcp_evidence_expires_utc": None,
            "evidence_status": "NOT_VERIFIED",
        }
    )
    validate_document("instance", record)
    atomic_write_json(root / "instance.json", record)
    append_audit(
        project.audit_path,
        "INSTANCE_STARTED",
        instance_id=instance_id,
        pid=state["pid"],
        port=port,
        engine=str(runtime.engine),
    )
    return record


def verified_instance_identity(
    project: Project,
    instance_id: str,
    *,
    require_ready: bool = False,
) -> tuple[dict[str, Any], ConsoleRuntime, dict[str, Any], str]:
    record = load_instance(project, instance_id)
    if require_ready and record.get("state") != "READY":
        raise HeadlessError(
            f"Instance {instance_id} is {record.get('state')}, not READY"
        )
    runtime, record = runtime_for(project, instance_id)
    state = runtime.state()
    identity = runtime.process_identity(state)
    fingerprint = identity_fingerprint(
        identity,
        instance_id=instance_id,
        engine_type=record["engine_type"],
        bridge_port=int(record["bridge_port"]),
    )
    expected = record.get("identity_fingerprint")
    if expected and expected != fingerprint:
        raise HeadlessError(
            "INSTANCE_IDENTITY_MISMATCH: current process no longer matches "
            f"registered instance {instance_id}"
        )
    if not expected:
        record = update_instance(
            project,
            instance_id,
            identity_fingerprint=fingerprint,
        )
    return record, runtime, identity, fingerprint


def load_instance(project: Project, instance_id: str) -> dict[str, Any]:
    path = instance_dir(project, instance_id) / "instance.json"
    if not path.is_file():
        raise HeadlessError(f"Instance does not exist: {instance_id}")
    record = read_json(path)
    validate_document("instance", record)
    return record


def runtime_for(project: Project, instance_id: str) -> tuple[ConsoleRuntime, dict[str, Any]]:
    record = load_instance(project, instance_id)
    runtime = ConsoleRuntime(
        Path(record["workdir"]),
        dimension=2 if record["engine_type"] == "PFC2D_CONSOLE" else 3,
        port=int(record["bridge_port"]),
        engine=record["executable_path"],
        instance_id=instance_id,
    )
    return runtime, record


def update_instance(
    project: Project,
    instance_id: str,
    **updates: Any,
) -> dict[str, Any]:
    path = instance_dir(project, instance_id) / "instance.json"
    record = read_json(path)
    record.update(updates)
    validate_document("instance", record)
    atomic_write_json(path, record)
    return record


def stop_instance(
    project: Project,
    instance_id: str,
    *,
    save_model: bool = True,
    save_name: str | None = None,
    allow_unsaved: bool = False,
) -> dict[str, Any]:
    runtime, record = runtime_for(project, instance_id)
    result = runtime.stop(
        save_model=save_model,
        save_name=save_name,
        allow_unsaved=allow_unsaved,
    )
    if result.get("status") == "STOPPED":
        record.update(
            {
                "state": "STOPPED",
                "stopped_utc": utc_now(),
                "stop_result": result,
            }
        )
        validate_document("instance", record)
        atomic_write_json(
            instance_dir(project, instance_id) / "instance.json",
            record,
        )
        append_audit(
            project.audit_path,
            "INSTANCE_STOPPED",
            instance_id=instance_id,
            method=result.get("method"),
            pid=record.get("pid"),
        )
    return result


def list_instances(project: Project) -> list[dict[str, Any]]:
    root = project.root / INSTANCES_DIR
    records = []
    for path in sorted(root.glob("*/instance.json")):
        record = read_json(path)
        validate_document("instance", record)
        records.append(record)
    return records

