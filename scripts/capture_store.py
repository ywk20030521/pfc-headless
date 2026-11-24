from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import struct
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


FORMAT_VERSION = "pfc-live-capture-gui/1"
FRAME_MAGIC = b"PFCLF01\0"
FRAME_HEADER = struct.Struct("<8sIIddddI")
FRAME_FLAG_FIRST = 1
FRAME_FLAG_FINAL = 2
FRAME_FLAG_IDENTITY_OK = 4
FRAME_FLAG_RADII = 8
DEFAULT_FLOAT32_ABS_TOL = 1.0e-6
DEFAULT_FLOAT32_REL_TOL = 1.0e-5

RAW_FILES = {
    "frames": "frame_spool.csv",
    "balls": "ball_spool.csv",
    "walls": "wall_spool.csv",
    "wall_vertices": "wall_vertex_spool.csv",
    "events": "bond_spool.csv",
    "solve_events": "solve_spool.csv",
}


class CaptureStoreError(RuntimeError):
    pass


class CaptureIntegrityError(CaptureStoreError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def pretty_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def crc32_bytes(value: bytes) -> str:
    return f"{zlib.crc32(value) & 0xFFFFFFFF:08x}"


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


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, pretty_json(value))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def initialize_run_dirs(run_dir: Path) -> None:
    for name in (
        "metadata",
        "static",
        "frames",
        "events",
        "histories",
        "recovery",
        "recovery/raw",
        "frames/blocks",
    ):
        (run_dir / name).mkdir(parents=True, exist_ok=True)


def initialize_raw_spools(run_dir: Path) -> None:
    raw = run_dir / "recovery" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    headers = {
        "frames": [
            "frame_id",
            "cycle",
            "mechanical_time_total",
            "ball_count",
            "wall_count",
            "wall_vertex_count",
            "capture_elapsed_ms",
            "write_elapsed_ms",
            "callback_calls",
            "identity_ok",
            "identity_reason",
            "frame_role",
        ],
        "balls": ["frame_id", "ball_id", "x", "y", "z", "radius"],
        "walls": [
            "frame_id",
            "wall_id",
            "x",
            "y",
            "z",
            "dx",
            "dy",
            "dz",
            "vx",
            "vy",
            "vz",
            "sx",
            "sy",
            "sz",
            "ex",
            "ey",
            "ez",
            "fx",
            "fy",
            "fz",
            "vertex_count",
        ],
        "wall_vertices": ["frame_id", "vertex_id", "x", "y", "z"],
        "events": [
            "event_id",
            "cycle",
            "mechanical_time_total",
            "contact_id",
            "ball_id_a",
            "ball_id_b",
            "mode",
            "failure_strength",
            "x",
            "y",
            "z",
            "nx",
            "ny",
            "nz",
            "diameter",
        ],
        "solve_events": [
            "event_id",
            "event",
            "solve_sequence",
            "cycle",
            "mechanical_time_total",
            "message",
        ],
    }
    for key, columns in headers.items():
        path = raw / RAW_FILES[key]
        if path.exists() and path.stat().st_size:
            continue
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(columns)


def _read_complete_csv(path: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not path.is_file():
        raise CaptureIntegrityError(f"Missing raw spool: {path}")
    payload = path.read_bytes()
    complete_end = payload.endswith(b"\n")
    complete_payload = payload
    rejected_tail = b""
    if not complete_end:
        split = payload.rfind(b"\n")
        if split < 0:
            complete_payload = b""
            rejected_tail = payload
        else:
            complete_payload = payload[: split + 1]
            rejected_tail = payload[split + 1 :]
    try:
        text = complete_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CaptureIntegrityError(f"Raw spool is not UTF-8: {path}") from exc
    reader = csv.DictReader(text.splitlines())
    rows = [dict(row) for row in reader]
    return rows, {
        "path": str(path),
        "file_bytes": len(payload),
        "complete_bytes": len(complete_payload),
        "rejected_tail_bytes": len(rejected_tail),
        "rejected_tail_sha256": (
            sha256_bytes(rejected_tail) if rejected_tail else None
        ),
        "rejected_tail_text": (
            rejected_tail.decode("utf-8", errors="replace")
            if rejected_tail
            else None
        ),
    }


def _finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CaptureIntegrityError(f"{label} is not numeric: {value!r}") from exc
    if not math.isfinite(number):
        raise CaptureIntegrityError(f"{label} is not finite: {number!r}")
    return number


def _required_file_entry(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "crc32": crc32_bytes(path.read_bytes()),
        "sha256": sha256_file(path),
    }


def choose_wall_roles(
    static_walls: list[dict[str, Any]],
) -> dict[str, int]:
    if not static_walls:
        return {}
    named = {
        str(wall.get("name", "")).lower(): int(wall["id"]) for wall in static_walls
    }
    if "top" in named and "bottom" in named:
        return {"top": named["top"], "bottom": named["bottom"]}
    ordered = sorted(
        static_walls, key=lambda wall: float(wall["position"][2])
    )
    result = {"bottom": int(ordered[0]["id"])}
    if len(ordered) > 1:
        result["top"] = int(ordered[-1]["id"])
    return result


def _load_static(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "static" / "model.json"
    if not path.is_file():
        raise CaptureIntegrityError(f"Static model file is missing: {path}")
    model = read_json(path)
    manifest_path = run_dir / "static" / "manifest.json"
    if manifest_path.is_file():
        manifest = read_json(manifest_path)
        model["bundle_sha256"] = manifest.get("bundle_sha256")
    else:
        model["bundle_sha256"] = None
    return model


def _parse_raw(run_dir: Path) -> dict[str, Any]:
    raw = run_dir / "recovery" / "raw"
    parsed: dict[str, list[dict[str, str]]] = {}
    tails: dict[str, dict[str, Any]] = {}
    for key, name in RAW_FILES.items():
        rows, tail = _read_complete_csv(raw / name)
        parsed[key] = rows
        tails[key] = tail
    frames_by_id: dict[int, dict[str, Any]] = {}
    for row in parsed["frames"]:
        frame_id = int(row["frame_id"])
        if frame_id in frames_by_id:
            raise CaptureIntegrityError(f"Duplicate frame metadata: {frame_id}")
        cycle = int(row["cycle"])
        mechanical_time = _finite(
            row["mechanical_time_total"], f"frame {frame_id} time"
        )
        ball_count = int(row["ball_count"])
        wall_count = int(row["wall_count"])
        vertex_count = int(row["wall_vertex_count"])
        identity_ok = row["identity_ok"].strip().lower() in {"1", "true", "yes"}
        if not identity_ok:
            raise CaptureIntegrityError(
                f"Frame {frame_id} failed same-cycle identity: "
                f"{row.get('identity_reason', '')}"
            )
        frames_by_id[frame_id] = {
            "frame_id": frame_id,
            "cycle": cycle,
            "mechanical_time_total": mechanical_time,
            "ball_count": ball_count,
            "wall_count": wall_count,
            "wall_vertex_count": vertex_count,
            "capture_elapsed_ms": _finite(
                row["capture_elapsed_ms"], f"frame {frame_id} capture time"
            ),
            "write_elapsed_ms": _finite(
                row["write_elapsed_ms"], f"frame {frame_id} write time"
            ),
            "callback_calls": int(row["callback_calls"]),
            "identity_ok": identity_ok,
            "frame_role": row.get("frame_role", "INTERVAL"),
        }
    frame_ids = sorted(frames_by_id)
    if not frame_ids:
        raise CaptureIntegrityError("No complete frame metadata rows")
    if frame_ids != list(range(1, len(frame_ids) + 1)):
        raise CaptureIntegrityError("Frame IDs are not contiguous from 1")
    cycles = [frames_by_id[frame_id]["cycle"] for frame_id in frame_ids]
    times = [
        frames_by_id[frame_id]["mechanical_time_total"] for frame_id in frame_ids
    ]
    if any(right <= left for left, right in zip(cycles, cycles[1:])):
        raise CaptureIntegrityError("Frame Cycles are not strictly increasing")
    if any(right <= left for left, right in zip(times, times[1:])):
        raise CaptureIntegrityError(
            "Frame Mechanical Times are not strictly increasing"
        )

    max_frame_id = frame_ids[-1]
    incomplete_frame_rows: dict[str, int] = {}
    balls: dict[int, list[dict[str, Any]]] = {value: [] for value in frame_ids}
    for row in parsed["balls"]:
        frame_id = int(row["frame_id"])
        if frame_id > max_frame_id:
            incomplete_frame_rows["balls"] = (
                incomplete_frame_rows.get("balls", 0) + 1
            )
            continue
        if frame_id not in balls:
            raise CaptureIntegrityError(f"Ball row references bad frame: {frame_id}")
        ball_id = int(row["ball_id"])
        balls[frame_id].append(
            {
                "id": ball_id,
                "x": _finite(row["x"], f"Ball {ball_id} x"),
                "y": _finite(row["y"], f"Ball {ball_id} y"),
                "z": _finite(row["z"], f"Ball {ball_id} z"),
                "radius": _finite(
                    row["radius"], f"Ball {ball_id} radius"
                ),
            }
        )
    walls: dict[int, list[dict[str, Any]]] = {value: [] for value in frame_ids}
    for row in parsed["walls"]:
        frame_id = int(row["frame_id"])
        if frame_id > max_frame_id:
            incomplete_frame_rows["walls"] = (
                incomplete_frame_rows.get("walls", 0) + 1
            )
            continue
        if frame_id not in walls:
            raise CaptureIntegrityError(f"Wall row references bad frame: {frame_id}")
        wall_id = int(row["wall_id"])
        walls[frame_id].append(
            {
                "id": wall_id,
                "position": [
                    _finite(row["x"], "wall x"),
                    _finite(row["y"], "wall y"),
                    _finite(row["z"], "wall z"),
                ],
                "displacement": [
                    _finite(row["dx"], "wall dx"),
                    _finite(row["dy"], "wall dy"),
                    _finite(row["dz"], "wall dz"),
                ],
                "velocity": [
                    _finite(row["vx"], "wall vx"),
                    _finite(row["vy"], "wall vy"),
                    _finite(row["vz"], "wall vz"),
                ],
                "spin": [
                    _finite(row["sx"], "wall sx"),
                    _finite(row["sy"], "wall sy"),
                    _finite(row["sz"], "wall sz"),
                ],
                "euler": [
                    _finite(row["ex"], "wall ex"),
                    _finite(row["ey"], "wall ey"),
                    _finite(row["ez"], "wall ez"),
                ],
                "force_contact": [
                    _finite(row["fx"], "wall fx"),
                    _finite(row["fy"], "wall fy"),
                    _finite(row["fz"], "wall fz"),
                ],
                "vertex_count": int(row["vertex_count"]),
            }
        )
    vertices: dict[int, list[dict[str, Any]]] = {
        value: [] for value in frame_ids
    }
    for row in parsed["wall_vertices"]:
        frame_id = int(row["frame_id"])
        if frame_id > max_frame_id:
            incomplete_frame_rows["wall_vertices"] = (
                incomplete_frame_rows.get("wall_vertices", 0) + 1
            )
            continue
        if frame_id not in vertices:
            raise CaptureIntegrityError(
                f"Wall vertex row references bad frame: {frame_id}"
            )
        vertices[frame_id].append(
            {
                "vertex_id": int(row["vertex_id"]),
                "position": [
                    _finite(row["x"], "vertex x"),
                    _finite(row["y"], "vertex y"),
                    _finite(row["z"], "vertex z"),
                ],
            }
        )
    previous_ids: set[int] | None = None
    previous_radii: dict[int, float] = {}
    changes: list[dict[str, Any]] = []
    radius_changes: list[dict[str, Any]] = []
    for frame_id in frame_ids:
        meta = frames_by_id[frame_id]
        ball_rows = sorted(balls[frame_id], key=lambda row: row["id"])
        ids = [row["id"] for row in ball_rows]
        if len(ids) != len(set(ids)):
            raise CaptureIntegrityError(
                f"Frame {frame_id} contains duplicate Ball IDs"
            )
        if len(ids) != meta["ball_count"]:
            raise CaptureIntegrityError(
                f"Frame {frame_id} Ball rows {len(ids)} != "
                f"metadata {meta['ball_count']}"
            )
        current_ids = set(ids)
        current_radii = {
            row["id"]: float(row["radius"]) for row in ball_rows
        }
        if previous_ids is not None:
            added = sorted(current_ids - previous_ids)
            removed = sorted(previous_ids - current_ids)
            if added or removed:
                changes.append(
                    {
                        "frame_id": frame_id,
                        "cycle": meta["cycle"],
                        "added_ids": added,
                        "removed_ids": removed,
                        "added_radius": {
                            str(ball_id): current_radii[ball_id]
                            for ball_id in added
                        },
                    }
                )
            changed = sorted(
                ball_id
                for ball_id in current_ids & previous_ids
                if current_radii[ball_id] != previous_radii[ball_id]
            )
            if changed:
                radius_changes.append(
                    {
                        "frame_id": frame_id,
                        "cycle": meta["cycle"],
                        "changes": {
                            str(ball_id): {
                                "before": previous_radii[ball_id],
                                "after": current_radii[ball_id],
                            }
                            for ball_id in changed
                        },
                    }
                )
        previous_ids = current_ids
        previous_radii = current_radii
        wall_rows = sorted(walls[frame_id], key=lambda row: row["id"])
        if len(wall_rows) != meta["wall_count"]:
            raise CaptureIntegrityError(
                f"Frame {frame_id} Wall rows {len(wall_rows)} != "
                f"metadata {meta['wall_count']}"
            )
        vertex_rows = vertices[frame_id]
        if len(vertex_rows) != meta["wall_vertex_count"]:
            raise CaptureIntegrityError(
                f"Frame {frame_id} vertex rows {len(vertex_rows)} != "
                f"metadata {meta['wall_vertex_count']}"
            )
    event_cycles = sorted(int(row["cycle"]) for row in parsed["events"])
    event_cursor = 0
    for frame_id in frame_ids:
        cycle = frames_by_id[frame_id]["cycle"]
        while (
            event_cursor < len(event_cycles)
            and event_cycles[event_cursor] <= cycle
        ):
            event_cursor += 1
        frames_by_id[frame_id]["fracture_count"] = event_cursor
        frames_by_id[frame_id]["capture_status"] = "VALID"
    return {
        "frame_ids": frame_ids,
        "frames": [frames_by_id[value] for value in frame_ids],
        "balls": balls,
        "walls": walls,
        "vertices": vertices,
        "ball_id_changes": changes,
        "ball_radius_changes": radius_changes,
        "raw_tails": tails,
        "incomplete_frame_rows": incomplete_frame_rows,
        "solve_events": parsed["solve_events"],
        "fracture_events": parsed["events"],
    }


def _pack_frame(
    *,
    meta: dict[str, Any],
    balls: list[dict[str, Any]],
    radii: list[float],
    first: bool,
    final: bool,
) -> tuple[bytes, dict[str, Any]]:
    flags = FRAME_FLAG_IDENTITY_OK
    if first:
        flags |= FRAME_FLAG_FIRST
    if final:
        flags |= FRAME_FLAG_FINAL
    if radii:
        flags |= FRAME_FLAG_RADII
    ids = [int(row["id"]) for row in balls]
    header = FRAME_HEADER.pack(
        FRAME_MAGIC,
        int(meta["frame_id"]),
        len(balls),
        int(meta["cycle"]),
        float(meta["mechanical_time_total"]),
        float(meta["capture_elapsed_ms"]),
        float(meta["write_elapsed_ms"]),
        flags,
    )
    id_payload = b"".join(struct.pack("<I", value) for value in ids)
    xyz_payload = b"".join(
        struct.pack(
            "<fff",
            float(row["x"]),
            float(row["y"]),
            float(row["z"]),
        )
        for row in balls
    )
    radius_payload = b""
    if radii:
        radius_payload = b"".join(
            struct.pack("<f", float(value)) for value in radii
        )
    payload = header + id_payload + xyz_payload + radius_payload
    return payload, {
        "frame_id": int(meta["frame_id"]),
        "sequence": int(meta["frame_id"]),
        "cycle": int(meta["cycle"]),
        "mechanical_time_total": float(meta["mechanical_time_total"]),
        "ball_count": len(balls),
        "wall_count": int(meta["wall_count"]),
        "capture_elapsed_ms": float(meta["capture_elapsed_ms"]),
        "write_elapsed_ms": float(meta["write_elapsed_ms"]),
        "flags": flags,
        "first_frame": first,
        "final_frame": final,
        "radius_count": len(radii),
        "frame_role": meta["frame_role"],
        "fracture_count": int(meta["fracture_count"]),
        "capture_status": str(meta["capture_status"]),
        "frame_bytes": len(payload),
        "crc32": crc32_bytes(payload),
        "sha256": sha256_bytes(payload),
    }


def _float32_errors(
    balls: list[dict[str, Any]],
    abs_tol: float,
    rel_tol: float,
) -> dict[str, Any]:
    max_abs = 0.0
    max_rel = 0.0
    for row in balls:
        for key in ("x", "y", "z", "radius"):
            original = float(row[key])
            decoded = struct.unpack("<f", struct.pack("<f", original))[0]
            absolute = abs(decoded - original)
            relative = absolute / max(abs(original), 1.0)
            max_abs = max(max_abs, absolute)
            max_rel = max(max_rel, relative)
            if absolute > abs_tol and relative > rel_tol:
                raise CaptureIntegrityError(
                    f"Float32 error exceeds visualization tolerance for "
                    f"Ball {row['id']} {key}: {absolute} / {relative}"
                )
    return {
        "encoding": "IEEE-754 binary32",
        "absolute_tolerance": abs_tol,
        "relative_tolerance": rel_tol,
        "max_abs_error": max_abs,
        "max_rel_error_against_max_abs_1": max_rel,
        "status": "PASS",
    }


def _commit_block(
    *,
    run_dir: Path,
    block_id: int,
    block_frames: list[tuple[dict[str, Any], bytes, dict[str, Any]]],
    static: dict[str, Any],
    float32_report: dict[str, Any],
) -> dict[str, Any]:
    blocks_root = run_dir / "frames" / "blocks"
    final_dir = blocks_root / f"block-{block_id:06d}"
    if final_dir.exists():
        raise CaptureIntegrityError(f"Block already exists: {final_dir}")
    staging = blocks_root / (
        f".stage-block-{block_id:06d}-{uuid.uuid4().hex}"
    )
    staging.mkdir()
    try:
        binary_path = staging / "ball_frames.bin"
        wall_path = staging / "wall_frames.jsonl"
        offset = 0
        frame_index = []
        wall_lines = []
        for meta, payload, frame_meta in block_frames:
            binary_offset = offset
            offset += len(payload)
            frame_index.append(
                {
                    **frame_meta,
                    "offset_bytes": binary_offset,
                }
            )
            wall_lines.append(
                canonical_json(
                    {
                        "frame_id": meta["frame_id"],
                        "cycle": meta["cycle"],
                        "mechanical_time_total": meta["mechanical_time_total"],
                        "walls": [
                            row
                            for row in block_frames[0][0].get("_unused", [])
                        ],
                    }
                )
            )
        binary_payload = b"".join(value[1] for value in block_frames)
        atomic_write_bytes(binary_path, binary_payload)
        wall_payload = b"\n".join(
            canonical_json(
                {
                    "frame_id": meta["frame_id"],
                    "cycle": meta["cycle"],
                    "mechanical_time_total": meta["mechanical_time_total"],
                    "walls": meta["walls"],
                    "vertices": meta["vertices"],
                }
            )
            for meta, _payload, _frame_meta in block_frames
        ) + b"\n"
        atomic_write_bytes(wall_path, wall_payload)
        commit = {
            "format": FORMAT_VERSION,
            "status": "COMMITTED",
            "block_id": block_id,
            "sample_count": len(block_frames),
            "first_frame_id": block_frames[0][2]["frame_id"],
            "last_frame_id": block_frames[-1][2]["frame_id"],
            "cycle_start": block_frames[0][2]["cycle"],
            "cycle_end": block_frames[-1][2]["cycle"],
            "mechanical_time_start": block_frames[0][2][
                "mechanical_time_total"
            ],
            "mechanical_time_end": block_frames[-1][2][
                "mechanical_time_total"
            ],
            "ball_frame_encoding": {
                "header_format": FRAME_HEADER.format,
                "header_size_bytes": FRAME_HEADER.size,
                "ids": "uint32 little-endian",
                "xyz": "float32 little-endian",
                "frame_radius_updates": (
                    "float32 little-endian; stored for the first frame and "
                    "only when a Ball ID or Radius changes"
                ),
            },
            "float32_precision": float32_report,
            "static_bundle_sha256": static["bundle_sha256"],
            "frames": frame_index,
            "files": [
                _required_file_entry(staging, binary_path),
                _required_file_entry(staging, wall_path),
            ],
            "committed_utc": utc_now(),
        }
        atomic_write_json(staging / "commit.json", commit)
        os.replace(staging, final_dir)
        return validate_block(final_dir)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def decode_frame(
    payload: bytes,
) -> tuple[dict[str, Any], list[int], list[tuple[float, float, float]], list[float] | None]:
    if len(payload) < FRAME_HEADER.size:
        raise CaptureIntegrityError("Truncated frame header")
    (
        magic,
        frame_id,
        count,
        cycle,
        mechanical_time,
        capture_ms,
        write_ms,
        flags,
    ) = FRAME_HEADER.unpack_from(payload, 0)
    if magic != FRAME_MAGIC:
        raise CaptureIntegrityError(f"Frame magic mismatch: {magic!r}")
    if count > 10_000_000:
        raise CaptureIntegrityError(f"Unreasonable Ball count: {count}")
    offset = FRAME_HEADER.size
    ids_end = offset + count * 4
    xyz_end = ids_end + count * 12
    has_radii = bool(
        flags & FRAME_FLAG_RADII or flags & FRAME_FLAG_FIRST
    )
    radii_end = xyz_end + (count * 4 if has_radii else 0)
    if radii_end != len(payload):
        raise CaptureIntegrityError(
            f"Frame length mismatch: expected {radii_end}, got {len(payload)}"
        )
    ids = list(struct.unpack_from(f"<{count}I", payload, offset)) if count else []
    xyz = (
        list(
            struct.iter_unpack(
                "<fff", payload[ids_end:xyz_end]
            )
        )
        if count
        else []
    )
    radii = (
        list(struct.unpack_from(f"<{count}f", payload, xyz_end))
        if count and has_radii
        else None
    )
    if len(ids) != len(set(ids)):
        raise CaptureIntegrityError("Decoded Ball IDs are not unique")
    return (
        {
            "frame_id": int(frame_id),
            "cycle": int(cycle),
            "mechanical_time_total": float(mechanical_time),
            "capture_elapsed_ms": float(capture_ms),
            "write_elapsed_ms": float(write_ms),
            "flags": int(flags),
            "ball_count": int(count),
        },
        ids,
        xyz,
        radii,
    )


def validate_block(path: Path) -> dict[str, Any]:
    commit_path = path / "commit.json"
    if not commit_path.is_file():
        raise CaptureIntegrityError(f"Block commit missing: {path}")
    commit = read_json(commit_path)
    if commit.get("status") != "COMMITTED":
        raise CaptureIntegrityError(f"Block not committed: {path}")
    for entry in commit["files"]:
        file_path = path / entry["path"]
        if not file_path.is_file():
            raise CaptureIntegrityError(f"Block file missing: {file_path}")
        payload = file_path.read_bytes()
        if len(payload) != entry["size_bytes"]:
            raise CaptureIntegrityError(f"Block size mismatch: {file_path}")
        if crc32_bytes(payload) != entry["crc32"]:
            raise CaptureIntegrityError(f"Block CRC32 mismatch: {file_path}")
        if sha256_bytes(payload) != entry["sha256"]:
            raise CaptureIntegrityError(f"Block SHA-256 mismatch: {file_path}")
    binary = (path / "ball_frames.bin").read_bytes()
    decoded = []
    for frame in commit["frames"]:
        offset = int(frame["offset_bytes"])
        end = offset + int(frame["frame_bytes"])
        chunk = binary[offset:end]
        if crc32_bytes(chunk) != frame["crc32"]:
            raise CaptureIntegrityError(
                f"Frame {frame['frame_id']} CRC32 mismatch"
            )
        if sha256_bytes(chunk) != frame["sha256"]:
            raise CaptureIntegrityError(
                f"Frame {frame['frame_id']} SHA-256 mismatch"
            )
        header, ids, xyz, radii = decode_frame(chunk)
        if header["frame_id"] != frame["frame_id"]:
            raise CaptureIntegrityError("Frame ID mismatch")
        if header["cycle"] != frame["cycle"]:
            raise CaptureIntegrityError("Frame Cycle mismatch")
        if header["mechanical_time_total"] != frame["mechanical_time_total"]:
            raise CaptureIntegrityError("Frame Mechanical Time mismatch")
        if header["ball_count"] != frame["ball_count"]:
            raise CaptureIntegrityError("Frame Ball count mismatch")
        decoded.append(
            {
                "header": header,
                "ids": ids,
                "xyz": xyz,
                "radii": radii,
            }
        )
    return {"commit": commit, "frames": decoded}


def recover_blocks(run_dir: Path) -> dict[str, Any]:
    root = run_dir / "frames" / "blocks"
    root.mkdir(parents=True, exist_ok=True)
    valid = []
    invalid = []
    candidate_dirs = sorted(
        path for path in root.glob("block-*") if path.is_dir()
    )
    for path in candidate_dirs:
        try:
            report = validate_block(path)
            valid.append(
                {
                    "path": str(path),
                    "commit": report["commit"],
                }
            )
        except BaseException as exc:
            invalid.append(
                {
                    "path": str(path),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
    expected_blocks = list(range(1, len(valid) + 1))
    valid_ids = [int(item["commit"]["block_id"]) for item in valid]
    if valid_ids != expected_blocks:
        raise CaptureIntegrityError(
            f"Valid frame blocks are not contiguous: {valid_ids}"
        )
    if invalid and candidate_dirs[-1].name != Path(invalid[-1]["path"]).name:
        raise CaptureIntegrityError(
            "A non-tail frame block is corrupt; refusing partial recovery"
        )
    last_cycle = (
        int(valid[-1]["commit"]["cycle_end"]) if valid else None
    )
    return {
        "status": "PASS" if not invalid else "INVALID_TAIL_REJECTED",
        "valid_blocks": valid,
        "invalid_tail": invalid,
        "valid_block_count": len(valid),
        "invalid_tail_count": len(invalid),
        "frame_count": sum(
            int(item["commit"]["sample_count"]) for item in valid
        ),
        "last_valid_cycle": last_cycle,
    }


def compact_run(
    run_dir: Path,
    *,
    chunk_frames: int = 10,
    float32_abs_tol: float = DEFAULT_FLOAT32_ABS_TOL,
    float32_rel_tol: float = DEFAULT_FLOAT32_REL_TOL,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    initialize_run_dirs(run_dir)
    static = _load_static(run_dir)
    parsed = _parse_raw(run_dir)
    static_balls = {
        int(row["id"]): row for row in static["balls"]
    }
    first_frame = parsed["frames"][0]
    first_ball_rows = sorted(
        parsed["balls"][first_frame["frame_id"]],
        key=lambda row: row["id"],
    )
    for row in first_ball_rows:
        if row["id"] not in static_balls:
            raise CaptureIntegrityError(
                f"First-frame Ball {row['id']} absent from static data"
            )
        static_radius = float(static_balls[row["id"]]["radius"])
        radius_delta = abs(float(row["radius"]) - static_radius)
        if radius_delta > max(1.0e-12, float32_abs_tol):
            raise CaptureIntegrityError(
                f"First-frame Ball {row['id']} Radius differs from static data"
            )
    float32_report = _float32_errors(
        first_ball_rows, float32_abs_tol, float32_rel_tol
    )
    recovered = recover_blocks(run_dir)
    existing_frame_count = recovered["frame_count"]
    next_block_id = recovered["valid_block_count"] + 1
    start_index = existing_frame_count
    if start_index > len(parsed["frames"]):
        raise CaptureIntegrityError(
            "Committed blocks contain more frames than the raw spool"
        )
    radius_state = {
        int(ball_id): float(row["radius"])
        for ball_id, row in static_balls.items()
    }
    for meta in parsed["frames"][:start_index]:
        frame_id = meta["frame_id"]
        radius_state = {
            row["id"]: float(row["radius"])
            for row in parsed["balls"][frame_id]
        }
    for block_start in range(start_index, len(parsed["frames"]), chunk_frames):
        source_frames = parsed["frames"][
            block_start : block_start + chunk_frames
        ]
        block_frames = []
        for meta in source_frames:
            frame_id = meta["frame_id"]
            ball_rows = sorted(
                parsed["balls"][frame_id], key=lambda row: row["id"]
            )
            first = frame_id == 1
            final = meta.get("frame_role") == "FINAL"
            current_radii = {
                row["id"]: float(row["radius"]) for row in ball_rows
            }
            changed_radii = (
                first
                or any(
                    ball_id not in radius_state
                    or current_radii[ball_id] != radius_state[ball_id]
                    for ball_id in current_radii
                )
            )
            radii = (
                [current_radii[row["id"]] for row in ball_rows]
                if changed_radii
                else []
            )
            payload, frame_meta = _pack_frame(
                meta=meta,
                balls=ball_rows,
                radii=radii,
                first=first,
                final=final,
            )
            radius_state = current_radii
            meta_with_walls = dict(meta)
            meta_with_walls["walls"] = parsed["walls"][frame_id]
            meta_with_walls["vertices"] = parsed["vertices"][frame_id]
            block_frames.append((meta_with_walls, payload, frame_meta))
        _commit_block(
            run_dir=run_dir,
            block_id=next_block_id,
            block_frames=block_frames,
            static=static,
            float32_report=float32_report,
        )
        next_block_id += 1
    recovered = recover_blocks(run_dir)
    if recovered["frame_count"] != len(parsed["frames"]):
        raise CaptureIntegrityError(
            "Committed frame count differs from complete raw frames"
        )
    tail_rows = [
        {
            "channel": key,
            "path": report["path"],
            "rejected_tail_bytes": report["rejected_tail_bytes"],
            "rejected_tail_sha256": report["rejected_tail_sha256"],
            "rejected_tail_text": report["rejected_tail_text"],
        }
        for key, report in parsed["raw_tails"].items()
        if report["rejected_tail_bytes"]
    ]
    atomic_write_json(
        run_dir / "recovery" / "recovery_scan.json",
        {
            "generated_utc": utc_now(),
            "complete_frames": len(parsed["frames"]),
            "last_complete_cycle": parsed["frames"][-1]["cycle"],
            "rejected_tails": tail_rows,
            "incomplete_frame_rows": parsed["incomplete_frame_rows"],
            "frame_blocks": recovered,
        },
    )
    return {
        "status": "COMPLETE",
        "frames": len(parsed["frames"]),
        "blocks": recovered,
        "float32_precision": float32_report,
        "ball_id_changes": parsed["ball_id_changes"],
        "ball_radius_changes": parsed["ball_radius_changes"],
        "raw_tails": tail_rows,
        "incomplete_frame_rows": parsed["incomplete_frame_rows"],
        "parsed": parsed,
    }


def iter_committed_frames(run_dir: Path) -> Iterable[dict[str, Any]]:
    recovered = recover_blocks(run_dir)
    for block in recovered["valid_blocks"]:
        path = Path(block["path"])
        report = validate_block(path)
        wall_rows = [
            json.loads(line)
            for line in (path / "wall_frames.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line
        ]
        wall_by_id = {row["frame_id"]: row for row in wall_rows}
        for frame in report["frames"]:
            header = frame["header"]
            yield {
                "header": header,
                "ids": frame["ids"],
                "xyz": frame["xyz"],
                "radii": frame["radii"],
                "walls": wall_by_id[header["frame_id"]]["walls"],
                "vertices": wall_by_id[header["frame_id"]]["vertices"],
                "block_path": str(path),
            }


def write_final_reports(
    run_dir: Path,
    *,
    status: str,
    reason: str,
    run_id: str,
    pid: int,
    sample_mode: str,
    sample_value: float,
    additional_events: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    recovered = recover_blocks(run_dir)
    frames = list(iter_committed_frames(run_dir))
    cycle_start = frames[0]["header"]["cycle"] if frames else None
    cycle_end = frames[-1]["header"]["cycle"] if frames else None
    time_start = frames[0]["header"]["mechanical_time_total"] if frames else None
    time_end = frames[-1]["header"]["mechanical_time_total"] if frames else None
    data_bytes = sum(
        path.stat().st_size
        for path in (run_dir / "frames").rglob("*")
        if path.is_file()
    )
    events = {}
    events_path = run_dir / "events" / "matched_fractures.jsonl"
    if events_path.is_file():
        events = {
            "path": "events/matched_fractures.jsonl",
            "rows": sum(1 for line in events_path.read_text(encoding="utf-8").splitlines() if line),
            "sha256": sha256_file(events_path),
        }
    manifest = {
        "schema_version": 1,
        "format_version": FORMAT_VERSION,
        "data_boundary": "REAL_PFC",
        "mock_data_used": False,
        "run_id": run_id,
        "pid": int(pid),
        "status": status,
        "reason": reason,
        "field_configuration": {
            "ball_static": ["id", "x", "y", "z", "radius"],
            "ball_dynamic": ["id", "x", "y", "z"],
            "radius_rule": (
                "static and first binary frame for the initial set; later "
                "binary frames store Radius only for added Balls or changes"
            ),
            "wall_dynamic": [
                "id",
                "position",
                "displacement",
                "velocity",
                "spin",
                "euler",
                "vertices",
            ],
            "fracture": [
                "event_id",
                "cycle",
                "mechanical_time_total",
                "contact_id",
                "ball_id_a",
                "ball_id_b",
                "mode",
                "failure_strength",
                "position",
                "normal",
                "diameter",
            ],
        },
        "sampling": {
            "mode": sample_mode,
            "value": sample_value,
            "policy": "capture at solve_start, interval, and solve_complete",
        },
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
        "mechanical_time_start": time_start,
        "mechanical_time_end": time_end,
        "frame_count": len(frames),
        "block_count": recovered["valid_block_count"],
        "data_bytes": data_bytes,
        "events": events,
        "viewer_generated": False,
        "generated_utc": utc_now(),
    }
    atomic_write_json(run_dir / "manifest.json", manifest)
    files = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in {"manifest.json", "integrity_report.json"}:
            continue
        files.append(_required_file_entry(run_dir, path))
    integrity = {
        "status": "PASS" if frames and not recovered["invalid_tail"] else "INCOMPLETE",
        "run_id": run_id,
        "pid": int(pid),
        "frame_count": len(frames),
        "block_recovery": recovered,
        "strictly_increasing_cycles": all(
            right["header"]["cycle"] > left["header"]["cycle"]
            for left, right in zip(frames, frames[1:])
        ),
        "strictly_increasing_mechanical_time": all(
            right["header"]["mechanical_time_total"]
            > left["header"]["mechanical_time_total"]
            for left, right in zip(frames, frames[1:])
        ),
        "all_committed_blocks_valid": not recovered["invalid_tail"],
        "all_committed_frames_sha256_verified": True,
        "files": files,
        "additional_events": additional_events or {},
        "generated_utc": utc_now(),
    }
    atomic_write_json(run_dir / "integrity_report.json", integrity)
    return manifest

