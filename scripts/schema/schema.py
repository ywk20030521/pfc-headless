"""Small, dependency-free builders and validator for the experiment schema.

The JSON Schema files are the interchange contract.  This module produces
objects that satisfy that contract and performs the essential checks without
requiring a third-party ``jsonschema`` installation in the PFC Python runtime.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "1.0.0"
CHANNEL_SOURCES = {
    "REAL_PFC",
    "DERIVED",
    "CONFIG",
    "NOT_CAPTURED",
    "INVALID",
}
RESULT_STATUSES = {
    "GENERATED",
    "NOT_GENERATED",
    "NOT_CAPTURED",
    "NOT_SUPPORTED",
    "INVALID",
    "NOT_VERIFIED",
}
ENTITY_TYPES = {
    "ball",
    "clump",
    "wall",
    "contact",
    "bond",
    "fracture",
    "history",
    "other",
}
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _finite_or_none(value: Any, label: str) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _source(value: str) -> str:
    if value not in CHANNEL_SOURCES:
        raise ValueError(f"Unknown data source: {value}")
    return value


def make_provenance(
    *,
    source: str,
    input_files: Iterable[dict[str, Any] | str] = (),
    parent_results: Iterable[str] = (),
    formula: str | None = None,
    method: str | None = None,
    applicability: str | None = None,
    notes: Iterable[str] = (),
) -> dict[str, Any]:
    """Return an auditable provenance record.

    File entries may be paths or objects containing ``path``, ``sha256`` and
    optional ``size_bytes``.  A missing hash is recorded as ``NOT_VERIFIED``;
    it is never replaced by invented evidence.
    """
    files = []
    for entry in input_files:
        item = {"path": str(entry)} if isinstance(entry, str) else dict(entry)
        if "path" not in item:
            raise ValueError("Provenance file entry requires a path")
        item.setdefault("sha256", None)
        item.setdefault("size_bytes", None)
        files.append(item)
    return {
        "source": _source(source),
        "input_files": files,
        "parent_results": sorted(set(str(value) for value in parent_results)),
        "formula": formula,
        "method": method,
        "applicability": applicability,
        "notes": list(notes),
        "generated_utc": utc_now(),
    }


def make_channel(
    channel_id: str,
    *,
    entity_type: str,
    variable: str,
    unit: str | None,
    source: str,
    status: str = "GENERATED",
    dimensions: Iterable[str] = (),
    description: str = "",
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not _ID_RE.match(channel_id):
        raise ValueError(f"Invalid channel id: {channel_id}")
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"Unknown entity type: {entity_type}")
    if status not in RESULT_STATUSES:
        raise ValueError(f"Unknown result status: {status}")
    return {
        "id": channel_id,
        "entity_type": entity_type,
        "variable": variable,
        "unit": unit,
        "source": _source(source),
        "status": status,
        "dimensions": list(dimensions),
        "description": description,
        "provenance": provenance or make_provenance(source=source),
    }


def make_entity_group(
    entity_type: str,
    *,
    array_prefix: str,
    count: int,
    dynamic_ids: bool,
    properties: Iterable[str] = (),
    source: str = "REAL_PFC",
) -> dict[str, Any]:
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"Unknown entity type: {entity_type}")
    if count < 0:
        raise ValueError("Entity count cannot be negative")
    return {
        "entity_type": entity_type,
        "array_prefix": array_prefix,
        "count": int(count),
        "dynamic_ids": bool(dynamic_ids),
        "properties": list(properties),
        "source": _source(source),
    }


def make_frame(
    frame_id: int,
    *,
    cycle: int,
    mechanical_time_total: float | None,
    entity_offsets: dict[str, list[int]] | None = None,
    events: Iterable[int] = (),
    capture_status: str = "VALID",
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if int(frame_id) < 1:
        raise ValueError("frame_id starts at 1")
    if capture_status not in {"VALID", "INVALID", "NOT_CAPTURED"}:
        raise ValueError(f"Invalid capture status: {capture_status}")
    return {
        "frame_id": int(frame_id),
        "cycle": int(cycle),
        "mechanical_time_total": _finite_or_none(
            mechanical_time_total, "mechanical_time_total"
        ),
        "entity_offsets": entity_offsets or {},
        "event_ids": [int(value) for value in events],
        "capture_status": capture_status,
        "provenance": provenance
        or make_provenance(
            source="REAL_PFC" if capture_status == "VALID" else "NOT_CAPTURED"
        ),
    }


def make_event(
    event_id: int,
    *,
    event_type: str,
    cycle: int | None,
    mechanical_time_total: float | None,
    position: Iterable[float] | None,
    properties: dict[str, Any] | None = None,
    source: str = "REAL_PFC",
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pos = None if position is None else [float(value) for value in position]
    if pos is not None:
        if len(pos) not in {2, 3} or not all(math.isfinite(v) for v in pos):
            raise ValueError("Event position must contain finite 2D or 3D values")
    return {
        "event_id": int(event_id),
        "event_type": event_type,
        "cycle": None if cycle is None else int(cycle),
        "mechanical_time_total": _finite_or_none(
            mechanical_time_total, "event mechanical_time_total"
        ),
        "position": pos,
        "properties": properties or {},
        "source": _source(source),
        "provenance": provenance or make_provenance(source=source),
    }


def make_case(
    case_id: int,
    *,
    label: str,
    run_id: str,
    dimension: int,
    source_format: str,
    frame_count: int,
    arrays_path: str,
    channels: Iterable[dict[str, Any]] = (),
    entity_groups: Iterable[dict[str, Any]] = (),
    metadata: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if dimension not in {2, 3}:
        raise ValueError("Only PFC2D (2) and PFC3D (3) are valid dimensions")
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": int(case_id),
        "label": str(label),
        "run_id": str(run_id),
        "dimension": dimension,
        "source_format": str(source_format),
        "frame_count": int(frame_count),
        "arrays_path": str(arrays_path),
        "channels": list(channels),
        "entity_groups": list(entity_groups),
        "metadata": metadata or {},
        "provenance": provenance or make_provenance(source="REAL_PFC"),
    }


def make_experiment(
    *,
    experiment_id: str,
    title: str,
    pfc_version: str | None,
    execution_mode: str,
    dimensions: Iterable[int],
    cases: Iterable[dict[str, Any]],
    data_boundary: str,
    metadata: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    case_list = list(cases)
    if not case_list:
        raise ValueError("An experiment requires at least one case")
    dims = sorted(set(int(value) for value in dimensions))
    if any(value not in {2, 3} for value in dims):
        raise ValueError("Experiment dimensions must be 2 and/or 3")
    if execution_mode not in {"CONSOLE", "OFFLINE", "UNKNOWN"}:
        raise ValueError("Official execution_mode must be CONSOLE, OFFLINE or UNKNOWN")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": str(experiment_id),
        "title": str(title),
        "pfc_version": pfc_version,
        "execution_mode": str(execution_mode),
        "dimensions": dims,
        "data_boundary": str(data_boundary),
        "cases": case_list,
        "metadata": metadata or {},
        "provenance": provenance or make_provenance(source="CONFIG"),
        "generated_utc": utc_now(),
    }
    validate_experiment(payload)
    return payload


def validate_experiment(
    experiment: dict[str, Any],
    *,
    arrays_loader: Any | None = None,
) -> None:
    """Validate structural invariants and, if supplied, NPZ lengths.

    ``arrays_loader`` is a callable accepting the case record and returning a
    ``numpy.lib.npyio.NpzFile`` or mapping with ``__getitem__``.  It is kept
    optional so metadata can be validated before arrays are written.
    """
    required = {
        "schema_version",
        "experiment_id",
        "title",
        "execution_mode",
        "dimensions",
        "data_boundary",
        "cases",
        "provenance",
    }
    missing = sorted(required - set(experiment))
    if missing:
        raise ValueError(f"Experiment missing keys: {missing}")
    if not experiment["cases"]:
        raise ValueError("Experiment cases cannot be empty")
    seen = set()
    for case in experiment["cases"]:
        case_id = int(case.get("case_id", -1))
        if case_id < 0 or case_id in seen:
            raise ValueError(f"Duplicate or invalid case_id: {case_id}")
        seen.add(case_id)
        if int(case.get("dimension", 0)) not in {2, 3}:
            raise ValueError(f"Case {case_id} has invalid dimension")
        if int(case.get("frame_count", -1)) < 1:
            raise ValueError(f"Case {case_id} has no frames")
        for channel in case.get("channels", []):
            if channel.get("source") not in CHANNEL_SOURCES:
                raise ValueError(f"Case {case_id} channel has invalid source")
            if channel.get("status") not in RESULT_STATUSES:
                raise ValueError(f"Case {case_id} channel has invalid status")
        if arrays_loader is not None:
            with arrays_loader(case) as arrays:
                frames = int(case["frame_count"])
                expected = {"cycle", "mechanical_time_total", "frame_offsets"}
                if expected - set(arrays.files):
                    raise ValueError(f"Case {case_id} NPZ lacks core frame arrays")
                for key in ("cycle", "mechanical_time_total", "frame_offsets"):
                    expected_length = frames + 1 if key == "frame_offsets" else frames
                    if len(arrays[key]) != expected_length:
                        raise ValueError(
                            f"Case {case_id} {key} length does not match frame_count"
                        )
                offsets = arrays["frame_offsets"]
                if offsets[0] != 0 or not all(
                    int(right) >= int(left)
                    for left, right in zip(offsets, offsets[1:])
                ):
                    raise ValueError(f"Case {case_id} has invalid frame offsets")
                if int(offsets[-1]) != len(arrays["ball_id"]):
                    raise ValueError(f"Case {case_id} final Ball offset is inconsistent")
                if "ball_xyz" in arrays.files and not np_isfinite(arrays["ball_xyz"]):
                    raise ValueError(f"Case {case_id} contains non-finite Ball coordinates")


def np_isfinite(values: Any) -> bool:
    """Check finiteness without importing NumPy in the metadata-only path."""
    try:
        return all(math.isfinite(float(value)) for value in list(values.flat))
    except AttributeError:
        return all(math.isfinite(float(value)) for value in values)
