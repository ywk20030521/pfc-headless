"""Convert captured cases into a stable, variable-length NumPy representation."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from schema import (
    SCHEMA_VERSION,
    make_case,
    make_channel,
    make_entity_group,
    make_event,
    make_experiment,
    make_frame,
    make_provenance,
)
from .legacy import LegacyDataError, discover_legacy_cases, load_legacy_case


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SOURCE = ROOT / "schema"
CONTRACT_NAME = "pfc.standardized-experiment"
CONTRACT_VERSION = "1.0.0"


def _json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _append_flat(
    target: list[Any], values: Iterable[Any], frame_offsets: list[int]
) -> None:
    target.extend(values)
    frame_offsets.append(len(target))


def _array_record(arrays: dict[str, np.ndarray], key: str, unit: str | None, source: str) -> dict[str, Any]:
    value = arrays[key]
    return {
        "key": key,
        "shape": list(value.shape),
        "dtype": str(value.dtype),
        "unit": unit,
        "source": source,
    }


def export_independent_npy(
    arrays: dict[str, np.ndarray], output_dir: Path
) -> dict[str, Any]:
    """Write one NPY file per array plus a machine-readable index."""
    output_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for key in sorted(arrays):
        path = output_dir / f"{key}.npy"
        np.save(path, arrays[key], allow_pickle=False)
        files.append(
            {
                "key": key,
                "path": path.name,
                "shape": list(arrays[key].shape),
                "dtype": str(arrays[key].dtype),
                "sha256": _sha256(path),
            }
        )
    payload = {"status": "GENERATED", "arrays": files}
    _json_dump(output_dir / "index.json", payload)
    return payload


def _write_frame_summary_csv(arrays: dict[str, np.ndarray], path: Path) -> None:
    optional = [
        key
        for key in ("top_force_n", "bottom_force_n", "platen_distance_m")
        if key in arrays
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "cycle",
                "mechanical_time_total",
                "ball_count",
                "wall_vertex_count",
                *optional,
            ]
        )
        ball_counts = np.diff(arrays["frame_offsets"])
        wall_counts = np.diff(arrays["wall_offsets"])
        for index, (cycle, time_value) in enumerate(
            zip(arrays["cycle"], arrays["mechanical_time_total"])
        ):
            row: list[Any] = [
                int(cycle),
                float(time_value),
                int(ball_counts[index]),
                int(wall_counts[index]),
            ]
            for key in optional:
                value = float(arrays[key][index])
                row.append(value if math.isfinite(value) else "")
            writer.writerow(row)


def _entity_change_report(arrays: dict[str, np.ndarray]) -> dict[str, Any]:
    offsets = arrays["frame_offsets"]
    previous_ids: set[int] | None = None
    previous_radii: dict[int, float] = {}
    frames = []
    for index, (cycle, time_value) in enumerate(
        zip(arrays["cycle"], arrays["mechanical_time_total"])
    ):
        start, end = int(offsets[index]), int(offsets[index + 1])
        ids = [int(value) for value in arrays["ball_id"][start:end]]
        radii = {
            int(entity_id): float(radius)
            for entity_id, radius in zip(ids, arrays["ball_radius"][start:end])
        }
        current = set(ids)
        added = sorted(current - previous_ids) if previous_ids is not None else []
        removed = sorted(previous_ids - current) if previous_ids is not None else []
        radius_changes = {
            str(entity_id): {"before": previous_radii[entity_id], "after": radii[entity_id]}
            for entity_id in sorted(current & set(previous_radii))
            if radii[entity_id] != previous_radii[entity_id]
        }
        frames.append(
            {
                "frame_index": index,
                "cycle": int(cycle),
                "mechanical_time_total": float(time_value),
                "ball_count": len(ids),
                "added_ids": added,
                "removed_ids": removed,
                "radius_changes": radius_changes,
            }
        )
        previous_ids = current
        previous_radii = radii
    return {
        "status": "GENERATED",
        "policy": "ID sets come from each real frame; no fixed entity count is assumed.",
        "frames": frames,
        "added_id_count": sum(len(item["added_ids"]) for item in frames),
        "removed_id_count": sum(len(item["removed_ids"]) for item in frames),
    }


def _native_history_channels(case: dict[str, Any], case_root: Path) -> tuple[dict[str, np.ndarray], list[dict[str, Any]]]:
    arrays: dict[str, np.ndarray] = {}
    channels = []
    data_root = case.get("data_root")
    search_roots = []
    if data_root:
        search_roots.append(Path(data_root) / "histories")
    search_roots.extend(
        Path(entry["path"]).parent
        for entry in case["input_files"]
        if Path(entry["path"]).name.startswith("native_")
    )
    seen = set()
    index = 0
    for root in search_roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("native_*.csv")):
            if path in seen:
                continue
            seen.add(path)
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            if not rows:
                continue
            if path.name == "native_histories.csv":
                definitions = (
                    case.get("static", {})
                    .get("source", {})
                    .get("histories", {})
                )
                grouped: dict[str, list[dict[str, str]]] = {}
                for row in rows:
                    grouped.setdefault(str(row["history_id"]), []).append(row)
                for history_id, history_rows in sorted(grouped.items()):
                    history_rows.sort(key=lambda row: float(row["cycle"]))
                    safe_name = re.sub(
                        r"[^A-Za-z0-9_.-]+", "_", history_id
                    ).lower()
                    key = f"native_{safe_name}_value"
                    definition = definitions.get(history_id, {})
                    arrays[f"{key}_abscissa"] = np.asarray(
                        [float(row["cycle"]) for row in history_rows],
                        dtype=np.float64,
                    )
                    arrays[key] = np.asarray(
                        [float(row["value"]) for row in history_rows],
                        dtype=np.float64,
                    )
                    channels.append(
                        make_channel(
                            f"history_{safe_name}",
                            entity_type="history",
                            variable=history_id,
                            unit=definition.get("unit") or "UNKNOWN",
                            source="REAL_PFC",
                            dimensions=["native_history"],
                            description=definition.get(
                                "physical_meaning",
                                "Native PFC History; physical meaning is not "
                                "inferred from its name.",
                            ),
                            provenance=make_provenance(
                                source="REAL_PFC",
                                input_files=[
                                    {
                                        "path": str(path),
                                        "size_bytes": path.stat().st_size,
                                        "sha256": _sha256(path),
                                    }
                                ],
                                notes=[
                                    "Abscissa is the native History Cycle "
                                    "column; no interpolation."
                                ],
                            ),
                        )
                    )
                continue
            index += 1
            key = f"native_{index}_value"
            arrays[f"{key}_abscissa"] = np.asarray(
                [float(row["cycle_or_step"]) for row in rows], dtype=np.float64
            )
            arrays[key] = np.asarray(
                [float(row["value"]) for row in rows], dtype=np.float64
            )
            channels.append(
                make_channel(
                    f"history_{index}",
                    entity_type="history",
                    variable=path.stem,
                    unit="UNKNOWN",
                    source="REAL_PFC",
                    dimensions=["native_history"],
                    description="Native PFC History; physical meaning is not inferred from its name.",
                    provenance=make_provenance(
                        source="REAL_PFC",
                        input_files=[
                            {
                                "path": str(path),
                                "size_bytes": path.stat().st_size,
                                "sha256": _sha256(path),
                            }
                        ],
                        notes=["Abscissa is the native History first column; no interpolation."],
                    ),
                )
            )
    return arrays, channels


def _wall_force_from_index(frame: dict[str, Any], key: str) -> float | None:
    value = frame.get(key)
    return None if value is None else float(value)


def _sample_geometry(static: dict[str, Any]) -> dict[str, Any] | None:
    balls = static["balls"]
    walls = static["walls"]
    if not balls or len(walls) < 2:
        return None
    source = static.get("source", {})
    axis = str(source.get("load_axis", source.get("loading_axis", "z"))).lower()
    if axis not in {"x", "y", "z"}:
        return None
    k = "xyz".index(axis)
    roles = source.get("wall_roles")
    by_id = {int(wall["id"]): wall for wall in walls}
    if roles and "top" in roles and "bottom" in roles:
        top_id, bottom_id = int(roles["top"]), int(roles["bottom"])
    else:
        ordered = sorted(walls, key=lambda wall: float(wall["position"][k]))
        bottom_id, top_id = int(ordered[0]["id"]), int(ordered[-1]["id"])
    if top_id not in by_id or bottom_id not in by_id or top_id == bottom_id:
        return None
    top, bottom = by_id[top_id], by_id[bottom_id]
    height0 = float(top["position"][k]) - float(bottom["position"][k])
    dimension = int(static.get("source", {}).get("dimension", 3))
    transverse_spans = []
    for axis_index in range(3):
        if axis_index == k:
            continue
        values = [float(vertex["position"][axis_index]) for vertex in top["vertices"]]
        extent = max(values) - min(values) if values else 0.0
        if extent > 0:
            transverse_spans.append({"axis": "xyz"[axis_index], "extent": extent})
    if dimension == 2:
        if height0 <= 0 or len(transverse_spans) != 1:
            return None
        area0 = transverse_spans[0]["extent"]
        area_kind = "unit_thickness_length"
    else:
        if height0 <= 0 or len(transverse_spans) != 2:
            return None
        area0 = transverse_spans[0]["extent"] * transverse_spans[1]["extent"]
        area_kind = "cross_section_area"
    if area0 <= 0:
        return None
    return {
        "dimension": dimension,
        "axis": axis,
        "axis_index": k,
        "top": top_id,
        "bottom": bottom_id,
        "height0": height0,
        "area0": area0,
        "area_kind": area_kind,
        "transverse_spans": transverse_spans,
    }


def _wall_facet_arrays(walls: list[dict[str, Any]]) -> dict[str, np.ndarray]:
    """Export static wall facet topology (PFC3D) for real face rendering.

    A facet is a triangle whose corners are wall vertex IDs.  Vertex *positions*
    stay per-frame in wall_vertex_xyz; only the topology is static.  Flat arrays
    with an offset keep facets with different vertex counts representable.  If
    no wall declares facets (PFC2D / old deliveries), the arrays are empty but
    always present so downstream contracts are stable.
    """
    facet_ids: list[int] = []
    facet_wall_ids: list[int] = []
    facet_active: list[int] = []
    facet_normal: list[list[float]] = []
    facet_vertex_offsets = [0]
    facet_vertex_ids: list[int] = []
    for wall in walls:
        for facet in wall.get("facets", []):
            facet_ids.append(int(facet.get("id", len(facet_ids) + 1)))
            facet_wall_ids.append(int(wall["id"]))
            facet_active.append(int(facet.get("active", 0)))
            normal = facet.get("normal", [0.0, 0.0, 1.0])
            facet_normal.append([
                float(normal[0]),
                float(normal[1]),
                float(normal[2]) if len(normal) > 2 else 0.0,
            ])
            for vertex_id in facet.get("vertex_ids", []):
                facet_vertex_ids.append(int(vertex_id))
            facet_vertex_offsets.append(len(facet_vertex_ids))
    return {
        "wall_facet_id": np.asarray(facet_ids, dtype=np.uint64),
        "wall_facet_wall_id": np.asarray(facet_wall_ids, dtype=np.uint64),
        "wall_facet_active": np.asarray(facet_active, dtype=np.int8),
        "wall_facet_normal": np.asarray(facet_normal, dtype=np.float64).reshape((-1, 3)),
        "wall_facet_vertex_offsets": np.asarray(facet_vertex_offsets, dtype=np.int64),
        "wall_facet_vertex_ids": np.asarray(facet_vertex_ids, dtype=np.uint64),
    }


def _build_case_arrays(case: dict[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    data_boundary = str(case.get("data_boundary", "REAL_PFC"))
    raw_source = "REAL_PFC" if data_boundary == "REAL_PFC" else "CONFIG"
    frames = case["frame_index"]
    frame_count = len(frames)
    cycles = np.asarray([frame["cycle"] for frame in frames], dtype=np.int64)
    times = np.asarray(
        [frame["mechanical_time_total"] for frame in frames], dtype=np.float64
    )
    ball_offsets = [0]
    ball_ids: list[int] = []
    ball_xyz: list[float] = []
    ball_radius: list[float] = []
    ball_velocity: list[float] = []
    ball_spin: list[float] = []
    ball_present: list[float] = []
    velocity_complete = True
    spin_complete = True
    static_radius = {
        int(row["id"]): float(row["radius"]) for row in case["static"]["balls"]
    }
    for index, frame in enumerate(frames):
        rows = case["ball_frames"][int(frame["frame_id"])]
        for row in rows:
            ball_ids.append(int(row["id"]))
            ball_xyz.extend([row["x"], row["y"], row["z"]])
            radius = row.get("radius")
            ball_radius.append(
                float(radius if radius is not None else static_radius.get(int(row["id"]), float("nan")))
            )
            ball_present.append(float(index))
            if row.get("velocity") is None:
                velocity_complete = False
            else:
                ball_velocity.extend(float(value) for value in row["velocity"])
            if row.get("spin") is None:
                spin_complete = False
            else:
                ball_spin.extend(float(value) for value in row["spin"])
        ball_offsets.append(len(ball_ids))

    contact_offsets = [0]
    contact_ids: list[int] = []
    contact_xyz: list[float] = []
    contact_force_xyz: list[float] = []
    contact_end1_ids: list[int] = []
    contact_end2_ids: list[int] = []
    contact_end1_types: list[int] = []
    contact_end2_types: list[int] = []
    contact_model_codes: list[int] = []
    contact_type_names: set[str] = set()
    contact_model_names: set[str] = set()
    cumulative_contacts = 0
    for frame in frames:
        frame_contacts = case.get("contact_frames", {}).get(
            int(frame["frame_id"]), []
        )
        for row in frame_contacts:
            contact_type_names.add(str(row["end1_type"]))
            contact_type_names.add(str(row["end2_type"]))
            contact_model_names.add(str(row["model"]))
        cumulative_contacts += len(frame_contacts)
        contact_offsets.append(cumulative_contacts)
    contact_type_map = {
        name: index for index, name in enumerate(sorted(contact_type_names))
    }
    contact_model_map = {
        name: index for index, name in enumerate(sorted(contact_model_names))
    }
    for frame in frames:
        for row in case.get("contact_frames", {}).get(
            int(frame["frame_id"]), []
        ):
            contact_ids.append(int(row["id"]))
            contact_xyz.extend(float(value) for value in row["position"])
            contact_force_xyz.extend(float(value) for value in row["force_xyz"])
            contact_end1_ids.append(int(row["end1_id"]))
            contact_end2_ids.append(int(row["end2_id"]))
            contact_end1_types.append(contact_type_map[str(row["end1_type"])])
            contact_end2_types.append(contact_type_map[str(row["end2_type"])])
            contact_model_codes.append(contact_model_map[str(row["model"])])

    wall_ids: list[int] = []
    wall_vertex_ids: list[int] = []
    wall_vertex_xyz: list[float] = []
    wall_offsets = [0]
    static_vertex_wall = {
        int(vertex["id"]): int(wall["id"])
        for wall in case["static"]["walls"]
        for vertex in wall["vertices"]
    }
    for frame in frames:
        by_wall = case["wall_frames"][int(frame["frame_id"])]
        for wall_id in sorted(by_wall):
            for vertex in sorted(by_wall[wall_id], key=lambda value: value["vertex_id"]):
                vertex_id = int(vertex["vertex_id"])
                resolved_wall_id = (
                    wall_id
                    if wall_id >= 0
                    else static_vertex_wall.get(vertex_id)
                )
                if resolved_wall_id is None:
                    raise ValueError(
                        f"Wall vertex {vertex_id} has no Wall identity in static.json"
                    )
                wall_ids.append(int(resolved_wall_id))
                wall_vertex_ids.append(vertex_id)
                wall_vertex_xyz.extend(vertex["position"])
        wall_offsets.append(len(wall_ids))

    event_count = len(case["fracture_events"])
    event_ids = np.asarray([row["event_id"] for row in case["fracture_events"]], dtype=np.int64)
    event_cycles = np.asarray([row["cycle"] for row in case["fracture_events"]], dtype=np.int64)
    event_times = np.asarray(
        [row["mechanical_time_total"] for row in case["fracture_events"]], dtype=np.float64
    )
    event_modes = np.asarray([row["mode"] for row in case["fracture_events"]], dtype=np.int8)
    event_positions = np.asarray(
        [row["position"] for row in case["fracture_events"]], dtype=np.float64
    ).reshape((event_count, 3))
    event_normals = np.asarray(
        [row["normal"] for row in case["fracture_events"]], dtype=np.float64
    ).reshape((event_count, 3))
    event_diameters = np.asarray(
        [row["diameter"] for row in case["fracture_events"]], dtype=np.float64
    )
    event_ball_a = np.asarray(
        [row.get("ball_id_a", -1) for row in case["fracture_events"]], dtype=np.int64
    )
    event_ball_b = np.asarray(
        [row.get("ball_id_b", -1) for row in case["fracture_events"]], dtype=np.int64
    )
    endpoint_ids_captured = bool(event_count) and bool(
        np.any((event_ball_a > 0) & (event_ball_b > 0))
    )

    geometry = _sample_geometry(case["static"])
    top_force = np.asarray(
        [
            np.nan if frame.get("top_force") is None else float(frame["top_force"])
            for frame in frames
        ],
        dtype=np.float64,
    )
    bottom_force = np.asarray(
        [
            np.nan if frame.get("bottom_force") is None else float(frame["bottom_force"])
            for frame in frames
        ],
        dtype=np.float64,
    )

    walls_by_id = {int(wall["id"]): wall for wall in case["static"]["walls"]}
    wall_axis_center = np.full(frame_count, np.nan, dtype=np.float64)
    if geometry:
        for index, frame in enumerate(frames):
            vertices = case["wall_frames"][int(frame["frame_id"])]
            top_vertices = vertices.get(geometry["top"], [])
            bottom_vertices = vertices.get(geometry["bottom"], [])
            if top_vertices and bottom_vertices:
                k = geometry["axis_index"]
                top_center = sum(value["position"][k] for value in top_vertices) / len(top_vertices)
                bottom_center = sum(value["position"][k] for value in bottom_vertices) / len(bottom_vertices)
                wall_axis_center[index] = top_center - bottom_center
            else:
                raw = frame.get("raw", {})
                top_key = f"wall1_{geometry['axis']}"
                bottom_key = f"wall2_{geometry['axis']}"
                if raw.get(top_key) not in {None, ""} and raw.get(bottom_key) not in {None, ""}:
                    wall_axis_center[index] = float(raw[top_key]) - float(raw[bottom_key])

    arrays: dict[str, np.ndarray] = {
        "cycle": cycles,
        "mechanical_time_total": times,
        "frame_offsets": np.asarray(ball_offsets, dtype=np.int64),
        "ball_id": np.asarray(ball_ids, dtype=np.uint64),
        "ball_xyz": np.asarray(ball_xyz, dtype=np.float64).reshape((-1, 3)),
        "ball_radius": np.asarray(ball_radius, dtype=np.float64),
        "ball_frame_index": np.asarray(ball_present, dtype=np.int64),
        "wall_offsets": np.asarray(wall_offsets, dtype=np.int64),
        "wall_id": np.asarray(wall_ids, dtype=np.uint64),
        "wall_vertex_id": np.asarray(wall_vertex_ids, dtype=np.uint64),
        "wall_vertex_xyz": np.asarray(wall_vertex_xyz, dtype=np.float64).reshape((-1, 3)),
        **_wall_facet_arrays(case["static"]["walls"]),
        "fracture_event_id": event_ids,
        "fracture_cycle": event_cycles,
        "fracture_mechanical_time_total": event_times,
        "fracture_mode": event_modes,
        "fracture_position": event_positions,
        "fracture_normal": event_normals,
        "fracture_diameter": event_diameters,
    }
    if endpoint_ids_captured:
        arrays["fracture_ball_id_a"] = event_ball_a
        arrays["fracture_ball_id_b"] = event_ball_b
    if velocity_complete and ball_velocity:
        arrays["ball_velocity"] = np.asarray(ball_velocity, dtype=np.float64).reshape((-1, 3))
    if spin_complete and ball_spin:
        arrays["ball_spin"] = np.asarray(ball_spin, dtype=np.float64).reshape((-1, 3))
    if contact_ids:
        arrays.update(
            {
                "contact_offsets": np.asarray(contact_offsets, dtype=np.int64),
                "contact_id": np.asarray(contact_ids, dtype=np.uint64),
                "contact_xyz": np.asarray(contact_xyz, dtype=np.float64).reshape((-1, 3)),
                "contact_force_xyz": np.asarray(contact_force_xyz, dtype=np.float64).reshape((-1, 3)),
                "contact_end1_id": np.asarray(contact_end1_ids, dtype=np.uint64),
                "contact_end2_id": np.asarray(contact_end2_ids, dtype=np.uint64),
                "contact_end1_type": np.asarray(contact_end1_types, dtype=np.int16),
                "contact_end2_type": np.asarray(contact_end2_types, dtype=np.int16),
                "contact_model": np.asarray(contact_model_codes, dtype=np.int16),
            }
        )
    if np.isfinite(top_force).any():
        arrays["top_force_n"] = top_force
    if np.isfinite(bottom_force).any():
        arrays["bottom_force_n"] = bottom_force
    if np.isfinite(wall_axis_center).any():
        arrays["platen_distance_m"] = wall_axis_center

    native_arrays, native_channels = _native_history_channels(case, Path("."))
    arrays.update(native_arrays)

    channels: list[dict[str, Any]] = [
        make_channel(
            "cycle",
            entity_type="history",
            variable="cycle",
            unit="cycle",
            source=raw_source,
            dimensions=["frame"],
            description="PFC Cycle at capture.",
        ),
        make_channel(
            "mechanical_time_total",
            entity_type="history",
            variable="mechanical_time_total",
            unit="s",
            source=raw_source,
            dimensions=["frame"],
            description="PFC total mechanical time at capture.",
        ),
        make_channel(
            "ball_id",
            entity_type="ball",
            variable="id",
            unit=None,
            source=raw_source,
            dimensions=["entity", "frame_variable_length"],
            description="Stable PFC Ball ID; offsets define each real frame.",
        ),
        make_channel(
            "ball_xyz",
            entity_type="ball",
            variable="position",
            unit="m",
            source=raw_source,
            dimensions=["entity", "xyz"],
            description="Same-Cycle Ball coordinates.",
        ),
        make_channel(
            "ball_radius",
            entity_type="ball",
            variable="radius",
            unit="m",
            source=raw_source,
            dimensions=["entity"],
            description="Static radius or a real radius update at/after Ball creation.",
        ),
        make_channel(
            "wall_vertex_xyz",
            entity_type="wall",
            variable="vertex_position",
            unit="m",
            source=raw_source,
            dimensions=["entity", "xyz", "frame_variable_length"],
            description="Wall vertices from each captured frame.",
        ),
    ]
    # Static wall facet topology (PFC3D). Registered as a channel so capability
    # detection and the output contract can advertise real wall faces. Vertex
    # positions stay per-frame in wall_vertex_xyz.
    if len(arrays.get("wall_facet_id", [])) > 0:
        channels.append(
            make_channel(
                "wall_facet_vertex_ids",
                entity_type="wall",
                variable="facet_vertex_topology",
                unit=None,
                source=raw_source,
                dimensions=["facet", "variable_length"],
                description=(
                    "Static facet corner vertex IDs (flat, indexed by "
                    "wall_facet_vertex_offsets); join with per-frame "
                    "wall_vertex_xyz to rebuild real wall faces."
                ),
            )
        )
        channels.append(
            make_channel(
                "wall_facet_normal",
                entity_type="wall",
                variable="facet_normal",
                unit=None,
                source=raw_source,
                dimensions=["facet", "xyz"],
                description="Static facet unit normals for real wall face rendering.",
            )
        )
    if "ball_velocity" in arrays:
        channels.append(
            make_channel(
                "ball_velocity",
                entity_type="ball",
                variable="velocity",
                unit="m/s",
                source=raw_source,
                dimensions=["entity", "xyz"],
                description="Captured Ball velocity in the global coordinate system.",
            )
        )
    if "ball_spin" in arrays:
        channels.append(
            make_channel(
                "ball_spin",
                entity_type="ball",
                variable="angular_velocity",
                unit="rad/s",
                source=raw_source,
                dimensions=["entity", "xyz"],
                description="Captured Ball angular velocity; PFC2D uses the z component.",
            )
        )
    if contact_ids:
        channels.extend(
            [
                make_channel(
                    "contact_id",
                    entity_type="contact",
                    variable="id",
                    unit=None,
                    source=raw_source,
                    dimensions=["contact", "frame_variable_length"],
                    description="Captured contact ID and force at each selected frame.",
                ),
                make_channel(
                    "contact_force_xyz",
                    entity_type="contact",
                    variable="force_global",
                    unit="N",
                    source=raw_source,
                    dimensions=["contact", "xyz"],
                    description="Contact force in the global coordinate system.",
                ),
            ]
        )
    else:
        channels.extend(
            [
                make_channel(
                    "contact_id",
                    entity_type="contact",
                    variable="id",
                    unit=None,
                    source="NOT_CAPTURED",
                    status="NOT_CAPTURED",
                    dimensions=["contact"],
                    description="Contact network was disabled for this Case.",
                ),
                make_channel(
                    "contact_force_xyz",
                    entity_type="contact",
                    variable="force_global",
                    unit="N",
                    source="NOT_CAPTURED",
                    status="NOT_CAPTURED",
                    dimensions=["contact", "xyz"],
                    description="Contact force was not captured.",
                ),
            ]
        )
    if event_count:
        channels.extend(
            [
                make_channel(
                    "fracture_events",
                    entity_type="fracture",
                    variable="bond_break",
                    unit="event",
                    source=raw_source,
                    dimensions=["event"],
                    description="Real bond-break/DFN-matched fracture events.",
                ),
                make_channel(
                    "fracture_normal",
                    entity_type="fracture",
                    variable="normal",
                    unit=None,
                    source=raw_source,
                    dimensions=["event", "xyz"],
                    description="Captured fracture normal; orientation is not inferred.",
                ),
                make_channel(
                    "fracture_ball_id_a",
                    entity_type="fracture",
                    variable="endpoint_ball_id_a",
                    unit=None,
                    source=raw_source if endpoint_ids_captured else "NOT_CAPTURED",
                    status="GENERATED" if endpoint_ids_captured else "NOT_CAPTURED",
                    dimensions=["event"],
                    description=(
                        "Ball ID at contact end1 when the bond broke; -1 when the "
                        "endpoint is not a Ball or was not captured."
                    ),
                ),
                make_channel(
                    "fracture_ball_id_b",
                    entity_type="fracture",
                    variable="endpoint_ball_id_b",
                    unit=None,
                    source=raw_source if endpoint_ids_captured else "NOT_CAPTURED",
                    status="GENERATED" if endpoint_ids_captured else "NOT_CAPTURED",
                    dimensions=["event"],
                    description=(
                        "Ball ID at contact end2 when the bond broke; -1 when the "
                        "endpoint is not a Ball or was not captured."
                    ),
                ),
            ]
        )
    if "top_force_n" in arrays:
        channels.append(
            make_channel(
                "top_force_n",
                entity_type="wall",
                variable="contact_force_magnitude",
                unit="N",
                source=raw_source,
                dimensions=["frame"],
                description="Top platen contact-force magnitude.",
            )
        )
    if "bottom_force_n" in arrays:
        channels.append(
            make_channel(
                "bottom_force_n",
                entity_type="wall",
                variable="contact_force_magnitude",
                unit="N",
                source=raw_source,
                dimensions=["frame"],
                description="Bottom platen contact-force magnitude.",
            )
        )
    channels.extend(native_channels)

    entities = [
        make_entity_group(
            "ball",
            array_prefix="ball",
            count=len(ball_ids),
            dynamic_ids=True,
            properties=["id", "position", "radius", "frame_index"],
        ),
        make_entity_group(
            "wall",
            array_prefix="wall",
            count=len(wall_ids),
            dynamic_ids=True,
            properties=["id", "vertex_id", "vertex_position"],
        ),
    ]
    if contact_ids:
        entities.append(
            make_entity_group(
                "contact",
                array_prefix="contact",
                count=len(contact_ids),
                dynamic_ids=True,
                properties=["id", "position", "force_global", "end1_id", "end2_id"],
            )
        )
    if event_count:
        fracture_properties = ["id", "cycle", "position", "normal", "diameter", "mode"]
        if endpoint_ids_captured:
            fracture_properties.extend(["ball_id_a", "ball_id_b"])
        entities.append(
            make_entity_group(
                "fracture",
                array_prefix="fracture",
                count=event_count,
                dynamic_ids=False,
                properties=fracture_properties,
            )
        )

    frame_records = []
    for index, frame in enumerate(frames):
        entity_offsets = {
            "ball": [int(ball_offsets[index]), int(ball_offsets[index + 1])],
            "wall": [int(wall_offsets[index]), int(wall_offsets[index + 1])],
        }
        if contact_ids:
            entity_offsets["contact"] = [
                int(contact_offsets[index]),
                int(contact_offsets[index + 1]),
            ]
        frame_records.append(
            make_frame(
                int(frame["frame_id"]),
                cycle=int(frame["cycle"]),
                mechanical_time_total=float(frame["mechanical_time_total"]),
                entity_offsets=entity_offsets,
                provenance=make_provenance(
                    source=raw_source,
                    parent_results=["case conversion_report.json"],
                    method="frame membership preserved through explicit slice offsets",
                ),
            )
        )

    event_records = []
    for row in case["fracture_events"]:
        properties = {
            "mode": int(row["mode"]),
            "contact_id": int(row["contact_id"]),
            "failure_strength": float(row["failure_strength"]),
            "normal": row["normal"],
            "diameter": float(row["diameter"]),
        }
        if endpoint_ids_captured:
            properties["ball_id_a"] = int(row.get("ball_id_a", -1))
            properties["ball_id_b"] = int(row.get("ball_id_b", -1))
        event_records.append(
            make_event(
                int(row["event_id"]),
                event_type="bond_break",
                cycle=int(row["cycle"]),
                mechanical_time_total=float(row["mechanical_time_total"]),
                position=row["position"],
                properties=properties,
                source=raw_source,
            )
        )
    summary = {
        "geometry": geometry,
        "static_balls": case["static"]["balls"],
        "static_walls": case["static"]["walls"],
        "array_records": [
            _array_record(arrays, key, channel.get("unit"), channel["source"])
            for channel in channels
            for key in [channel["id"]]
            if key in arrays
        ],
        "frame_records": frame_records,
        "event_records": event_records,
        "fracture_endpoint_ids_status": (
            "REAL_PFC" if endpoint_ids_captured else "NOT_CAPTURED"
        ),
        "contact_type_map": contact_type_map,
        "contact_model_map": contact_model_map,
        "contact_count": len(contact_ids),
    }
    return arrays, summary, channels, entities


def standardize_experiment(
    input_root: Path,
    output_root: Path,
    *,
    title: str | None = None,
    experiment_id: str | None = None,
    execution_mode: str = "UNKNOWN",
    pfc_version: str | None = None,
    export_npy: bool = False,
) -> dict[str, Any]:
    """Create a standardized experiment without overwriting raw inputs."""
    input_root = input_root.resolve()
    output_root = output_root.resolve()
    if (
        input_root == output_root
        or input_root in output_root.parents
        or output_root in input_root.parents
    ):
        raise ValueError(
            "Standardized output and raw input must be separate directory trees"
        )
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(
            f"Refusing to overwrite an existing standardized delivery: {output_root}"
        )
    case_dirs = discover_legacy_cases(input_root)
    cases_root = output_root / "cases"
    schema_root = output_root / "schema"
    cases_root.mkdir(parents=True, exist_ok=True)
    schema_root.mkdir(parents=True, exist_ok=True)
    for schema_path in sorted(SCHEMA_SOURCE.glob("*.json")):
        shutil.copy2(schema_path, schema_root / schema_path.name)

    case_records = []
    conversion_records = []
    legacy_records = []
    boundaries = []
    for case_dir in case_dirs:
        legacy = load_legacy_case(case_dir)
        legacy_records.append(legacy)
        boundaries.append(str(legacy.get("data_boundary", "REAL_PFC")))
        raw_source = "REAL_PFC" if legacy.get("data_boundary") == "REAL_PFC" else "CONFIG"
        arrays, summary, channels, entities = _build_case_arrays(legacy)
        case_id = int(legacy["case_id"])
        case_out = cases_root / f"case_{case_id}"
        case_out.mkdir(parents=True, exist_ok=True)
        npz_path = case_out / "arrays.npz"
        np.savez_compressed(npz_path, **arrays)
        _write_frame_summary_csv(arrays, case_out / "frame_summary.csv")
        if export_npy:
            export_independent_npy(arrays, case_out / "npy")
        _json_dump(case_out / "frames.json", summary["frame_records"])
        _json_dump(case_out / "events.json", summary["event_records"])
        entity_changes = _entity_change_report(arrays)
        _json_dump(case_out / "entity_changes.json", entity_changes)
        _json_dump(
            case_out / "static.json",
            {
                "dimension": legacy["dimension"],
                "balls": summary["static_balls"],
                "walls": summary["static_walls"],
                "geometry": summary["geometry"],
            },
        )
        provenance = make_provenance(
            source=raw_source,
            input_files=legacy["input_files"],
            method="read-only legacy adapter; variable-length concatenated arrays; NPZ compression",
            notes=[
                "Raw capture files were not modified.",
                "Each frame uses explicit offsets; Ball sets may grow or shrink.",
            ],
        )
        case_record = make_case(
            case_id,
            label=f"Case {case_id}",
            run_id=legacy["run_id"],
            dimension=int(legacy["dimension"]),
            source_format=legacy["source_format"],
            frame_count=len(arrays["cycle"]),
            arrays_path=npz_path.relative_to(output_root).as_posix(),
            channels=channels,
            entity_groups=entities,
            metadata={
                "geometry": summary["geometry"],
                "ball_count_min": int(np.diff(arrays["frame_offsets"]).min()),
                "ball_count_max": int(np.diff(arrays["frame_offsets"]).max()),
                "event_count": int(len(arrays["fracture_event_id"])),
                "contact_count": summary["contact_count"],
                "contact_type_codes": summary["contact_type_map"],
                "contact_model_codes": summary["contact_model_map"],
                "cycle_start": int(arrays["cycle"][0]),
                "cycle_end": int(arrays["cycle"][-1]),
                "mechanical_time_start": float(arrays["mechanical_time_total"][0]),
                "mechanical_time_end": float(arrays["mechanical_time_total"][-1]),
            },
            provenance=provenance,
        )
        _json_dump(case_out / "case.json", case_record)
        _json_dump(case_out / "channels.json", channels)
        array_records = []
        for key, value in arrays.items():
            array_records.append(
                {
                    "key": key,
                    "shape": list(value.shape),
                    "dtype": str(value.dtype),
                    "source": raw_source if key.startswith(("cycle", "ball", "wall", "fracture", "top_force", "bottom_force", "platen")) else "DERIVED",
                }
            )
        report = {
            "status": "GENERATED",
            "case_id": case_id,
            "input_files": legacy["input_files"],
            "output_file": str(npz_path),
            "output_sha256": _sha256(npz_path),
            "arrays": array_records,
            "fracture_endpoint_ids_status": summary["fracture_endpoint_ids_status"],
            "integrity": {
                "status": "PASS_AT_CONVERSION_TIME",
                "frame_count": len(arrays["cycle"]),
                "frame_offsets": [0, int(arrays["frame_offsets"][-1])],
                "ball_observation_count": int(len(arrays["ball_id"])),
                "wall_observation_count": int(len(arrays["wall_id"])),
                "strictly_increasing_cycle": bool(
                    np.all(np.diff(arrays["cycle"]) > 0)
                ),
                "strictly_increasing_mechanical_time": bool(
                    np.all(np.diff(arrays["mechanical_time_total"]) > 0)
                ),
            },
            "entity_changes": {
                "added_id_count": entity_changes["added_id_count"],
                "removed_id_count": entity_changes["removed_id_count"],
            },
            "missing_fields": [
                channel["id"]
                for channel in channels
                if channel["status"] == "NOT_CAPTURED"
            ],
            "truth_boundary": "Original files remain unchanged; no missing value is zero-filled.",
        }
        _json_dump(case_out / "conversion_report.json", report)
        case_records.append(case_record)
        conversion_records.append(report)

    distinct_boundaries = sorted(set(boundaries))
    experiment_boundary = (
        distinct_boundaries[0]
        if len(distinct_boundaries) == 1
        else "MIXED"
    )
    experiment = make_experiment(
        experiment_id=experiment_id or input_root.name,
        title=title or input_root.name,
        pfc_version=pfc_version,
        execution_mode=execution_mode,
        dimensions=sorted({case["dimension"] for case in case_records}),
        cases=case_records,
        data_boundary=experiment_boundary,
        metadata={
            "conversion": "NumPy NPZ with variable-length entity offsets",
            "raw_input_root": str(input_root),
            "case_count": len(case_records),
        },
        provenance=make_provenance(
            source="CONFIG",
            input_files=[
                file
                for case_report in conversion_records
                for file in case_report["input_files"]
            ],
            method="standardize_experiment",
        ),
    )
    _json_dump(output_root / "experiment.json", experiment)
    _json_dump(
        output_root / "conversion_report.json",
        {
            "status": "GENERATED",
            "schema_version": SCHEMA_VERSION,
            "experiment_id": experiment["experiment_id"],
            "cases": conversion_records,
            "raw_data_immutable": True,
        },
    )
    validation_checks = []
    for case, conversion in zip(case_records, conversion_records):
        arrays_path = output_root / case["arrays_path"]
        with np.load(arrays_path, allow_pickle=False) as arrays:
            frame_count = int(case["frame_count"])
            checks = {
                "arrays_exist": arrays_path.is_file(),
                "arrays_hash_matches": _sha256(arrays_path)
                == conversion["output_sha256"],
                "frame_lengths_match": len(arrays["cycle"]) == frame_count,
                "frame_offsets_match": len(arrays["frame_offsets"])
                == frame_count + 1,
                "final_ball_offset_matches": int(arrays["frame_offsets"][-1])
                == len(arrays["ball_id"]),
                "cycles_strictly_increase": bool(
                    np.all(np.diff(arrays["cycle"]) > 0)
                ),
                "mechanical_time_strictly_increases": bool(
                    np.all(np.diff(arrays["mechanical_time_total"]) > 0)
                ),
                "real_pfc_boundary": case["provenance"]["source"]
                in {"REAL_PFC", "CONFIG"},
            }
            validation_checks.append(
                {
                    "case_id": int(case["case_id"]),
                    "status": "PASS" if all(checks.values()) else "FAIL",
                    "checks": checks,
                    "frame_count": frame_count,
                    "ball_observations": int(len(arrays["ball_id"])),
                    "wall_observations": int(len(arrays["wall_id"])),
                }
            )
    validation_report = {
        "schema_version": "1.0.0",
        "status": (
            "PASS"
            if all(item["status"] == "PASS" for item in validation_checks)
            else "FAIL"
        ),
        "raw_data_immutable": True,
        "analysis_output_inside_contract": False,
        "missing_values_zero_filled": False,
        "cases": validation_checks,
        "generated_utc": experiment["generated_utc"],
    }
    _json_dump(output_root / "validation_report.json", validation_report)
    if validation_report["status"] != "PASS":
        raise ValueError("Standardized package failed its independent validation")
    primary_case = case_records[0]
    primary_legacy = legacy_records[0]
    primary_conversion = conversion_records[0]
    existing_files = [
        path
        for path in sorted(output_root.rglob("*"))
        if path.is_file()
        and path.name not in {"metadata.json", "manifest.json", "delivery_manifest.json"}
    ]
    data_file_records = [
        {
            "path": path.relative_to(output_root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in existing_files
    ]
    static_source = primary_legacy["static"].get("source", {})
    snapshot = static_source.get("snapshot", {})
    capture_config = primary_legacy.get("capture_config", {})
    script_inputs = [
        {
            "path": Path(entry["path"]).name,
            "size_bytes": entry.get("size_bytes"),
            "sha256": entry.get("sha256"),
        }
        for entry in primary_legacy.get("input_files", [])
    ]
    topology_payload = {
        "balls": primary_legacy["static"]["balls"],
        "walls": primary_legacy["static"]["walls"],
        "fractures": primary_legacy.get("fracture_events", []),
    }
    model_sha256 = hashlib.sha256(
        json.dumps(
            topology_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    package_metadata = {
        "schema_version": "1.0.0",
        "run_id": primary_case["run_id"],
        "case_id": int(primary_case["case_id"]),
        "case_ids": [int(case["case_id"]) for case in case_records],
        "engine_dimension": int(primary_case["dimension"]),
        "engine_version": pfc_version,
        "model_identity": {
            "sha256": model_sha256,
            "ball_count": len(primary_legacy["static"]["balls"]),
            "wall_count": len(primary_legacy["static"]["walls"]),
            "wall_vertex_count": sum(
                len(wall.get("vertices", []))
                for wall in primary_legacy["static"]["walls"]
            ),
            "basis": "static initial topology plus captured fracture events",
        },
        "script_identity": {
            "input_files": script_inputs,
            "capture_config_sha256": hashlib.sha256(
                json.dumps(
                    capture_config,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "capture_config_available": bool(capture_config),
        },
        "parameters": (
            capture_config.get("headless", {}).get("parameters", {})
            if isinstance(capture_config.get("headless"), dict)
            else {}
        ),
        "sampling_configuration": {
            "mode": capture_config.get(
                "sample_mode",
                capture_config.get("sample_interval_mode", "cycle"),
            ),
            "value": capture_config.get(
                "sample_interval",
                capture_config.get(
                    "sample_interval_time",
                    capture_config.get("sample_stride_cycles"),
                ),
            ),
            "capture_contacts": bool(capture_config.get("capture_contacts", False)),
            "source": "recorded capture configuration",
        },
        "units": {
            "length": "m",
            "time": "s",
            "force": "N",
            "velocity": "m/s",
            "angular_velocity": "rad/s",
            "unknown_native_histories": "UNKNOWN",
        },
        "coordinate_system": {
            "name": "PFC_GLOBAL_CARTESIAN",
            "dimensions": int(primary_case["dimension"]),
            "pfc2d_z": (
                "numeric embedding only; not a physical out-of-plane coordinate"
                if int(primary_case["dimension"]) == 2
                else "physical PFC3D coordinate"
            ),
        },
        "time_range": [
            primary_case["metadata"]["mechanical_time_start"],
            primary_case["metadata"]["mechanical_time_end"],
        ],
        "step_range": [
            int(primary_case["metadata"].get("cycle_start", 0)),
            int(primary_case["metadata"].get("cycle_end", 0)),
        ],
        "data_files": data_file_records,
        "file_hashes": {
            entry["path"]: entry["sha256"] for entry in data_file_records
        },
        "record_counts": {
            "cases": len(case_records),
            "frames": int(primary_case["frame_count"]),
            "ball_observations": int(
                primary_conversion["integrity"]["ball_observation_count"]
            ),
            "wall_observations": int(
                primary_conversion["integrity"]["wall_observation_count"]
            ),
            "events": int(len(primary_legacy.get("fracture_events", []))),
        },
        "validation_status": "PASS",
        "source": {
            "raw_input_root": str(input_root),
            "data_boundary": primary_legacy.get("data_boundary", "REAL_PFC"),
            "engine": primary_legacy.get("engine_record", {}),
            "snapshot": snapshot,
        },
    }
    metadata_path = output_root / "metadata.json"
    _json_dump(metadata_path, package_metadata)
    manifest_files = [
        {
            "path": path.relative_to(output_root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(output_root.rglob("*"))
        if path.is_file()
        and path.name not in {"manifest.json", "delivery_manifest.json"}
    ]
    _json_dump(
        output_root / "manifest.json",
        {
            **{
                key: package_metadata[key]
                for key in (
                    "schema_version",
                    "run_id",
                    "case_id",
                    "engine_dimension",
                    "engine_version",
                    "model_identity",
                    "script_identity",
                    "parameters",
                    "sampling_configuration",
                    "units",
                    "coordinate_system",
                    "time_range",
                    "step_range",
                    "data_files",
                    "file_hashes",
                    "record_counts",
                    "validation_status",
                )
            },
            "metadata_file": "metadata.json",
            "files": manifest_files,
            "files_sha256_verified": True,
        },
    )
    artifact_records = []
    for path in sorted(output_root.rglob("*")):
        if not path.is_file() or path.name == "delivery_manifest.json":
            continue
        artifact_records.append(
            {
                "path": path.relative_to(output_root).as_posix(),
                "sha256": _sha256(path),
                "size_bytes": path.stat().st_size,
            }
        )
    experiment_path = output_root / "experiment.json"
    _json_dump(
        output_root / "delivery_manifest.json",
        {
            "contract": {
                "name": CONTRACT_NAME,
                "version": CONTRACT_VERSION,
                "schema_version": SCHEMA_VERSION,
                "immutable": True,
                "scope": "STANDARDIZED_EXPERIMENT_DATA",
            },
            "producer": {
                "skill": "pfc-headless",
                "entrypoint": "standardize_experiment",
            },
            "experiment": {
                "path": "experiment.json",
                "sha256": _sha256(experiment_path),
                "size_bytes": experiment_path.stat().st_size,
            },
            "raw_input": {
                "root": str(input_root),
                "read_only": True,
                "embedded_in_contract": False,
                "input_file_count": sum(
                    len(report["input_files"]) for report in conversion_records
                ),
            },
            "cases": [
                {
                    "case_id": int(report["case_id"]),
                    "conversion_report": (
                        f"cases/case_{int(report['case_id'])}/conversion_report.json"
                    ),
                    "arrays": (
                        f"cases/case_{int(report['case_id'])}/arrays.npz"
                    ),
                    "arrays_sha256": report["output_sha256"],
                }
                for report in conversion_records
            ],
            "artifacts": artifact_records,
            "integrity": {
                "status": "PASS_AT_CONVERSION_TIME",
                "raw_files_modified": False,
                "missing_values_zero_filled": False,
                "frames_interpolated": False,
            },
            "consumer_policy": {
                "read_only": True,
                "may_write_inside_contract": False,
                "analysis_output_must_be_separate": True,
            },
            "generated_utc": experiment["generated_utc"],
        },
    )
    return experiment
