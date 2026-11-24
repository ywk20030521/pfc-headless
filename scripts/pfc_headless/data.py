"""Offline data-package validation and downstream contract checks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# numpy is imported lazily inside verify_delivery().  headless.py imports this
# module for EVERY CLI command, so a hard import here made commands such as
# `environment check` and `project init` fail on interpreters without numpy.
# The engine-local Python normally has numpy; system Python may not.

from .common import HeadlessError, atomic_write_json, read_json, sha256_file, utc_now
from .contracts import validate_document


CONTRACT_NAME = "pfc.standardized-experiment"
CONTRACT_VERSION = "1.0.0"


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HeadlessError(f"Package artifact escapes root: {relative}") from exc
    return path


def verify_delivery(root: str | Path) -> dict[str, Any]:
    try:
        import numpy as np
    except ImportError as exc:
        raise HeadlessError(
            "data verify requires numpy to inspect NPZ arrays. Use the PFC "
            "engine Python (e.g. <engine>/python310/python.exe), or install "
            "numpy in the active interpreter."
        ) from exc

    root = Path(root).resolve()
    errors: list[str] = []
    checks: dict[str, Any] = {}
    for name in (
        "metadata.json",
        "manifest.json",
        "delivery_manifest.json",
        "experiment.json",
        "validation_report.json",
        "conversion_report.json",
    ):
        if not (root / name).is_file():
            errors.append(f"Missing {name}")
    if not (root / "schema").is_dir():
        errors.append("Missing schema/ directory")
    if errors:
        return {
            "status": "FAIL",
            "root": str(root),
            "errors": errors,
            "checks": checks,
            "generated_utc": utc_now(),
        }
    metadata = read_json(root / "metadata.json")
    manifest = read_json(root / "manifest.json")
    delivery = read_json(root / "delivery_manifest.json")
    experiment: dict[str, Any] | None = None
    try:
        validate_document("metadata", metadata)
        validate_document("manifest", manifest)
    except HeadlessError as exc:
        errors.append(str(exc))

    contract = delivery.get("contract") or {}
    checks["contract_name"] = contract.get("name") == CONTRACT_NAME
    checks["contract_version"] = contract.get("version") == CONTRACT_VERSION
    checks["contract_immutable"] = contract.get("immutable") is True
    policy = delivery.get("consumer_policy") or {}
    checks["consumer_read_only"] = policy.get("read_only") is True
    checks["consumer_cannot_write"] = policy.get("may_write_inside_contract") is False

    artifact_paths = set()
    for entry in delivery.get("artifacts", []):
        relative = str(entry.get("path", ""))
        try:
            path = _inside(root, relative)
        except HeadlessError as exc:
            errors.append(str(exc))
            continue
        artifact_paths.add(path.relative_to(root).as_posix())
        if not path.is_file():
            errors.append(f"Missing delivery artifact: {relative}")
            continue
        if path.stat().st_size != int(entry.get("size_bytes", -1)):
            errors.append(f"Size mismatch: {relative}")
        if sha256_file(path) != entry.get("sha256"):
            errors.append(f"SHA-256 mismatch: {relative}")

    for entry in manifest.get("files", []):
        relative = str(entry.get("path", ""))
        path = _inside(root, relative)
        if not path.is_file():
            errors.append(f"Missing manifest file: {relative}")
        elif path.stat().st_size != int(entry.get("size_bytes", -1)):
            errors.append(f"Manifest size mismatch: {relative}")
        elif sha256_file(path) != entry.get("sha256"):
            errors.append(f"Manifest hash mismatch: {relative}")

    actual_data_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.name
        not in {"metadata.json", "manifest.json", "delivery_manifest.json"}
    }
    declared_data_files = {
        str(entry.get("path")) for entry in metadata.get("data_files", [])
    }
    checks["manifest_covers_data_files"] = actual_data_files <= artifact_paths
    checks["metadata_file_index_complete"] = declared_data_files == actual_data_files

    case_contract = {
        int(item["case_id"]): item for item in delivery.get("cases", [])
    }
    experiment_path = _inside(
        root, str((delivery.get("experiment") or {}).get("path", ""))
    )
    checks["experiment_hash_matches"] = (
        experiment_path.is_file()
        and sha256_file(experiment_path)
        == (delivery.get("experiment") or {}).get("sha256")
    )
    if experiment_path.is_file():
        experiment = read_json(experiment_path)
        for case in experiment.get("cases", []):
            case_id = int(case["case_id"])
            reference = case_contract.get(case_id)
            if reference is None:
                errors.append(f"Case {case_id} absent from delivery manifest")
                continue
            arrays_path = _inside(root, str(case["arrays_path"]))
            if not arrays_path.is_file():
                errors.append(f"Case {case_id} arrays are missing")
                continue
            if sha256_file(arrays_path) != reference.get("arrays_sha256"):
                errors.append(f"Case {case_id} arrays hash mismatch")
            try:
                with np.load(arrays_path, allow_pickle=False) as arrays:
                    frame_count = int(case["frame_count"])
                    if len(arrays["cycle"]) != frame_count:
                        errors.append(f"Case {case_id} Cycle length mismatch")
                    if len(arrays["frame_offsets"]) != frame_count + 1:
                        errors.append(f"Case {case_id} frame offset length mismatch")
                    if int(arrays["frame_offsets"][-1]) != len(arrays["ball_id"]):
                        errors.append(f"Case {case_id} final Ball offset mismatch")
                    if not np.all(np.isfinite(arrays["ball_xyz"])):
                        errors.append(f"Case {case_id} has non-finite Ball coordinates")
                    if "contact_offsets" in arrays.files:
                        if len(arrays["contact_offsets"]) != frame_count + 1:
                            errors.append(
                                f"Case {case_id} contact offset length mismatch"
                            )
                        if int(arrays["contact_offsets"][-1]) != len(
                            arrays["contact_id"]
                        ):
                            errors.append(
                                f"Case {case_id} final contact offset mismatch"
                            )
            except Exception as exc:
                errors.append(f"Case {case_id} NPZ invalid: {exc}")

    bool_checks = [value for value in checks.values() if isinstance(value, bool)]
    if not all(bool_checks):
        errors.append("One or more package contract checks failed")
    return {
        "status": "PASS" if not errors else "FAIL",
        "root": str(root),
        "errors": errors,
        "checks": checks,
        "metadata": metadata,
        "manifest": manifest,
        "experiment": experiment,
        "generated_utc": utc_now(),
    }


def write_verification_report(
    root: str | Path,
    report_path: str | Path,
) -> dict[str, Any]:
    root = Path(root).resolve()
    report = verify_delivery(root)
    output = Path(report_path).resolve()
    try:
        output.relative_to(root)
    except ValueError:
        pass
    else:
        raise HeadlessError(
            "Verification reports must be written outside the immutable package"
        )
    atomic_write_json(output, report)
    return report

