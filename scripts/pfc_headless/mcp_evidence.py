"""Validation helpers for Agent-supplied itasca-mcp operation evidence."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import HeadlessError, read_json


EVIDENCE_SCHEMA_VERSION = "1.0.0"
EXECUTION_TOOLS = {"itasca_execute_task"}
STATUS_TOOLS = {"itasca_check_task_status", "itasca_list_tasks"}
INTERRUPT_TOOLS = {"itasca_interrupt_task"}


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def evidence_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise HeadlessError(f"MCP evidence requires {name}")
    return text


def _timestamp(value: Any, name: str) -> datetime:
    text = _required_text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HeadlessError(f"MCP evidence {name} is not ISO-8601: {text!r}") from exc
    if parsed.tzinfo is None:
        raise HeadlessError(f"MCP evidence {name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def load_evidence(path: str | Path) -> dict[str, Any]:
    evidence = read_json(Path(path))
    if not isinstance(evidence, dict):
        raise HeadlessError("MCP evidence must be a JSON object")
    if evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise HeadlessError(
            f"MCP evidence schema_version must be {EVIDENCE_SCHEMA_VERSION!r}"
        )
    return evidence


def validate_evidence(
    evidence: dict[str, Any],
    *,
    tool: str,
    run_id: str,
    instance_id: str,
    task_id: str,
    connection_id: str,
    identity_fingerprint: str,
) -> dict[str, Any]:
    actual_tool = _required_text(evidence.get("tool"), "tool")
    if actual_tool != tool:
        raise HeadlessError(
            f"MCP evidence tool mismatch: {actual_tool!r} != {tool!r}"
        )
    expected = {
        "run_id": run_id,
        "instance_id": instance_id,
        "task_id": task_id,
        "connection_id": connection_id,
        "identity_fingerprint": identity_fingerprint,
    }
    for name, value in expected.items():
        actual = _required_text(evidence.get(name), name)
        if actual != str(value):
            raise HeadlessError(
                f"MCP evidence {name} mismatch: {actual!r} != {value!r}"
            )
    observed = _timestamp(evidence.get("observed_utc"), "observed_utc")
    if observed > datetime.now(timezone.utc).replace(microsecond=0):
        raise HeadlessError("MCP evidence timestamp is in the future")
    if "request" not in evidence or "response" not in evidence:
        raise HeadlessError("MCP evidence requires request and response")
    result = dict(evidence)
    result["evidence_sha256"] = evidence_sha256(evidence)
    result["validated_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return result


def extract_task_id(evidence: dict[str, Any]) -> str | None:
    explicit = evidence.get("task_id")
    if explicit:
        return str(explicit)
    response = evidence.get("response")
    if isinstance(response, dict):
        for key in ("task_id", "taskId"):
            if response.get(key):
                return str(response[key])
        data = response.get("data")
        if isinstance(data, dict):
            for key in ("task_id", "taskId"):
                if data.get(key):
                    return str(data[key])
    return None


def extract_task_error(evidence: dict[str, Any]) -> dict[str, Any] | None:
    """Return a concise engine-side error from MCP status evidence.

    Task responses nest the real error differently across the MCP wrapper and
    the bridge.  Search the known locations, then, as a last resort, parse an
    embedded capture result JSON string.  Never return the whole traceback.
    """
    response = evidence.get("response")
    if not isinstance(response, dict):
        return None
    candidates: list[Any] = [response.get("error")]
    data = response.get("data")
    if isinstance(data, dict):
        candidates.extend([data.get("error"), data.get("message")])
        output = data.get("output")
        if isinstance(output, str) and output.strip():
            try:
                parsed = json.loads(output)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                errors = parsed.get("errors")
                if isinstance(errors, list) and errors:
                    first = errors[0]
                    if isinstance(first, dict):
                        message = str(first.get("message") or "").strip()
                        if message:
                            return {
                                "type": str(first.get("type") or "EngineError"),
                                "message": message[:600],
                                "source": "engine_result",
                            }
            candidates.append(output)
    for candidate in candidates:
        if isinstance(candidate, dict):
            message = str(candidate.get("message") or "").strip()
            if message:
                return {
                    "type": str(candidate.get("code") or candidate.get("type") or "MCPError"),
                    "message": message[:600],
                    "source": "mcp_response",
                }
        elif isinstance(candidate, str):
            text = " ".join(candidate.split())
            if text:
                return {"type": "MCPTaskError", "message": text[:600], "source": "mcp_response"}
    return None


def extract_task_state(evidence: dict[str, Any]) -> str:
    explicit = str(evidence.get("task_state") or "").strip().lower()
    if explicit:
        return explicit
    response = evidence.get("response")
    for candidate in (evidence, response):
        if not isinstance(candidate, dict):
            continue
        for key in ("task_status", "status"):
            value = str(candidate.get(key) or "").strip().lower()
            if value in {
                "pending",
                "running",
                "completed",
                "failed",
                "error",
                "interrupted",
                "cancelled",
                "timeout_unknown",
            }:
                return value
        data = candidate.get("data")
        if isinstance(data, dict):
            for key in ("task_status", "status"):
                value = str(data.get(key) or "").strip().lower()
                if value in {
                    "pending",
                    "running",
                    "completed",
                    "failed",
                    "error",
                    "interrupted",
                    "cancelled",
                    "timeout_unknown",
                }:
                    return value
            task = data.get("task")
            if isinstance(task, dict) and task.get("status"):
                return str(task["status"]).lower()
    return "unknown"


def ensure_task_id_unique(
    runs: list[dict[str, Any]],
    *,
    task_id: str,
    current_run_id: str,
) -> None:
    for record in runs:
        if (
            record.get("run_id") != current_run_id
            and str(record.get("mcp_task_id") or "") == task_id
        ):
            raise HeadlessError(
                f"MCP task ID {task_id!r} is already bound to Run {record['run_id']}"
            )

