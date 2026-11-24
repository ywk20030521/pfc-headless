"""Agent-orchestrated PFC Run preparation, evidence recording and finalization."""
from __future__ import annotations

import json
import shutil
import csv
from pathlib import Path
from typing import Any

from run_case import finalize_prepared_run, prepare_run_directory_from_config

from .common import (
    HeadlessError,
    append_audit,
    atomic_write_json,
    read_json,
    utc_now,
    validate_id,
)
from .instance import load_instance, verified_instance_identity
from .preflight import preflight_config
from .mcp_evidence import (
    EXECUTION_TOOLS,
    INTERRUPT_TOOLS,
    STATUS_TOOLS,
    ensure_task_id_unique,
    extract_task_error,
    extract_task_id,
    extract_task_state,
    load_evidence,
    validate_evidence,
)
from .project import Project


def _route(project: Project, run_id: str, *, require_ready: bool = False) -> dict[str, Any]:
    record = project.get_run(run_id)
    instance_id = record.get("instance_id")
    if not instance_id:
        raise HeadlessError(
            f"Run {run_id} has no registered instance; prepare it with --instance-id"
        )
    instance, runtime, identity, fingerprint = verified_instance_identity(
        project,
        str(instance_id),
        require_ready=require_ready,
    )
    recorded_fingerprint = record.get("instance_identity_fingerprint")
    if recorded_fingerprint and recorded_fingerprint != fingerprint:
        raise HeadlessError(
            "INSTANCE_IDENTITY_MISMATCH: Run was prepared against another "
            "instance identity"
        )
    connection_id = str(
        record.get("mcp_connection_id")
        or instance.get("mcp_connection_id")
        or ""
    )
    if not connection_id:
        raise HeadlessError(
            f"Instance {instance_id} has no registered MCP connection identity"
        )
    return {
        "run": record,
        "instance": instance,
        "runtime": runtime,
        "identity": identity,
        "identity_fingerprint": fingerprint,
        "mcp_connection_id": connection_id,
    }


def _operation(
    route: dict[str, Any],
    *,
    tool: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "AGENT_ACTION_REQUIRED",
        "run_id": route["run"]["run_id"],
        "task_id": route["run"].get("mcp_task_id"),
        "instance_id": route["instance"]["instance_id"],
        "mcp_connection_id": route["mcp_connection_id"],
        "mcp_operation": {
            "tool": tool,
            "arguments": arguments,
        },
    }


def prepare_project_case(
    project: Project,
    *,
    case_id: int,
    run_id: str | None = None,
    parameters: dict[str, Any] | None = None,
    sampling: dict[str, Any] | None = None,
    instance_id: str,
    collection_plan: dict[str, Any] | None = None,
    feedback_id: str | None = None,
) -> dict[str, Any]:
    instance = load_instance(project, instance_id)
    if instance.get("state") != "READY":
        raise HeadlessError(
            f"Instance {instance_id} is {instance.get('state')}, not READY"
        )
    # Static preflight before creating any immutable run directory.
    from .common import read_json as _read_json
    _case = project.get_case(case_id)
    _cfg = _read_json(project.root / _case["config_path"])
    _preflight = preflight_config(_cfg)
    created = project.new_run(
        case_id,
        run_id=run_id,
        parameters=parameters,
        sampling=sampling,
        instance_id=instance_id,
        collection_plan=collection_plan,
        feedback_id=feedback_id,
    )
    return prepare_planned_run(project, str(created["record"]["run_id"]))


def prepare_planned_run(project: Project, run_id: str) -> dict[str, Any]:
    route = _route(project, run_id, require_ready=True)
    record = route["run"]
    if record.get("task_status") != "PREPARED":
        raise HeadlessError(
            f"Only PREPARED Runs can be prepared; {run_id} is {record.get('task_status')}"
        )
    run_root = project.run_root(run_id)
    launch_path = run_root / "launch.json"
    if launch_path.is_file():
        launch = read_json(launch_path)
    else:
        config = read_json(run_root / "input" / "config.json")
        launch = prepare_run_directory_from_config(
            config,
            run_root,
            allow_existing_managed_root=True,
        )
    nonce = str(record.get("execution_nonce") or "")
    if not nonce:
        raise HeadlessError(f"Run {run_id} has no execution nonce")
    description = (
        f"PFC Headless run_id={run_id} nonce={nonce} "
        f"instance_id={route['instance']['instance_id']}"
    )
    record = project.update_run(
        run_id,
        task_description=description,
        entry_script=str(Path(launch["entry_script"]).resolve()),
        mcp_connection_id=route["mcp_connection_id"],
        instance_identity_fingerprint=route["identity_fingerprint"],
        instance_snapshot={
            "instance_id": route["instance"]["instance_id"],
            "pid": route["identity"]["pid"],
            "executable_path": route["identity"]["executable"],
            "command_line": route["identity"].get("command_line", []),
            "bridge_port": route["instance"]["bridge_port"],
            "engine_type": route["instance"]["engine_type"],
        },
        prepared_utc=utc_now(),
    )
    append_audit(
        project.audit_path,
        "RUN_PREPARED_FOR_MCP",
        run_id=run_id,
        instance_id=route["instance"]["instance_id"],
        execution_nonce=nonce,
    )
    result = _operation(
        {**route, "run": record},
        tool="itasca_execute_task",
        arguments={
            "entry_script": str(Path(launch["entry_script"]).resolve()),
            "description": description,
        },
    )
    result["run_status"] = record["task_status"]
    result["launch"] = launch
    result["preflight"] = record.get("preflight") or {"status": "NOT_RECORDED"}
    result["execution_nonce"] = nonce
    return result


def attach_task(
    project: Project,
    run_id: str,
    *,
    evidence_path: str | Path,
) -> dict[str, Any]:
    route = _route(project, run_id)
    record = route["run"]
    if record.get("task_status") != "PREPARED":
        raise HeadlessError(
            f"Only PREPARED Runs can bind a task; {run_id} is {record.get('task_status')}"
        )
    evidence = load_evidence(evidence_path)
    task_id = extract_task_id(evidence)
    if not task_id:
        raise HeadlessError("Execute-task evidence does not contain task_id")
    ensure_task_id_unique(
        project.list_runs(),
        task_id=task_id,
        current_run_id=run_id,
    )
    validated = validate_evidence(
        evidence,
        tool="itasca_execute_task",
        run_id=run_id,
        instance_id=str(route["instance"]["instance_id"]),
        task_id=task_id,
        connection_id=route["mcp_connection_id"],
        identity_fingerprint=route["identity_fingerprint"],
    )
    request = validated.get("request") or {}
    expected_script = str(Path(str(record["entry_script"])).resolve())
    actual_script = str(Path(str(request.get("entry_script") or "")).resolve())
    if actual_script != expected_script:
        raise HeadlessError(
            f"MCP task entry_script mismatch: {actual_script} != {expected_script}"
        )
    description = str(request.get("description") or "")
    if record["execution_nonce"] not in description:
        raise HeadlessError("MCP task description does not contain the Run nonce")
    updated = project.update_run(
        run_id,
        task_status="SUBMITTED",
        mcp_task_id=task_id,
        mcp_evidence=validated,
    )
    append_audit(
        project.audit_path,
        "MCP_TASK_BOUND",
        run_id=run_id,
        task_id=task_id,
        mcp_connection_id=route["mcp_connection_id"],
    )
    _mark_feedback_running(project, updated)
    return {"run": updated, "mcp_evidence": validated}


def rebind_run(
    project: Project,
    run_id: str,
    *,
    instance_id: str,
    approved_by: str,
    reason: str,
) -> dict[str, Any]:
    """Explicitly rebind a PREPARED run to a new, verified READY instance.

    This is a deliberate escape hatch for the case where the original Console
    instance died before the run was submitted.  It never bypasses identity or
    connection verification: the target instance must be READY, the nonce and
    fingerprint are re-captured, and the old identity is preserved in the audit
    record.  Only PREPARED runs (no task submitted yet) may be rebound.
    """
    record = project.get_run(run_id)
    if record.get("task_status") != "PREPARED":
        raise HeadlessError(
            f"Only PREPARED Runs can be rebound; {run_id} is "
            f"{record.get('task_status')}"
        )
    if not approved_by or not reason:
        raise HeadlessError("rebind requires approved_by and reason")
    instance = load_instance(project, instance_id)
    if instance.get("state") != "READY":
        raise HeadlessError(f"Instance {instance_id} is not READY")
    _, runtime, identity, fingerprint = verified_instance_identity(
        project, instance_id, require_ready=True
    )
    connection_id = str(instance.get("mcp_connection_id") or "")
    if not connection_id:
        raise HeadlessError(f"Instance {instance_id} has no MCP connection identity")
    previous = {
        "instance_id": record.get("instance_id"),
        "mcp_connection_id": record.get("mcp_connection_id"),
        "instance_identity_fingerprint": record.get("instance_identity_fingerprint"),
        "execution_nonce": record.get("execution_nonce"),
        "prepared_utc": record.get("prepared_utc"),
    }
    # A fresh nonce is required: the old one was bound to the dead instance.
    from .common import new_id
    project.update_run(
        run_id,
        instance_id=instance_id,
        mcp_connection_id=connection_id,
        instance_identity_fingerprint=fingerprint,
        execution_nonce=new_id("exec"),
        instance_snapshot={
            "instance_id": instance_id,
            "pid": identity["pid"],
            "executable_path": identity["executable"],
            "command_line": identity.get("command_line", []),
            "bridge_port": instance.get("bridge_port"),
            "engine_type": instance.get("engine_type"),
        },
        rebind={
            "previous": previous,
            "approved_by": approved_by,
            "reason": reason,
            "rebound_utc": utc_now(),
        },
    )
    # Re-render the prepared launch so the new nonce/description is used.
    updated = project.get_run(run_id)
    prepared = prepare_planned_run(project, run_id)
    append_audit(
        project.audit_path,
        "RUN_REBOUND",
        run_id=run_id,
        from_instance=str(previous["instance_id"]),
        to_instance=instance_id,
        approved_by=approved_by,
        reason=reason,
    )
    return {"run": updated, "prepared": prepared, "previous": previous}


def status_operation(project: Project, run_id: str) -> dict[str, Any]:
    route = _route(project, run_id)
    task_id = route["run"].get("mcp_task_id")
    if not task_id:
        return {
            "status": "NO_TASK",
            "run_id": run_id,
            "task_status": route["run"].get("task_status"),
            "mcp_task_id": None,
        }
    return _operation(
        route,
        tool="itasca_check_task_status",
        arguments={"task_id": str(task_id)},
    )


def record_status(
    project: Project,
    run_id: str,
    *,
    evidence_path: str | Path,
) -> dict[str, Any]:
    route = _route(project, run_id)
    task_id = route["run"].get("mcp_task_id")
    if not task_id:
        raise HeadlessError(f"Run {run_id} has no MCP task ID")
    evidence = load_evidence(evidence_path)
    evidence_task = extract_task_id(evidence)
    if evidence_task and evidence_task != str(task_id):
        raise HeadlessError("MCP status evidence belongs to another task")
    validated = validate_evidence(
        evidence,
        tool=str(evidence.get("tool") or ""),
        run_id=run_id,
        instance_id=str(route["instance"]["instance_id"]),
        task_id=str(task_id),
        connection_id=route["mcp_connection_id"],
        identity_fingerprint=route["identity_fingerprint"],
    )
    if str(validated["tool"]) not in STATUS_TOOLS:
        raise HeadlessError("Status evidence must use an official MCP status tool")
    state = extract_task_state(validated)
    mapped = {
        "pending": "SUBMITTED",
        "running": "RUNNING",
        "completed": "COMPLETED",
        "failed": "FAILED",
        "error": "FAILED",
        "interrupted": "INTERRUPTED",
        "cancelled": "INTERRUPTED",
        "timeout_unknown": "TIMEOUT_UNKNOWN",
    }.get(state)
    if mapped is None:
        raise HeadlessError(
            f"MCP status evidence has no recognized task state: {state!r}"
        )
    error_summary = extract_task_error(validated) if mapped == "FAILED" else None
    updates: dict[str, Any] = {
        "task_status": mapped,
        "mcp_evidence": validated,
        "end_time": utc_now() if mapped in {"COMPLETED", "FAILED", "INTERRUPTED"} else route["run"].get("end_time"),
    }
    if error_summary is not None:
        # Keep the engine's real message on the Run itself so `run list` and
        # `run status` expose it without asking the user to dig into raw JSON.
        updates["error"] = error_summary
    updated = project.update_run(run_id, **updates)
    append_audit(
        project.audit_path,
        "MCP_TASK_STATUS_RECORDED",
        run_id=run_id,
        task_id=str(task_id),
        remote_status=state,
        local_status=mapped,
        error_summary=error_summary,
    )
    if mapped == "FAILED":
        _mark_feedback_failed(
            project,
            updated,
            error_summary or {"type": "MCPTaskFailed", "state": state},
        )
    return {
        "run": updated,
        "remote_status": state,
        "mcp_evidence": validated,
        "error_summary": error_summary,
    }


def retry_failed_run(
    project: Project,
    run_id: str,
    *,
    instance_id: str | None = None,
    new_run_id: str | None = None,
    approved_by: str = "agent",
    reason: str = "Retry after fixing the failed attempt",
) -> dict[str, Any]:
    """Create a fresh immutable Run from a failed attempt.

    Failed Runs stay immutable for audit.  This operation preserves the same
    Case, parameters and collection plan while picking up the current case
    configuration, so a corrected command sequence can be re-run without
    deleting evidence or guessing a new run id.
    """
    record = project.get_run(run_id)
    if record.get("task_status") not in {"FAILED", "TIMEOUT_UNKNOWN", "INTERRUPTED"}:
        raise HeadlessError(
            f"Only FAILED/TIMEOUT_UNKNOWN/INTERRUPTED Runs can be retried; "
            f"{run_id} is {record.get('task_status')}"
        )
    config_path = project.run_root(run_id) / "input" / "config.json"
    source_config = read_json(config_path) if config_path.is_file() else {}
    parameters = dict(
        ((source_config.get("headless") or {}).get("parameters") or {})
    )
    created = project.new_run(
        int(record["case_id"]),
        run_id=new_run_id,
        parameters=parameters,
        sampling=None,
        instance_id=instance_id or record.get("instance_id"),
        collection_plan=record.get("collection_plan"),
    )
    append_audit(
        project.audit_path,
        "RUN_RETRY_CREATED",
        source_run_id=run_id,
        new_run_id=created["record"]["run_id"],
        approved_by=approved_by,
        reason=reason,
    )
    return {
        "source_run_id": run_id,
        "run": created["record"],
        "run_root": str(created["run_root"]),
        "config_path": str(created["config_path"]),
    }


def interrupt_operation(project: Project, run_id: str) -> dict[str, Any]:
    route = _route(project, run_id)
    task_id = route["run"].get("mcp_task_id")
    if not task_id:
        raise HeadlessError(f"Run {run_id} has no MCP task ID")
    return _operation(
        route,
        tool="itasca_interrupt_task",
        arguments={"task_id": str(task_id)},
    )


def record_interrupt(
    project: Project,
    run_id: str,
    *,
    evidence_path: str | Path,
) -> dict[str, Any]:
    route = _route(project, run_id)
    task_id = route["run"].get("mcp_task_id")
    if not task_id:
        raise HeadlessError(f"Run {run_id} has no MCP task ID")
    evidence = load_evidence(evidence_path)
    validated = validate_evidence(
        evidence,
        tool=str(evidence.get("tool") or ""),
        run_id=run_id,
        instance_id=str(route["instance"]["instance_id"]),
        task_id=str(task_id),
        connection_id=route["mcp_connection_id"],
        identity_fingerprint=route["identity_fingerprint"],
    )
    if validated["tool"] not in INTERRUPT_TOOLS:
        raise HeadlessError("Interrupt evidence must use itasca_interrupt_task")
    updated = project.update_run(
        run_id,
        task_status="INTERRUPT_REQUESTED",
        mcp_evidence=validated,
        end_time=None,
    )
    append_audit(
        project.audit_path,
        "MCP_INTERRUPT_RECORDED",
        run_id=run_id,
        task_id=str(task_id),
    )
    return {"run": updated, "mcp_evidence": validated}


def finalize_run(project: Project, run_id: str, *, export_npy: bool = False) -> dict[str, Any]:
    route = _route(project, run_id)
    record = route["run"]
    if record.get("task_status") != "COMPLETED":
        raise HeadlessError(
            f"Only COMPLETED Runs can be finalized; {run_id} is {record.get('task_status')}"
        )
    run_root = project.run_root(run_id)
    launch = read_json(run_root / "launch.json")
    delivery = project.root / record["output_path"]
    execution = {
        "transport": "itasca-mcp",
        "task_id": record.get("mcp_task_id"),
        "task_status": "completed",
        "mcp_evidence": record.get("mcp_evidence"),
        "execution_nonce": record.get("execution_nonce"),
    }
    try:
        result = finalize_prepared_run(
            launch,
            run_root=run_root,
            execution=execution,
            standardized_output=delivery,
            title=run_id,
            pfc_version=route["instance"].get("engine_version"),
            export_npy=export_npy,
        )
    except BaseException as exc:
        if delivery.exists() and not (delivery / "delivery_manifest.json").is_file():
            failed_root = project.root / "failed_deliveries"
            failed_root.mkdir(parents=True, exist_ok=True)
            timestamp = utc_now().replace(":", "").replace("+", "_")
            shutil.move(str(delivery), str(failed_root / f"{run_id}_{timestamp}"))
        updated = project.update_run(
            run_id,
            task_status="INVALID",
            finalization={
                "status": "FAILED",
                "type": type(exc).__name__,
                "message": str(exc),
                "ended_utc": utc_now(),
            },
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        _mark_feedback_failed(project, updated, updated["error"])
        raise
    updated = project.update_run(
        run_id,
        finalization={
            "status": "VALIDATED",
            "delivery": str(delivery),
            "ended_utc": utc_now(),
        },
        error=None,
    )
    append_audit(
        project.audit_path,
        "RUN_FINALIZED_FROM_MCP_EVIDENCE",
        run_id=run_id,
        delivery=str(delivery),
    )
    _mark_feedback_validated(project, updated, delivery)
    return {"run": updated, "execution": result, "delivery": str(delivery)}


def recover_run(
    project: Project,
    run_id: str,
    *,
    reason: str,
    chunk_frames: int = 10,
) -> dict[str, Any]:
    route = _route(project, run_id)
    run_root = project.run_root(run_id)
    data_dir = run_root / "data"
    recovery_dir = run_root / "metadata" / "recovery"
    recovery_dir.mkdir(parents=True, exist_ok=True)
    try:
        compact = _scan_current_capture(data_dir, chunk_frames=chunk_frames)
        status = "READY_FOR_EXPLICIT_CONSUMPTION"
        result = {
            "status": status,
            "reason": reason,
            "run_id": run_id,
            "instance_id": route["instance"]["instance_id"],
            "frames": compact["frames"],
            "blocks": compact["blocks"],
            "raw_tail_rejections": compact["raw_tail_rejections"],
            "incomplete_frame_rows": compact["incomplete_frame_rows"],
            "viewer_generated": False,
            "derived_science_generated": False,
        }
        local_status = "INTERRUPTED"
    except BaseException as exc:
        status = "INVALID"
        result = {
            "status": status,
            "reason": reason,
            "run_id": run_id,
            "instance_id": route["instance"]["instance_id"],
            "error_type": type(exc).__name__,
            "error": str(exc),
            "viewer_generated": False,
            "derived_science_generated": False,
        }
        local_status = "INVALID"
    atomic_write_json(recovery_dir / "recovery_result.json", result)
    updated = project.update_run(
        run_id,
        task_status=local_status,
        finalization={"status": status, "reason": reason, "ended_utc": utc_now()},
        error=(
            None
            if status != "INVALID"
            else {"type": "RecoveryError", "message": result.get("error", "")}
        ),
    )
    append_audit(
        project.audit_path,
        "RUN_RECOVERY_COMPLETED",
        run_id=run_id,
        status=status,
        reason=reason,
    )
    return {"run": updated, "recovery": result}


def _scan_current_capture(data_dir: Path, *, chunk_frames: int) -> dict[str, Any]:
    required = {
        "frame_index": data_dir / "raw" / "frame_index.csv",
        "ball_frames": data_dir / "raw" / "ball_frames.csv",
        "wall_vertices": data_dir / "raw" / "wall_vertices.csv",
    }
    parsed: dict[str, list[dict[str, str]]] = {}
    tails: dict[str, dict[str, int]] = {}
    for name, path in required.items():
        if not path.is_file():
            raise HeadlessError(f"Recovery input is missing: {path}")
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise HeadlessError(f"Recovery input is empty: {path}") from exc
            rows = []
            invalid_indices = []
            for index, row in enumerate(reader, start=2):
                if len(row) != len(header):
                    invalid_indices.append(index)
                    continue
                rows.append(dict(zip(header, row)))
        if invalid_indices:
            with path.open("r", encoding="utf-8", newline="") as handle:
                total_rows = max(0, sum(1 for _ in handle) - 1)
            if min(invalid_indices) <= len(rows):
                raise HeadlessError(
                    f"Recovery found a non-tail malformed row in {path}"
                )
            tails[name] = {
                "invalid_rows": len(invalid_indices),
                "total_rows": total_rows,
            }
        parsed[name] = rows
    frames: dict[int, dict[str, str]] = {}
    previous_cycle = None
    for row in parsed["frame_index"]:
        frame_id = int(row["frame_id"])
        cycle = int(row["cycle"])
        if frame_id in frames:
            raise HeadlessError(f"Duplicate recovery frame ID: {frame_id}")
        if previous_cycle is not None and cycle < previous_cycle:
            raise HeadlessError("Recovery frames are not ordered by Cycle")
        previous_cycle = cycle
        frames[frame_id] = row
    if not frames:
        raise HeadlessError("Recovery found no committed frame-index rows")
    ball_counts: dict[int, int] = {}
    for row in parsed["ball_frames"]:
        frame_id = int(row["frame_id"])
        if frame_id not in frames:
            raise HeadlessError(
                f"Recovery found Ball rows for unknown frame {frame_id}"
            )
        ball_counts[frame_id] = ball_counts.get(frame_id, 0) + 1
    missing_ball_frames = sorted(set(frames) - set(ball_counts))
    if missing_ball_frames:
        raise HeadlessError(
            f"Recovery frames have no Ball rows: {missing_ball_frames}"
        )
    chunk = max(1, int(chunk_frames))
    return {
        "frames": len(frames),
        "blocks": (len(frames) + chunk - 1) // chunk,
        "raw_tail_rejections": tails,
        "incomplete_frame_rows": 0,
        "frame_ids": sorted(frames),
        "ball_counts": {
            str(frame_id): ball_counts[frame_id] for frame_id in sorted(ball_counts)
        },
    }


def _mark_feedback_running(project: Project, run: dict[str, Any]) -> None:
    feedback_id = run.get("feedback_id")
    if not feedback_id:
        return
    from .feedback import mark_feedback_running

    mark_feedback_running(project, str(feedback_id), run_id=str(run["run_id"]))


def _mark_feedback_failed(
    project: Project,
    run: dict[str, Any],
    error: dict[str, Any],
) -> None:
    feedback_id = run.get("feedback_id")
    if not feedback_id:
        return
    from .feedback import finalize_feedback_attempt

    finalize_feedback_attempt(
        project,
        str(feedback_id),
        run_id=str(run["run_id"]),
        status="FAILED",
        error=error,
    )


def _mark_feedback_validated(
    project: Project,
    run: dict[str, Any],
    delivery: Path,
) -> None:
    feedback_id = run.get("feedback_id")
    if not feedback_id:
        return
    from .feedback import finalize_feedback_attempt

    finalize_feedback_attempt(
        project,
        str(feedback_id),
        run_id=str(run["run_id"]),
        status="VALIDATED",
        delivery=delivery,
    )


# Compatibility names remain preparation-only; they never submit to Bridge.
def run_project_case(project: Project, **kwargs: Any) -> dict[str, Any]:
    return prepare_project_case(project, **kwargs)


def execute_planned_run(project: Project, run_id: str, **_: Any) -> dict[str, Any]:
    return prepare_planned_run(project, run_id)

