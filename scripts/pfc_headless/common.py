"""Shared filesystem, identifier and audit helpers."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0.0"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class HeadlessError(RuntimeError):
    """A headless operation failed an explicit contract or safety check."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str, length: int = 8) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:length]}"


def validate_id(value: str, label: str) -> str:
    if not SAFE_ID_RE.fullmatch(str(value)):
        raise HeadlessError(
            f"{label} must contain only letters, digits, '.', '_' or '-': {value!r}"
        )
    return str(value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    path = path.resolve()
    return {
        "path": (
            path.relative_to(root.resolve()).as_posix()
            if root is not None
            else str(path)
        ),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def append_audit(path: Path, event: str, **details: Any) -> dict[str, Any]:
    payload = {"time_utc": utc_now(), "event": event, **details}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return payload


def ensure_within(root: Path, path: Path, label: str) -> Path:
    root = root.resolve()
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HeadlessError(f"{label} escapes managed root: {path}") from exc
    return path


def copy_new_file(source: Path, destination: Path) -> dict[str, Any]:
    if not source.is_file():
        raise HeadlessError(f"Input file does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite input snapshot: {destination}")
    payload = source.read_bytes()
    atomic_write_bytes(destination, payload)
    return {
        "source": str(source.resolve()),
        "snapshot": str(destination.resolve()),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def substitute_parameters(value: Any, parameters: dict[str, Any], path: str = "$") -> Any:
    """Replace only explicit ``${name}`` placeholders in configuration."""
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in parameters:
                raise HeadlessError(f"Missing parameter {key!r} at {path}")
            replacement = parameters[key]
            if isinstance(replacement, (dict, list)) or replacement is None:
                raise HeadlessError(
                    f"Parameter {key!r} must be a scalar for string interpolation"
                )
            return str(replacement)

        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, value)
    if isinstance(value, list):
        return [
            substitute_parameters(item, parameters, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        return {
            key: substitute_parameters(item, parameters, f"{path}.{key}")
            for key, item in value.items()
        }
    return value

