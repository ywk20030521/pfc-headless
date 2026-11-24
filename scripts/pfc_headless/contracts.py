"""JSON Schema loading and essential structural validation."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .common import SCHEMA_VERSION, HeadlessError, utc_now


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "schema"
SCHEMAS = {
    "project": "project.schema.json",
    "case": "case.schema.json",
    "instance": "instance.schema.json",
    "run": "run.schema.json",
    "manifest": "manifest.schema.json",
    "metadata": "metadata.schema.json",
    "feedback": "feedback.schema.json",
}


def load_schema(name: str) -> dict[str, Any]:
    try:
        filename = SCHEMAS[name]
    except KeyError as exc:
        raise HeadlessError(f"Unknown schema {name!r}") from exc
    return json.loads((SCHEMA_ROOT / filename).read_text(encoding="utf-8"))


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _resolve_ref(root_schema: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise HeadlessError(f"Only local schema references are supported: {reference}")
    value: Any = root_schema
    for part in reference[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def _validate(
    value: Any,
    schema: dict[str, Any],
    root_schema: dict[str, Any],
    path: str,
) -> list[str]:
    errors: list[str] = []
    if "$ref" in schema:
        return _validate(value, _resolve_ref(root_schema, schema["$ref"]), root_schema, path)
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} is not one of {schema['enum']!r}")
    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_type_ok(value, item) for item in expected_types):
            errors.append(f"{path}: expected type {expected_type!r}")
            return errors
    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            errors.append(f"{path}: shorter than minLength")
        pattern = schema.get("pattern")
        if pattern:
            import re

            if re.fullmatch(pattern, value) is None:
                errors.append(f"{path}: does not match pattern {pattern!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            errors.append(f"{path}: fewer than minItems")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(
                    _validate(item, item_schema, root_schema, f"{path}[{index}]")
                )
    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                errors.extend(
                    _validate(item, properties[key], root_schema, f"{path}.{key}")
                )
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property {key!r}")
    for keyword in ("anyOf", "oneOf"):
        alternatives = schema.get(keyword)
        if not alternatives:
            continue
        matches = []
        alternative_errors = []
        for alternative in alternatives:
            current = _validate(value, alternative, root_schema, path)
            if current:
                alternative_errors.extend(current)
            else:
                matches.append(alternative)
        if keyword == "anyOf" and not matches:
            errors.extend(alternative_errors)
        if keyword == "oneOf" and len(matches) != 1:
            errors.append(f"{path}: must match exactly one oneOf schema")
    return errors


def validate_document(name: str, value: dict[str, Any]) -> dict[str, Any]:
    schema = load_schema(name)
    errors = _validate(value, schema, schema, "$")
    if errors:
        raise HeadlessError(
            f"{name} contract validation failed:\n" + "\n".join(errors)
        )
    return {
        "schema": name,
        "schema_version": value.get("schema_version", SCHEMA_VERSION),
        "validation_status": "PASS",
    }


def make_project(
    *,
    project_id: str,
    project_name: str,
    project_root: str,
    configuration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "project_name": project_name,
        "project_root": project_root,
        "configuration": configuration
        or {
            "execution_mode": "CONSOLE",
            "default_transport": "bridge",
            "default_port": 9001,
            "default_sampling": {
                "mode": "cycle",
                "interval": 1,
                "capture_contacts": False,
            },
        },
        "cases": [],
        "created_utc": utc_now(),
    }


def make_case(
    *,
    case_id: int,
    case_name: str,
    engine_dimension: int,
    config_path: str,
    parameters: dict[str, Any] | None = None,
    data_collection_config: dict[str, Any] | None = None,
    collection_plan: dict[str, Any] | None = None,
    model_path: str | None = None,
    script_path: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": int(case_id),
        "case_name": case_name,
        "engine_dimension": int(engine_dimension),
        "config_path": config_path,
        "model_path": model_path,
        "script_path": script_path,
        "parameters": parameters or {},
        "data_collection_config": data_collection_config
        or {
            "mode": "cycle",
            "interval": 1,
            "capture_contacts": False,
        },
        "collection_plan": collection_plan,
        "created_utc": utc_now(),
    }


def make_instance(
    *,
    instance_id: str,
    engine_type: str,
    executable_path: str,
    pid: int | None,
    bridge_port: int,
    bootstrap_path: str,
    state: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": instance_id,
        "engine_type": engine_type,
        "executable_path": executable_path,
        "pid": pid,
        "bridge_port": int(bridge_port),
        "state": state,
        "bootstrap_path": bootstrap_path,
        "identity_verified": False,
        "health_verified": False,
        "execution_verified": False,
        "mcp_verified": False,
        "identity_fingerprint": None,
        "mcp_connection_id": None,
        "readiness_nonce": None,
        "mcp_verified_utc": None,
        "mcp_evidence_expires_utc": None,
        "evidence_status": "NOT_VERIFIED",
        "started_utc": None,
        "stopped_utc": None,
    }


def make_run(
    *,
    run_id: str,
    case_id: int,
    instance_id: str | None,
    input_snapshot: str,
    script_version: str,
    output_path: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "case_id": int(case_id),
        "instance_id": instance_id,
        "input_snapshot": input_snapshot,
        "script_version": script_version,
        "start_time": utc_now(),
        "end_time": None,
        "task_status": "PREPARED",
        "mcp_task_id": None,
        "execution_nonce": None,
        "task_description": None,
        "entry_script": None,
        "mcp_connection_id": None,
        "instance_identity_fingerprint": None,
        "instance_snapshot": None,
        "execution_options": {},
        "collection_plan": None,
        "mcp_evidence": None,
        "prepared_utc": None,
        "finalization": None,
        "feedback_id": None,
        "output_path": output_path,
        "error": None,
    }


def make_feedback(
    *,
    run_id: str,
    source: str,
    findings: list[dict[str, Any]],
    missing_data: list[str],
    recommended_sampling: dict[str, Any],
    recommended_actions: list[str],
    referenced_artifacts: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "contract": "pfc.analysis-findings@1.0.0",
        "feedback_id": f"feedback_{utc_now().replace(':', '').replace('-', '')}",
        "run_id": run_id,
        "source": source,
        "referenced_artifacts": referenced_artifacts or [],
        "findings": findings,
        "missing_data": missing_data,
        "recommended_sampling": recommended_sampling,
        "recommended_parameters": {},
        "recommended_actions": recommended_actions,
        "status": "RECEIVED",
        "attempts": [],
        "active_attempt_run_id": None,
        "review": None,
        "produced_utc": utc_now(),
    }

