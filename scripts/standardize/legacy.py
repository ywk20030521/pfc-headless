"""Read the existing pfc-live-capture working or packaged layout.

This adapter is intentionally read-only.  It recognizes the capture engine's
current CSV and ZIP products and returns a neutral in-memory representation for
the NumPy converter.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import zipfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np


class LegacyDataError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv_rows_from_text(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _iter_csv_rows(path: Path) -> Iterable[dict[str, str]]:
    """Streaming CSV reader. Yields one row at a time so the raw
    list[dict[str, str]] never materializes in memory. The caller must
    consume the generator exactly once (all current call sites do)."""
    with path.open(encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def _iter_csv_rows_from_text(text: str) -> Iterable[dict[str, str]]:
    yield from csv.DictReader(io.StringIO(text))


def _zip_rows(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    try:
        text = archive.read(name).decode("utf-8")
    except KeyError as exc:
        raise LegacyDataError(f"frames.zip is missing {name}") from exc
    return _csv_rows_from_text(text)


def _iter_zip_rows(archive: zipfile.ZipFile, name: str) -> Iterable[dict[str, str]]:
    try:
        text = archive.read(name).decode("utf-8")
    except KeyError as exc:
        raise LegacyDataError(f"frames.zip is missing {name}") from exc
    yield from _iter_csv_rows_from_text(text)


def _finite(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise LegacyDataError(f"{label} is not finite")
    return number


def _optional_int(value: Any, default: int = -1) -> int:
    """Parse an optional numeric column; missing/blank values stay sentinel."""
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        return default


def _static_balls(static: dict[str, Any]) -> list[dict[str, Any]]:
    raw = static.get("balls", static.get("ball", {}))
    rows = raw.get("balls", raw) if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise LegacyDataError("static.json has no Ball rows")
    result = []
    for row in rows:
        result.append(
            {
                "id": int(row["id"]),
                "x": _finite(row["x"], "Ball x"),
                "y": _finite(row["y"], "Ball y"),
                "z": _finite(row.get("z", 0.0), "Ball z"),
                "radius": _finite(row.get("radius", 0.0), "Ball radius"),
            }
        )
    return result


def _static_walls(static: dict[str, Any]) -> list[dict[str, Any]]:
    raw = static.get("walls", static.get("wall", {}))
    rows = raw.get("walls", raw) if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise LegacyDataError("static.json has no Wall rows")
    result = []
    for row in rows:
        vertices = []
        for vertex in row.get("vertices", []):
            position = vertex.get("position")
            if position is None:
                position = [vertex.get("x"), vertex.get("y"), vertex.get("z", 0.0)]
            pos = [
                _finite(position[0], "Wall vertex x"),
                _finite(position[1], "Wall vertex y"),
                _finite(position[2] if len(position) > 2 else 0.0, "Wall vertex z"),
            ]
            vertices.append({"id": int(vertex.get("id", len(vertices) + 1)), "position": pos})
        position = row.get("position")
        if position is None:
            position = [row.get("x", 0.0), row.get("y", 0.0), row.get("z", 0.0)]

        # Facet topology (PFC3D). Callers can rebuild real wall faces only if
        # each facet keeps the IDs of its corner vertices. Old deliveries have
        # no facets key -> empty list, fully backward compatible.
        facets = []
        for facet in row.get("facets", []):
            fpos = facet.get("position", [0.0, 0.0, 0.0])
            fnormal = facet.get("normal", [0.0, 0.0, 1.0])
            facets.append(
                {
                    "id": int(facet.get("id", len(facets) + 1)),
                    "active": int(facet.get("active", 0)),
                    "position": [
                        _finite(fpos[0], "Facet x"),
                        _finite(fpos[1], "Facet y"),
                        _finite(fpos[2] if len(fpos) > 2 else 0.0, "Facet z"),
                    ],
                    "normal": [
                        _finite(fnormal[0], "Facet nx"),
                        _finite(fnormal[1], "Facet ny"),
                        _finite(fnormal[2] if len(fnormal) > 2 else 0.0, "Facet nz"),
                    ],
                    "vertex_ids": [int(v) for v in facet.get("vertex_ids", [])],
                }
            )
        result.append(
            {
                "id": int(row["id"]),
                "name": str(row.get("name", "")),
                "position": [
                    _finite(position[0], "Wall x"),
                    _finite(position[1], "Wall y"),
                    _finite(position[2] if len(position) > 2 else 0.0, "Wall z"),
                ],
                "vertices": vertices,
                "facets": facets,
            }
        )
    return result


def infer_dimension(static: dict[str, Any], balls: list[dict[str, Any]], walls: list[dict[str, Any]]) -> int:
    explicit = static.get("dimension", static.get("pfc_dimension"))
    if explicit is not None:
        value = int(explicit)
        if value not in {2, 3}:
            raise LegacyDataError(f"Unsupported PFC dimension: {value}")
        return value
    points = [[b["x"], b["y"], b["z"]] for b in balls]
    points.extend(v["position"] for w in walls for v in w["vertices"])
    if not points:
        raise LegacyDataError("Cannot infer dimensionality from empty static data")
    spans = [max(p[k] for p in points) - min(p[k] for p in points) for k in range(3)]
    return 2 if spans[2] <= max(1.0e-12, 1.0e-9 * max(spans[0], spans[1], 1.0)) else 3


def discover_legacy_cases(root: Path) -> list[Path]:
    root = root.resolve()
    if root.name.startswith("case_") and root.name.split("_", 1)[1].isdigit():
        return [root]
    found = [
        path for path in root.glob("case_*")
        if path.is_dir() and path.name.split("_", 1)[1].isdigit()
    ]
    found.sort(key=lambda p: int(p.name.split("_", 1)[1]))
    if not found:
        # A working <root>/data directory is useful for one-case conversion.
        if (root / "data").is_dir() or (root / "static.json").is_file():
            return [root]
        raise LegacyDataError(f"No case_<N> directories under {root}")
    return found


def _work_paths(case_dir: Path) -> tuple[Path, Path] | None:
    if (case_dir / "data" / "static.json").is_file():
        return case_dir, case_dir / "data"
    if (case_dir / "static.json").is_file() and (case_dir / "frames.zip").is_file():
        return case_dir, case_dir
    return None


def _load_work_files(
    case_dir: Path, data_dir: Path, *, fast_reader: bool = False
) -> dict[str, Any]:
    static_path = data_dir / "static.json"
    static = read_json(static_path)
    frame_index_path = data_dir / "raw" / "frame_index.csv"
    ball_path = data_dir / "raw" / "ball_frames.csv"
    wall_path = data_dir / "raw" / "wall_vertices.csv"
    row_reader = _iter_csv_rows if fast_reader else _csv_rows
    zip_reader = _iter_zip_rows if fast_reader else _zip_rows
    if not all(path.is_file() for path in (frame_index_path, ball_path, wall_path)):
        # Packaged case with an unpacked static.json and frames.zip.
        zipped = case_dir / "frames.zip"
        if zipped.is_file():
            with zipfile.ZipFile(zipped) as archive:
                frame_index = zip_reader(archive, "frame_index.csv")
                ball_rows = zip_reader(archive, "ball_frames.csv")
                wall_rows = zip_reader(archive, "wall_vertices.csv")
            fracture_rows = []
            if (case_dir / "fracture_events.csv").is_file():
                fracture_rows = row_reader(case_dir / "fracture_events.csv")
            return {
                "static": static,
                "static_path": static_path,
                "frame_index": frame_index,
                "ball_rows": ball_rows,
                "wall_rows": wall_rows,
                "fracture_rows": fracture_rows,
                "history_rows": row_reader(case_dir / "history.csv")
                if (case_dir / "history.csv").is_file()
                else [],
                "format": "pfc-live-capture-packaged",
                "files": [static_path, zipped]
                + ([case_dir / "history.csv"] if (case_dir / "history.csv").is_file() else [])
                + ([case_dir / "fracture_events.csv"] if (case_dir / "fracture_events.csv").is_file() else []),
            }
        raise LegacyDataError(f"Incomplete capture files under {data_dir}")
    fracture_path = data_dir / "raw" / "fracture_events.csv"
    fracture_rows = row_reader(fracture_path) if fracture_path.is_file() else []
    history_path = data_dir / "history.csv"
    if not history_path.is_file():
        history_path = case_dir / "history.csv"
    metric_path = data_dir / "histories" / "frame_metrics.csv"
    contact_path = data_dir / "raw" / "contact_frames.csv"
    files = [static_path, frame_index_path, ball_path, wall_path]
    if fracture_path.is_file():
        files.append(fracture_path)
    if contact_path.is_file():
        files.append(contact_path)
    if history_path.is_file():
        files.append(history_path)
    if metric_path.is_file():
        files.append(metric_path)
    native_histories_path = data_dir / "native_histories.csv"
    if native_histories_path.is_file():
        files.append(native_histories_path)
    files.extend(sorted((data_dir / "histories").glob("native_*.csv")))
    return {
        "static": static,
        "static_path": static_path,
        "frame_index": row_reader(frame_index_path),
        "ball_rows": row_reader(ball_path),
        "wall_rows": row_reader(wall_path),
        "fracture_rows": fracture_rows,
        "contact_rows": row_reader(contact_path) if contact_path.is_file() else [],
        "history_rows": row_reader(history_path) if history_path.is_file() else [],
        "metric_rows": row_reader(metric_path) if metric_path.is_file() else [],
        "format": "pfc-live-capture-working",
        "files": files,
    }


def _load_zip_only(case_dir: Path, *, fast_reader: bool = False) -> dict[str, Any]:
    static_path = case_dir / "static.json"
    if not static_path.is_file():
        raise LegacyDataError(f"Packaged case lacks static.json: {case_dir}")
    static = read_json(static_path)
    archive_path = case_dir / "frames.zip"
    row_reader = _iter_csv_rows if fast_reader else _csv_rows
    # ZIP rows are decoded into text eagerly; keep the packaged path materialized
    # because the archive is closed before the caller consumes the rows.
    with zipfile.ZipFile(archive_path) as archive:
        frame_index = _zip_rows(archive, "frame_index.csv")
        ball_rows = _zip_rows(archive, "ball_frames.csv")
        wall_rows = _zip_rows(archive, "wall_vertices.csv")
    fracture_path = case_dir / "fracture_events.csv"
    history_path = case_dir / "history.csv"
    return {
        "static": static,
        "static_path": static_path,
        "frame_index": frame_index,
        "ball_rows": ball_rows,
        "wall_rows": wall_rows,
        "fracture_rows": row_reader(fracture_path) if fracture_path.is_file() else [],
        "history_rows": row_reader(history_path) if history_path.is_file() else [],
        "format": "pfc-live-capture-packaged",
        "files": [static_path, archive_path]
        + ([history_path] if history_path.is_file() else [])
        + ([fracture_path] if fracture_path.is_file() else []),
    }


def _columnar_ball_rows(
    ball_path: Path,
    frame_index: list[dict[str, Any]],
    static_radius: dict[int, float],
) -> dict[str, Any] | None:
    """Read ball CSV into preallocated columnar arrays, bypassing the
    dict-of-dicts intermediate that dominates memory on large runs.

    Rows are grouped by frame and sorted by Ball ID to match the legacy path
    exactly. Returns None for the ZIP layout (caller falls back to the dict
    path). All validation performed by the legacy ball loop is reproduced.
    """
    frame_pos = {int(row["frame_id"]): index for index, row in enumerate(frame_index)}
    expected = {int(row["frame_id"]): int(row["ball_count"]) for row in frame_index}

    # Pass 1: count rows per frame.
    per_frame: dict[int, int] = {fid: 0 for fid in frame_pos}
    for row in _iter_csv_rows(ball_path):
        fid = int(row["frame_id"])
        if fid not in frame_pos:
            raise LegacyDataError(f"Ball row references unknown frame {fid}")
        per_frame[fid] += 1
    for fid, count in per_frame.items():
        if count != expected[fid]:
            raise LegacyDataError(
                f"Frame {fid} has {count} Ball rows, expected {expected[fid]}"
            )

    total = sum(per_frame.values())
    offsets = [0]
    for row in frame_index:
        offsets.append(offsets[-1] + per_frame[int(row["frame_id"])])
    ids = np.empty(total, dtype=np.uint64)
    xyz = np.empty((total, 3), dtype=np.float64)
    radius = np.empty(total, dtype=np.float64)
    present = np.empty(total, dtype=np.int64)
    velocity = np.empty((total, 3), dtype=np.float64)
    spin = np.empty((total, 3), dtype=np.float64)
    velocity_complete = True
    spin_complete = True

    # Pass 2: write rows into their frame's slice; track duplicates.
    cursors = {fid: offsets[index] for index, fid in enumerate(frame_pos)}
    seen: dict[int, set[int]] = {fid: set() for fid in frame_pos}
    for row in _iter_csv_rows(ball_path):
        fid = int(row["frame_id"])
        ball_id = int(row["ball_id"])
        dupes = seen[fid]
        if ball_id in dupes:
            raise LegacyDataError(f"Frame {fid} has duplicate Ball ID {ball_id}")
        dupes.add(ball_id)
        pos = cursors[fid]
        cursors[fid] += 1
        ids[pos] = ball_id
        xyz[pos] = (
            _finite(row["x"], "Ball x"),
            _finite(row["y"], "Ball y"),
            _finite(row.get("z", 0.0), "Ball z"),
        )
        raw_radius = row.get("radius")
        radius[pos] = float(raw_radius) if raw_radius not in {None, ""} else static_radius.get(ball_id, float("nan"))
        present[pos] = frame_pos[fid]
        has_velocity = all(row.get(key) not in {None, ""} for key in ("vx", "vy", "vz"))
        if has_velocity:
            velocity[pos] = (_finite(row["vx"], "vx"), _finite(row["vy"], "vy"), _finite(row["vz"], "vz"))
        else:
            velocity_complete = False
        has_spin = all(row.get(key) not in {None, ""} for key in ("spin_x", "spin_y", "spin_z"))
        if has_spin:
            spin[pos] = (_finite(row["spin_x"], "sx"), _finite(row["spin_y"], "sy"), _finite(row["spin_z"], "sz"))
        else:
            spin_complete = False

    # Sort each frame's slice by Ball ID to match legacy ordering.
    for index, row in enumerate(frame_index):
        fid = int(row["frame_id"])
        start, end = offsets[index], offsets[index + 1]
        if end - start < 2:
            continue
        order = np.argsort(ids[start:end], kind="stable")
        ids[start:end] = ids[start:end][order]
        xyz[start:end] = xyz[start:end][order]
        radius[start:end] = radius[start:end][order]
        present[start:end] = present[start:end][order]
        velocity[start:end] = velocity[start:end][order]
        spin[start:end] = spin[start:end][order]

    return {
        "frame_offsets": np.asarray(offsets, dtype=np.int64),
        "ball_id": ids,
        "ball_xyz": xyz,
        "ball_radius": radius,
        "ball_frame_index": present,
        "ball_velocity": velocity if velocity_complete and total else None,
        "ball_spin": spin if spin_complete and total else None,
    }


def load_legacy_case(case_dir: Path, *, fast_reader: bool = False, columnar: bool = False) -> dict[str, Any]:
    """Load one working or packaged case without modifying its source files.

    fast_reader=True streams large CSV tables instead of materializing
    list[dict[str, str]] in memory. The default path is unchanged.

    columnar=True reads ball rows straight into preallocated arrays, skipping
    the ball_frames dict-of-dicts intermediate. Requires the working CSV
    layout; ZIP cases fall back automatically. Off by default.
    """
    case_dir = case_dir.resolve()
    if (case_dir / "frames.zip").is_file() and not (case_dir / "data").is_dir():
        source = _load_zip_only(case_dir, fast_reader=fast_reader)
        columnar_active = False
    else:
        paths = _work_paths(case_dir)
        if paths is None:
            raise LegacyDataError(f"Not a recognized PFC case directory: {case_dir}")
        source = _load_work_files(*paths, fast_reader=fast_reader)
        columnar_active = columnar and (paths[1] / "raw" / "ball_frames.csv").is_file()

    static = source["static"]
    balls = _static_balls(static)
    walls = _static_walls(static)
    dimension = infer_dimension(static, balls, walls)
    result_path = case_dir / "data" / "metadata" / "result.json"
    validation_path = case_dir / "data" / "metadata" / "validation.json"
    result = read_json(result_path) if result_path.is_file() else {}
    validation = read_json(validation_path) if validation_path.is_file() else {}
    if validation and validation.get("status") not in {None, "PASS"}:
        raise LegacyDataError(f"Capture validation did not pass: {case_dir}")
    if result and result.get("status") not in {None, "COMPLETE"}:
        raise LegacyDataError(f"Capture result is not complete: {case_dir}")

    frame_index = []
    previous_cycle = -math.inf
    previous_time = -math.inf
    for row in source["frame_index"]:
        frame_id = int(row["frame_id"])
        cycle = int(row["cycle"])
        time_value = _finite(row["mechanical_time_total"], "mechanical time")
        if cycle <= previous_cycle or time_value <= previous_time:
            raise LegacyDataError("Capture frames are not strictly ordered")
        previous_cycle, previous_time = cycle, time_value
        top_raw = row.get("top_force_magnitude")
        bottom_raw = row.get("bottom_force_magnitude")
        frame_index.append(
            {
                "frame_id": frame_id,
                "cycle": cycle,
                "mechanical_time_total": time_value,
                "ball_count": int(row["ball_count"]),
                "top_force": _finite(top_raw, "top force")
                if top_raw not in {None, ""}
                else None,
                "bottom_force": _finite(bottom_raw, "bottom force")
                if bottom_raw not in {None, ""}
                else None,
                "raw": dict(row),
            }
        )

    ball_arrays: dict[str, Any] | None = None
    if columnar_active:
        ball_arrays = _columnar_ball_rows(
            paths[1] / "raw" / "ball_frames.csv",
            frame_index,
            {int(r["id"]): float(r["radius"]) for r in balls},
        )
        ball_frames = {}
    else:
        ball_frames: dict[int, list[dict[str, Any]]] = {
            int(row["frame_id"]): [] for row in frame_index
        }
        for row in source["ball_rows"]:
            frame_id = int(row["frame_id"])
            if frame_id not in ball_frames:
                raise LegacyDataError(f"Ball row references unknown frame {frame_id}")
            ball_frames[frame_id].append(
                {
                    "id": int(row["ball_id"]),
                    "x": _finite(row["x"], "Ball x"),
                    "y": _finite(row["y"], "Ball y"),
                    "z": _finite(row.get("z", 0.0), "Ball z"),
                    "radius": _finite(row["radius"], "Ball radius")
                    if row.get("radius") not in {None, ""}
                    else None,
                    "velocity": [
                        _finite(row[key], f"Ball velocity {key}")
                        for key in ("vx", "vy", "vz")
                    ]
                    if all(row.get(key) not in {None, ""} for key in ("vx", "vy", "vz"))
                    else None,
                    "spin": [
                        _finite(row[key], f"Ball spin {key}")
                        for key in ("spin_x", "spin_y", "spin_z")
                    ]
                    if all(
                        row.get(key) not in {None, ""}
                        for key in ("spin_x", "spin_y", "spin_z")
                    )
                    else None,
                }
            )
        for frame in frame_index:
            rows = ball_frames[frame["frame_id"]]
            rows.sort(key=lambda value: value["id"])
            if len(rows) != frame["ball_count"]:
                raise LegacyDataError(
                    f"Frame {frame['frame_id']} has {len(rows)} Ball rows, expected {frame['ball_count']}"
                )
            if len({row["id"] for row in rows}) != len(rows):
                raise LegacyDataError(f"Frame {frame['frame_id']} has duplicate Ball IDs")

    wall_frames: dict[int, dict[int, list[dict[str, Any]]]] = {
        int(row["frame_id"]): {} for row in frame_index
    }
    for row in source["wall_rows"]:
        frame_id = int(row["frame_id"])
        if frame_id not in wall_frames:
            raise LegacyDataError(f"Wall row references unknown frame {frame_id}")
        wall_id = int(row.get("wall_id", -1))
        wall_frames[frame_id].setdefault(wall_id, []).append(
            {
                "vertex_id": int(row["vertex_id"]),
                "position": [
                    _finite(row["x"], "vertex x"),
                    _finite(row["y"], "vertex y"),
                    _finite(row.get("z", 0.0), "vertex z"),
                ],
            }
        )

    fracture_events = []
    for row in source["fracture_rows"]:
        fracture_events.append(
            {
                "event_id": int(row["event_id"]),
                "cycle": int(row["cycle"]),
                "mechanical_time_total": _finite(row["mechanical_time_total"], "event time"),
                "contact_id": _optional_int(row.get("contact_id")),
                "ball_id_a": _optional_int(row.get("ball_id_a")),
                "ball_id_b": _optional_int(row.get("ball_id_b")),
                "mode": int(row["mode"]),
                "failure_strength": _finite(row.get("failure_strength", 0.0), "failure strength"),
                "position": [
                    _finite(row["x"], "event x"),
                    _finite(row["y"], "event y"),
                    _finite(row.get("z", 0.0), "event z"),
                ],
                "normal": [
                    _finite(row.get("nx", 0.0), "event nx"),
                    _finite(row.get("ny", 0.0), "event ny"),
                    _finite(row.get("nz", 0.0), "event nz"),
                ],
                "diameter": _finite(row.get("diameter", 0.0), "event diameter"),
            }
        )
    fracture_events.sort(key=lambda value: (value["cycle"], value["event_id"]))

    contact_frames: dict[int, list[dict[str, Any]]] = {
        int(row["frame_id"]): [] for row in frame_index
    }
    for row in source.get("contact_rows", []):
        frame_id = int(row["frame_id"])
        if frame_id not in contact_frames:
            raise LegacyDataError(f"Contact row references unknown frame {frame_id}")
        contact_frames[frame_id].append(
            {
                "id": int(row["contact_id"]),
                "end1_type": str(row["end1_type"]),
                "end1_id": int(row["end1_id"]),
                "end2_type": str(row["end2_type"]),
                "end2_id": int(row["end2_id"]),
                "position": [
                    _finite(row["x"], "contact x"),
                    _finite(row["y"], "contact y"),
                    _finite(row["z"], "contact z"),
                ],
                "force_xyz": [
                    _finite(row["fx"], "contact fx"),
                    _finite(row["fy"], "contact fy"),
                    _finite(row["fz"], "contact fz"),
                ],
                "model": str(row["model"]),
            }
        )

    file_records = []
    for path in source["files"]:
        if path.is_file():
            file_records.append(
                {
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
    return {
        "case_id": int(result.get("case_id", case_dir.name.split("_", 1)[1]))
        if case_dir.name.startswith("case_")
        else int(result.get("case_id", 0)),
        "run_id": str(result.get("run_id", case_dir.name)),
        "data_boundary": str(result.get("data_boundary", "REAL_PFC")),
        "static": {
            "balls": balls,
            "walls": walls,
            "source": static,
        },
        "dimension": dimension,
        "frame_index": frame_index,
        "ball_frames": ball_frames,
        "ball_arrays": ball_arrays,
        "wall_frames": wall_frames,
        "fracture_events": fracture_events,
        "contact_frames": contact_frames,
        "history_rows": source.get("history_rows", []),
        "metric_rows": source.get("metric_rows", []),
        "source_format": source["format"],
        "input_files": file_records,
        "capture_config": result.get("config", {}),
        "engine_record": result.get("engine", {}),
        "data_boundary_record": {
            "status": result.get("data_boundary"),
            "result_status": result.get("status"),
            "validation_status": validation.get("status"),
        },
    }
