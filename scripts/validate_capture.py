from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite(values: list[str], label: str) -> list[float]:
    parsed = [float(value) for value in values]
    if not all(math.isfinite(value) for value in parsed):
        raise ValueError(f"Non-finite value in {label}: {values}")
    return parsed


def optional_finite(values: list[str], label: str) -> list[float] | None:
    if all(value == "" for value in values):
        return None
    if any(value == "" for value in values):
        raise ValueError(f"Partially missing value in {label}: {values}")
    return finite(values, label)


def optional_float(value: str, label: str) -> float | None:
    if value == "":
        return None
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"Non-finite value in {label}: {value}")
    return parsed


def optional_int(value: str | None, default: int = -1) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(str(value).strip())
    except ValueError:
        return default


def validate(run_dir: Path) -> dict[str, Any]:
    result_path = run_dir / "metadata" / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    errors = []
    warnings = []

    index_rows = []
    with (run_dir / "raw" / "frame_index.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        for row in csv.DictReader(handle):
            index_rows.append(
                {
                    "frame_id": int(row["frame_id"]),
                    "cycle": int(row["cycle"]),
                    "mechanical_time_total": float(row["mechanical_time_total"]),
                    "ball_count": int(row["ball_count"]),
                    "wall1": optional_finite(
                        [row["wall1_x"], row["wall1_y"], row["wall1_z"]],
                        "frame index wall1",
                    ),
                    "wall2": optional_finite(
                        [row["wall2_x"], row["wall2_y"], row["wall2_z"]],
                        "frame index wall2",
                    ),
                    "top_force": optional_float(
                        row["top_force_magnitude"], "frame index top force"
                    ),
                    "bottom_force": optional_float(
                        row["bottom_force_magnitude"], "frame index bottom force"
                    ),
                    "callback_calls": int(row["callback_calls"]),
                }
            )

    frame_ids = [row["frame_id"] for row in index_rows]
    if frame_ids != list(range(1, len(frame_ids) + 1)):
        errors.append("frame_id sequence is not contiguous from 1")
    if any(
        right["cycle"] <= left["cycle"]
        for left, right in zip(index_rows, index_rows[1:])
    ):
        errors.append("Cycle is not strictly increasing")
    if any(
        right["mechanical_time_total"] <= left["mechanical_time_total"]
        for left, right in zip(index_rows, index_rows[1:])
    ):
        errors.append("Mechanical Time is not strictly increasing")

    ball_counts: dict[int, int] = defaultdict(int)
    ball_ids: dict[int, set[int]] = defaultdict(set)
    duplicate_balls = 0
    velocity_rows = 0
    spin_rows = 0
    with (run_dir / "raw" / "ball_frames.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        ball_reader = csv.DictReader(handle)
        for row in ball_reader:
            fid = int(row["frame_id"])
            ball_id = int(row["ball_id"])
            values = [row["x"], row["y"], row["z"]]
            if row.get("radius") not in {None, ""}:
                values.append(row["radius"])
            finite(values, f"Ball {ball_id} frame {fid}")
            for key in ("vx", "vy", "vz"):
                if row.get(key) not in {None, ""}:
                    finite([row[key]], f"Ball {ball_id} velocity {key}")
            if any(row.get(key) not in {None, ""} for key in ("vx", "vy", "vz")):
                velocity_rows += 1
            for key in ("spin_x", "spin_y", "spin_z"):
                if row.get(key) not in {None, ""}:
                    finite([row[key]], f"Ball {ball_id} spin {key}")
            if any(
                row.get(key) not in {None, ""}
                for key in ("spin_x", "spin_y", "spin_z")
            ):
                spin_rows += 1
            if ball_id in ball_ids[fid]:
                duplicate_balls += 1
            ball_ids[fid].add(ball_id)
            ball_counts[fid] += 1

    previous_ids: set[int] | None = None
    added_ids: list[int] = []
    removed_ids: list[int] = []
    for row in index_rows:
        fid = row["frame_id"]
        if ball_counts[fid] != row["ball_count"]:
            errors.append(
                f"Frame {fid} Ball rows {ball_counts[fid]} != "
                f"index count {row['ball_count']}"
            )
        if len(ball_ids[fid]) != ball_counts[fid]:
            errors.append(f"Frame {fid} contains duplicate Ball IDs")
        if previous_ids is not None:
            added = ball_ids[fid] - previous_ids
            removed = previous_ids - ball_ids[fid]
            added_ids.extend(sorted(added))
            removed_ids.extend(sorted(removed))
        previous_ids = ball_ids[fid]
    if duplicate_balls:
        errors.append(f"Found {duplicate_balls} duplicate Ball rows")

    wall_counts: dict[int, int] = defaultdict(int)
    wall_ids: dict[int, set[int]] = defaultdict(set)
    with (run_dir / "raw" / "wall_vertices.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        for row in csv.DictReader(handle):
            fid = int(row["frame_id"])
            vertex_id = int(row["vertex_id"])
            finite(
                [row["x"], row["y"], row["z"]],
                f"Wall vertex {vertex_id} frame {fid}",
            )
            wall_counts[fid] += 1
            wall_ids[fid].add(vertex_id)
    static_path = run_dir / "static.json"
    expected_wall_ids = {
        int(vertex["id"])
        for wall in json.loads(static_path.read_text(encoding="utf-8"))["walls"]["walls"]
        for vertex in wall["vertices"]
    }
    for row in index_rows:
        fid = row["frame_id"]
        expected_wall_rows = sum(
            len(wall["vertices"])
            for wall in json.loads(static_path.read_text(encoding="utf-8"))["walls"]["walls"]
        )
        if wall_counts[fid] != expected_wall_rows:
            errors.append(
                f"Frame {fid} Wall vertex data incomplete: "
                f"count={wall_counts[fid]} expected={expected_wall_rows}"
            )

    fracture_events = []
    with (run_dir / "raw" / "fracture_events.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        for row in csv.DictReader(handle):
            fracture_events.append(
                {
                    "event_id": int(row["event_id"]),
                    "cycle": int(row["cycle"]),
                    "mechanical_time_total": float(row["mechanical_time_total"]),
                    "contact_id": optional_int(row.get("contact_id")),
                    "ball_id_a": optional_int(row.get("ball_id_a")),
                    "ball_id_b": optional_int(row.get("ball_id_b")),
                    "mode": int(row["mode"]),
                    "failure_strength": float(row["failure_strength"]),
                    "position": finite(
                        [row["x"], row["y"], row["z"]], "fracture position"
                    ),
                    "normal": finite([row["nx"], row["ny"], row["nz"]], "fracture normal"),
                    "diameter": float(row["diameter"]),
                }
            )
    if len(fracture_events) != int(
        (result.get("capture") or {}).get("fracture_event_count", 0)
    ):
        errors.append("Fracture event count differs from result.json")

    contact_rows = 0
    contact_file = run_dir / "raw" / "contact_frames.csv"
    if contact_file.is_file():
        with contact_file.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                int(row["frame_id"])
                int(row["contact_id"])
                finite(
                    [
                        row["x"],
                        row["y"],
                        row["z"],
                        row["fx"],
                        row["fy"],
                        row["fz"],
                    ],
                    "contact sample",
                )
                contact_rows += 1

    catalog_path = run_dir / "fractures_final.json"
    catalog = []
    if catalog_path.is_file():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog_status = str(result.get("fracture_catalog_status") or "")
    matched_events = 0
    if catalog_status == "NOT_SUPPORTED" and fracture_events:
        # PFC2D has no itasca.dfn catalog; bond-break FISH events are the
        # authoritative fracture record and need no DFN cross-check.
        matched_events = len(fracture_events)
    elif catalog:
        used_ids = set()
        for event in fracture_events:
            candidates = []
            for fracture in catalog:
                if fracture["id"] in used_ids:
                    continue
                if "tension" in str(fracture.get("dfn_name", "")).lower() and event["mode"] != 1:
                    continue
                if "shear" in str(fracture.get("dfn_name", "")).lower() and event["mode"] != 2:
                    continue
                if max(
                    abs(a - b)
                    for a, b in zip(event["position"], fracture["position"])
                ) > 1.0e-8:
                    continue
                if abs(event["diameter"] - fracture["diameter"]) > 1.0e-10:
                    continue
                if abs(
                    event["mechanical_time_total"] - fracture["age"]
                ) > 1.0e-10:
                    continue
                if abs(
                    event["failure_strength"] - fracture["failure_strength"]
                ) > 1.0e-8:
                    continue
                candidates.append(fracture)
            if len(candidates) == 1:
                used_ids.add(candidates[0]["id"])
                matched_events += 1
            elif len(candidates) > 1:
                errors.append(
                    f"Ambiguous DFN match for event {event['event_id']}"
                )
            else:
                errors.append(
                    f"No DFN match for event {event['event_id']}"
                )
        if fracture_events and matched_events != len(catalog):
            errors.append(
                f"DFN catalog count {len(catalog)} != matched events {matched_events}"
            )
    elif fracture_events:
        errors.append("Fracture events exist but fractures_final.json is missing")

    native_rows = 0
    with (run_dir / "native_histories.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        for row in csv.DictReader(handle):
            float(row["value"])
            int(row["cycle"])
            native_rows += 1

    hash_errors = []
    for entry in result.get("files", []):
        path = run_dir / entry["path"]
        if not path.is_file():
            hash_errors.append(f"Missing file: {entry['path']}")
        elif path.stat().st_size != entry["size_bytes"]:
            hash_errors.append(f"Size mismatch: {entry['path']}")
        elif sha256_file(path) != entry["sha256"]:
            hash_errors.append(f"SHA-256 mismatch: {entry['path']}")

    capture = result.get("capture") or {}
    if result.get("status") != "COMPLETE":
        errors.append(f"Capture status is {result.get('status')}")
    if int(capture.get("frame_count", -1)) != len(index_rows):
        errors.append("result frame_count differs from frame index")
    if len(index_rows) < 2:
        errors.append("Fewer than two captured frames")
    if result.get("data_boundary") != "REAL_PFC":
        errors.append("Data boundary is not REAL_PFC")

    body = {
        "schema_version": 1,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "case_id": result.get("case_id"),
        "run_id": result.get("run_id"),
        "frames": len(index_rows),
        "cycle_start": index_rows[0]["cycle"] if index_rows else None,
        "cycle_end": index_rows[-1]["cycle"] if index_rows else None,
        "mechanical_time_run": capture.get("mechanical_time_run"),
        "ball_count_start": index_rows[0]["ball_count"] if index_rows else None,
        "ball_count_end": index_rows[-1]["ball_count"] if index_rows else None,
        "added_ball_count": len(added_ids),
        "added_ball_ids": added_ids,
        "removed_ball_count": len(removed_ids),
        "removed_ball_ids": removed_ids,
        "wall_vertex_rows": sum(wall_counts.values()),
        "native_history_rows": native_rows,
        "ball_velocity_rows": velocity_rows,
        "ball_spin_rows": spin_rows,
        "contact_rows": contact_rows,
        "fracture_events": len(fracture_events),
        "fracture_events_with_ball_endpoints": sum(
            1
            for event in fracture_events
            if event["ball_id_a"] > 0 and event["ball_id_b"] > 0
        ),
        "fracture_catalog": len(catalog),
        "matched_fracture_events": matched_events,
        "hash_errors": hash_errors,
        "all_ball_values_finite": not any("Non-finite" in error for error in errors),
        "strictly_increasing_cycles": not any("Cycle is not" in error for error in errors),
        "strictly_increasing_time": not any(
            "Mechanical Time is not" in error for error in errors
        ),
    }
    return body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--json-out")
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    report = validate(run_dir)
    if args.json_out:
        output = Path(args.json_out).resolve()
    else:
        output = run_dir / "metadata" / "validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
