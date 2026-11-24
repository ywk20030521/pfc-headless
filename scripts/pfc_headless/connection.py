"""Layered Console readiness verified against the current instance identity."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from console_runtime import ConsoleRuntime

from .common import HeadlessError, read_json, utc_now
from .instance import identity_fingerprint
from .mcp_evidence import EVIDENCE_SCHEMA_VERSION, evidence_sha256


OFFICIAL_MCP_TOOLS = {"itasca_execute_code", "itasca_execute_task"}


def _parse_utc(value: Any, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HeadlessError(f"MCP evidence {name} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise HeadlessError(f"MCP evidence {name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def normalize_mcp_output(output: str) -> str:
    """Validate an MCP tool envelope and return the engine-side text.

    Some hosts hand the MCP client a JSON string rather than the raw console
    text.  Recording that envelope verbatim leaves the readiness nonce escaped
    and hides `ok:false`.  Accept both shapes, but validate the envelope.
    """
    text = str(output or "").strip()
    if not text:
        raise HeadlessError("MCP output is empty")
    try:
        envelope = json.loads(text)
    except (TypeError, ValueError):
        return text
    if not isinstance(envelope, dict):
        return text
    if "ok" in envelope and envelope["ok"] is not True:
        raise HeadlessError("MCP tool response reports ok=false")
    data = envelope.get("data")
    if isinstance(data, dict) and isinstance(data.get("output"), str):
        return data["output"].strip()
    return text


def make_mcp_evidence(
    runtime: ConsoleRuntime,
    instance: dict[str, Any],
    *,
    tool: str,
    output: str,
    task_id: str | None = None,
    ttl_seconds: int = 600,
) -> dict[str, Any]:
    if tool not in OFFICIAL_MCP_TOOLS:
        raise HeadlessError("MCP evidence must name an official Itasca execution tool")
    output = normalize_mcp_output(output)
    if not output.strip():
        raise HeadlessError("MCP output is empty")
    nonce = str(instance.get("readiness_nonce") or "")
    if not nonce:
        raise HeadlessError("Instance has no readiness nonce")
    if nonce not in output:
        raise HeadlessError("MCP output does not echo the current readiness nonce")
    identity = runtime.process_identity(runtime.state())
    fingerprint = identity_fingerprint(
        identity,
        instance_id=str(instance["instance_id"]),
        engine_type=str(instance["engine_type"]),
        bridge_port=int(instance["bridge_port"]),
    )
    observed = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "status": "PASS",
        "tool": tool,
        "bridge_url": f"http://127.0.0.1:{runtime.port}",
        "bridge_port": int(runtime.port),
        "instance_id": str(instance["instance_id"]),
        "engine_type": str(instance["engine_type"]),
        "dimension": 2 if instance["engine_type"] == "PFC2D_CONSOLE" else 3,
        "engine_version": instance.get("engine_version"),
        "pid": int(identity["pid"]),
        "executable_path": str(Path(identity["executable"]).resolve()),
        "command_line": list(identity.get("command_line", [])),
        "identity_fingerprint": fingerprint,
        "mcp_connection_id": str(instance.get("mcp_connection_id") or ""),
        "readiness_nonce": nonce,
        "output": output,
        "observed_utc": observed.isoformat(timespec="seconds"),
        "expires_utc": (observed + timedelta(seconds=ttl_seconds)).isoformat(
            timespec="seconds"
        ),
    }
    if task_id:
        payload["task_id"] = task_id
    payload["evidence_sha256"] = evidence_sha256(payload)
    return payload


def verify_connection(
    runtime: ConsoleRuntime,
    instance: dict[str, Any],
    *,
    mcp_evidence_path: Path | None = None,
    ttl_seconds: int = 600,
) -> dict[str, Any]:
    """Require process, diagnostic Bridge/PFC and current-instance MCP evidence."""
    identity = runtime.process_identity(runtime.state())
    current_fingerprint = identity_fingerprint(
        identity,
        instance_id=str(instance["instance_id"]),
        engine_type=str(instance["engine_type"]),
        bridge_port=int(instance["bridge_port"]),
    )
    registered_fingerprint = str(instance.get("identity_fingerprint") or "")
    if not registered_fingerprint or registered_fingerprint != current_fingerprint:
        raise HeadlessError(
            "INSTANCE_IDENTITY_MISMATCH: READY evidence cannot be reused after "
            "PID, executable, command line or port changes"
        )
    preflight = runtime.preflight()
    layers: dict[str, Any] = {
        "L1_process_identity": {"status": "PASS", **identity},
        "L2_bridge_health": {
            "status": "PASS",
            "health": preflight["health"],
            "scope": "diagnostic only",
        },
        "L3_pfc_execution": {
            "status": "PASS",
            "channel": "Bridge diagnostic probe",
            "probe": preflight["probe"],
        },
        "L3_mcp_round_trip": {
            "status": "NOT_VERIFIED",
            "reason": "No current-instance itasca-mcp evidence supplied.",
        },
    }
    if mcp_evidence_path is None:
        return {
            "ready": False,
            "state": "ATTACHED",
            "verification_scope": "PROCESS+BRIDGE+PFC; current MCP evidence required",
            "layers": layers,
            "verified_utc": utc_now(),
        }

    evidence = read_json(mcp_evidence_path)
    if evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise HeadlessError("MCP evidence schema_version is not current")
    if evidence.get("status") != "PASS":
        raise HeadlessError("MCP evidence must contain status=PASS")
    tool = str(evidence.get("tool") or "")
    if tool not in OFFICIAL_MCP_TOOLS:
        raise HeadlessError("MCP evidence must name an official Itasca MCP tool")
    comparisons = {
        "instance_id": str(instance["instance_id"]),
        "engine_type": str(instance["engine_type"]),
        "pid": int(identity["pid"]),
        "executable_path": str(Path(identity["executable"]).resolve()),
        "bridge_port": int(instance["bridge_port"]),
        "identity_fingerprint": current_fingerprint,
        "mcp_connection_id": str(instance.get("mcp_connection_id") or ""),
        "readiness_nonce": str(instance.get("readiness_nonce") or ""),
        "dimension": 2 if instance["engine_type"] == "PFC2D_CONSOLE" else 3,
    }
    for name, expected in comparisons.items():
        actual = evidence.get(name)
        if str(actual) != str(expected):
            raise HeadlessError(
                f"MCP evidence {name} mismatch: {actual!r} != {expected!r}"
            )
    nonce = comparisons["readiness_nonce"]
    if not nonce or nonce not in str(evidence.get("output") or ""):
        raise HeadlessError("MCP evidence output does not echo the readiness nonce")
    observed = _parse_utc(evidence.get("observed_utc"), "observed_utc")
    expires = _parse_utc(evidence.get("expires_utc"), "expires_utc")
    now = datetime.now(timezone.utc)
    if expires <= now or observed > now:
        raise HeadlessError("MCP evidence is expired or has a future timestamp")
    if expires - observed > timedelta(seconds=ttl_seconds):
        raise HeadlessError("MCP evidence claims an invalid lifetime")
    layers["L3_mcp_round_trip"] = {
        "status": "PASS",
        "channel": "itasca-mcp",
        **evidence,
    }
    return {
        "ready": True,
        "state": "READY",
        "verification_scope": "PROCESS+BRIDGE+PFC+MCP",
        "layers": layers,
        "identity_fingerprint": current_fingerprint,
        "verified_utc": utc_now(),
        "evidence_expires_utc": str(evidence["expires_utc"]),
    }
