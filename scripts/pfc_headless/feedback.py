"""Analysis feedback validation and new-Run proposal generation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (
    HeadlessError,
    append_audit,
    atomic_write_json,
    ensure_within,
    read_json,
    utc_now,
    validate_id,
)
from .contracts import validate_document
from .data import verify_delivery
from .project import FEEDBACK_DIR, Project


SCALAR_TYPES = (str, int, float, bool)


def _feedback_path(project: Project, feedback_id: str) -> Path:
    return project.root / FEEDBACK_DIR / f"{validate_id(feedback_id, 'feedback_id')}.json"


def ingest_feedback(project: Project, source_path: str | Path) -> dict[str, Any]:
    source = Path(source_path).resolve()
    feedback = read_json(source)
    validate_document("feedback", feedback)
    if "visualization" not in str(feedback.get("source", "")).lower():
        raise HeadlessError(
            "Feedback source must identify pfc-scientific-visualization"
        )
    run_id = str(feedback["run_id"])
    run_record = project.get_run(run_id)
    delivery_root = project.root / run_record["output_path"]
    delivery = verify_delivery(delivery_root)
    if delivery["status"] != "PASS":
        raise HeadlessError(
            f"Reference delivery is invalid: {delivery['errors']}"
        )
    for relative in feedback.get("referenced_artifacts", []):
        path = Path(relative)
        if not path.is_absolute():
            path = project.root / path
        path = path.resolve()
        try:
            ensure_within(project.root / "analysis", path, "Feedback artifact")
        except HeadlessError:
            ensure_within(project.root / "deliveries", path, "Feedback artifact")
        if not path.is_file() and not path.is_dir():
            raise HeadlessError(f"Feedback artifact does not exist: {path}")

    metadata = delivery["metadata"]
    channels = {
        str(channel["id"]): channel
        for case in delivery["experiment"].get("cases", [])
        for channel in case.get("channels", [])
    }
    unknown = sorted(set(feedback.get("missing_data", [])) - set(channels))
    if unknown:
        raise HeadlessError(
            f"Feedback references unknown data channels: {unknown}"
        )
    time_range = feedback.get("recommended_time_range")
    if time_range is not None:
        start, end = float(time_range[0]), float(time_range[1])
        original_start, original_end = [
            float(value) for value in metadata["time_range"]
        ]
        if end < start:
            raise HeadlessError("Recommended time range is reversed")
        if start < original_start or end > original_end:
            raise HeadlessError(
                "Recommended time range is outside the referenced Run: "
                f"[{start}, {end}] not within [{original_start}, {original_end}]"
            )
    sampling = feedback.get("recommended_sampling") or {}
    mode = str(sampling.get("mode", "cycle"))
    interval = float(sampling.get("interval", metadata["sampling_configuration"].get("value") or 1))
    if mode not in {"cycle", "time", "event"}:
        raise HeadlessError(f"Unsupported recommended sampling mode: {mode}")
    if mode in {"cycle", "time"} and interval <= 0:
        raise HeadlessError("Recommended Cycle/time sampling interval must be positive")
    for name, value in (feedback.get("recommended_parameters") or {}).items():
        if not isinstance(value, SCALAR_TYPES):
            raise HeadlessError(
                f"Recommended parameter {name!r} must be a scalar; arbitrary values are forbidden"
            )
    feedback["status"] = "PENDING_APPROVAL"
    feedback.setdefault("attempts", [])
    feedback.setdefault("active_attempt_run_id", None)
    feedback["review"] = {
        "status": "PENDING",
        "checks": {
            "schema": "PASS",
            "run_exists": "PASS",
            "delivery_valid": "PASS",
            "referenced_artifacts": "PASS",
            "missing_channels_declared": "PASS",
            "time_range_valid": "PASS",
            "sampling_rule_valid": "PASS",
            "parameters_are_scalar": "PASS",
            "arbitrary_code_forbidden": True,
        },
        "received_utc": utc_now(),
    }
    output = _feedback_path(project, str(feedback["feedback_id"]))
    if output.exists():
        raise FileExistsError(f"Feedback already exists: {output}")
    atomic_write_json(output, feedback)
    append_audit(
        project.audit_path,
        "FEEDBACK_RECEIVED",
        feedback_id=feedback["feedback_id"],
        run_id=run_id,
    )
    return {"path": str(output), "feedback": feedback}


def approve_feedback(
    project: Project,
    feedback_id: str,
    *,
    approved_by: str,
    rationale: str,
) -> dict[str, Any]:
    path = _feedback_path(project, feedback_id)
    feedback = read_json(path)
    if feedback.get("status") != "PENDING_APPROVAL":
        raise HeadlessError("Only PENDING_APPROVAL feedback can be approved")
    if not approved_by.strip() or not rationale.strip():
        raise HeadlessError("Approval requires an approver and rationale")
    feedback["status"] = "APPROVED"
    feedback["review"] = {
        **(feedback.get("review") or {}),
        "status": "APPROVED",
        "approved_by": approved_by,
        "rationale": rationale,
        "approved_utc": utc_now(),
    }
    validate_document("feedback", feedback)
    atomic_write_json(path, feedback)
    append_audit(
        project.audit_path,
        "FEEDBACK_APPROVED",
        feedback_id=feedback_id,
        approved_by=approved_by,
    )
    return {"path": str(path), "feedback": feedback}


def prepare_feedback_run(
    project: Project,
    feedback_id: str,
    *,
    run_id: str | None = None,
    instance_id: str | None = None,
) -> dict[str, Any]:
    path = _feedback_path(project, feedback_id)
    feedback = read_json(path)
    if feedback.get("status") not in {"APPROVED", "FAILED"}:
        raise HeadlessError(
            "Only APPROVED or retryable FAILED feedback may create a new Run"
        )
    if feedback.get("active_attempt_run_id"):
        raise HeadlessError(
            "Feedback already has an active Run attempt: "
            f"{feedback['active_attempt_run_id']}"
        )
    original = project.get_run(str(feedback["run_id"]))
    sampling = feedback.get("recommended_sampling") or {}
    collection_plan = sampling.get("collection_plan")
    created = project.new_run(
        int(original["case_id"]),
        run_id=run_id,
        parameters=feedback.get("recommended_parameters") or {},
        sampling=sampling,
        instance_id=instance_id,
        collection_plan=(
            collection_plan if isinstance(collection_plan, dict) else None
        ),
        feedback_id=feedback_id,
    )
    attempt = {
        "run_id": created["record"]["run_id"],
        "status": "PROPOSED",
        "created_utc": utc_now(),
        "started_utc": None,
        "ended_utc": None,
        "error": None,
    }
    feedback["status"] = "PROPOSED"
    feedback["active_attempt_run_id"] = created["record"]["run_id"]
    feedback.setdefault("attempts", []).append(attempt)
    feedback["review"] = {
        **(feedback.get("review") or {}),
        "proposed_run_id": created["record"]["run_id"],
        "proposed_utc": utc_now(),
    }
    validate_document("feedback", feedback)
    atomic_write_json(path, feedback)
    append_audit(
        project.audit_path,
        "FEEDBACK_NEW_RUN_CREATED",
        feedback_id=feedback_id,
        original_run_id=feedback["run_id"],
        new_run_id=created["record"]["run_id"],
    )
    return {
        "run": created["record"],
        "run_root": str(created["run_root"]),
        "config_path": str(created["config_path"]),
        "feedback_path": str(path),
    }


def mark_feedback_running(
    project: Project,
    feedback_id: str,
    *,
    run_id: str,
) -> dict[str, Any]:
    path = _feedback_path(project, feedback_id)
    feedback = read_json(path)
    active = str(feedback.get("active_attempt_run_id") or "")
    if active != run_id:
        raise HeadlessError(
            f"Feedback active attempt {active!r} does not match Run {run_id!r}"
        )
    if feedback.get("status") != "PROPOSED":
        raise HeadlessError(
            f"Only PROPOSED feedback can enter RUNNING; current={feedback.get('status')}"
        )
    feedback["status"] = "RUNNING"
    for attempt in feedback.get("attempts", []):
        if attempt.get("run_id") == run_id:
            attempt["status"] = "RUNNING"
            attempt["started_utc"] = utc_now()
    validate_document("feedback", feedback)
    atomic_write_json(path, feedback)
    append_audit(
        project.audit_path,
        "FEEDBACK_RUN_STARTED",
        feedback_id=feedback_id,
        run_id=run_id,
    )
    return {"path": str(path), "feedback": feedback}


def finalize_feedback_attempt(
    project: Project,
    feedback_id: str,
    *,
    run_id: str,
    status: str,
    error: dict[str, Any] | None = None,
    delivery: str | Path | None = None,
) -> dict[str, Any]:
    if status not in {"VALIDATED", "FAILED"}:
        raise HeadlessError("Feedback attempt terminal status must be VALIDATED or FAILED")
    path = _feedback_path(project, feedback_id)
    feedback = read_json(path)
    if str(feedback.get("active_attempt_run_id") or "") != run_id:
        raise HeadlessError(
            f"Feedback active attempt {feedback.get('active_attempt_run_id')!r} "
            f"does not match Run {run_id!r}"
        )
    missing_checks: dict[str, str] = {}
    if status == "VALIDATED":
        if delivery is None:
            raise HeadlessError("VALIDATED feedback requires a delivery")
        verification = verify_delivery(delivery)
        if verification["status"] != "PASS":
            status = "FAILED"
            error = {
                "type": "DeliveryValidationError",
                "message": "; ".join(verification["errors"]),
            }
        else:
            channels = {
                str(channel["id"]): channel
                for case in verification["experiment"].get("cases", [])
                for channel in case.get("channels", [])
            }
            for channel_id in feedback.get("missing_data", []):
                channel_status = str(
                    channels.get(str(channel_id), {}).get("status")
                    or channels.get(str(channel_id), {}).get("source")
                    or "NOT_CAPTURED"
                )
                missing_checks[str(channel_id)] = channel_status
                if channel_status in {"NOT_CAPTURED", "NOT_SUPPORTED", "UNKNOWN"}:
                    status = "FAILED"
                    error = {
                        "type": "MissingDataUnresolved",
                        "message": f"Feedback channel is still unavailable: {channel_id}",
                    }
                    break
    feedback["status"] = status
    feedback["active_attempt_run_id"] = None
    for attempt in feedback.get("attempts", []):
        if attempt.get("run_id") == run_id:
            attempt["status"] = status
            attempt["ended_utc"] = utc_now()
            attempt["error"] = error
            attempt["missing_channel_status"] = missing_checks
    feedback["review"] = {
        **(feedback.get("review") or {}),
        "last_attempt_run_id": run_id,
        "last_validation_status": status,
        "last_validation_utc": utc_now(),
        "missing_channel_status": missing_checks,
    }
    validate_document("feedback", feedback)
    atomic_write_json(path, feedback)
    append_audit(
        project.audit_path,
        f"FEEDBACK_{status}",
        feedback_id=feedback_id,
        run_id=run_id,
    )
    return {"path": str(path), "feedback": feedback}


def make_plotting_feedback_example(run_id: str) -> dict[str, Any]:
    """Return a schema-valid template; it is not experimental evidence."""
    return {
        "schema_version": "1.0.0",
        "contract": "pfc.analysis-findings@1.0.0",
        "feedback_id": "feedback_template",
        "run_id": run_id,
        "source": "pfc-scientific-visualization",
        "referenced_artifacts": [],
        "findings": [],
        "missing_data": [],
        "recommended_sampling": {
            "mode": "cycle",
            "interval": 1,
            "capture_contacts": False,
        },
        "recommended_parameters": {},
        "recommended_actions": [],
        "status": "RECEIVED",
        "attempts": [],
        "active_attempt_run_id": None,
        "review": None,
        "produced_utc": utc_now(),
    }

