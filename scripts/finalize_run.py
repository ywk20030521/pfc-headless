from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import itasca

from capture_store import (
    atomic_write_json,
    canonical_json,
    choose_wall_roles,
    compact_run,
    read_json,
    sha256_bytes,
    utc_now,
    write_final_reports,
)


def vec(value: Any) -> list[float]:
    result = [float(item) for item in list(value)]
    if len(result) != 3 or not all(math.isfinite(item) for item in result):
        raise RuntimeError(f"Invalid vector from PFC: {value!r}")
    return result


def path_from_env() -> Path:
    explicit = os.environ.get("PFC_LIVE_CAPTURE_FINALIZE_CONFIG")
    if not explicit:
        raise FileNotFoundError(
            "PFC_LIVE_CAPTURE_FINALIZE_CONFIG is required"
        )
    return Path(explicit).resolve()


def write_native_histories(run_dir: Path, names: list[str]) -> dict[str, Any]:
    out_dir = run_dir / "histories"
    out_dir.mkdir(parents=True, exist_ok=True)
    definitions = []
    row_count = 0
    for name in names:
        try:
            array = itasca.history.get(str(name))
        except Exception as exc:
            definitions.append(
                {
                    "name": str(name),
                    "available": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        if len(array.shape) != 2 or array.shape[1] < 2:
            definitions.append(
                {
                    "name": str(name),
                    "available": False,
                    "error": f"Unexpected shape {array.shape}",
                }
            )
            continue
        rows = [[float(row[0]), float(row[1])] for row in array.tolist()]
        if not all(
            math.isfinite(value) for row in rows for value in row
        ):
            raise RuntimeError(f"History {name} contains non-finite values")
        path = out_dir / f"native_{name}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["cycle_or_step", "value"])
            writer.writerows(rows)
        row_count += len(rows)
        definitions.append(
            {
                "name": str(name),
                "available": True,
                "path": path.relative_to(run_dir).as_posix(),
                "rows": len(rows),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source": f"itasca.history.get('{name}')",
                "time_alignment": (
                    "first column is the native history abscissa; no value "
                    "was interpolated into capture frames"
                ),
            }
        )
    payload = {
        "schema_version": 1,
        "data_boundary": "REAL_PFC",
        "generated_utc": utc_now(),
        "histories": definitions,
        "total_rows": row_count,
    }
    atomic_write_json(out_dir / "history_definitions.json", payload)
    return payload


def read_fractures(run_dir: Path) -> list[dict[str, Any]]:
    static = read_json(run_dir / "static" / "model.json")
    baseline_ids = {
        int(row["id"]) for row in static.get("baseline_fractures", [])
    }
    rows = []
    for fracture in itasca.dfn.fracture.list():
        fracture_id = int(fracture.id())
        if fracture_id in baseline_ids:
            continue
        props = fracture.props()
        rows.append(
            {
                "id": fracture_id,
                "dfn_name": str(fracture.dfn().name()),
                "position": vec(fracture.pos()),
                "normal": vec(fracture.normal()),
                "diameter": float(fracture.diameter()),
                "dip": float(fracture.dip()),
                "dipdir": float(fracture.dipdir()),
                "area": float(fracture.area()),
                "age": float(props.get("age")),
                "failure_strength": float(props.get("failure_strength")),
                "props": {
                    key: value
                    for key, value in props.items()
                    if isinstance(value, (int, float, str, bool))
                },
            }
        )
    rows.sort(key=lambda row: row["id"])
    return rows


def _optional_int(value: Any, default: int = -1) -> int:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        return default


def event_key(row: dict[str, Any]) -> str:
    return sha256_bytes(
        canonical_json(
            {
                "cycle": row["cycle"],
                "mechanical_time_total": row["mechanical_time_total"],
                "contact_id": row["contact_id"],
                "ball_id_a": row.get("ball_id_a", -1),
                "ball_id_b": row.get("ball_id_b", -1),
                "mode": row["mode"],
                "failure_strength": row["failure_strength"],
                "position": row["position"],
                "normal": row["normal"],
                "diameter": row["diameter"],
            }
        )
    )


def parse_raw_events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "recovery" / "raw" / "bond_spool.csv"
    if not path.is_file():
        return []
    payload = path.read_bytes()
    if payload and not payload.endswith(b"\n"):
        payload = payload[: payload.rfind(b"\n") + 1]
    rows = []
    for row in csv.DictReader(payload.decode("utf-8").splitlines()):
        item = {
            "event_id": int(row["event_id"]),
            "cycle": int(row["cycle"]),
            "mechanical_time_total": float(row["mechanical_time_total"]),
            "contact_id": _optional_int(row.get("contact_id")),
            "ball_id_a": _optional_int(row.get("ball_id_a")),
            "ball_id_b": _optional_int(row.get("ball_id_b")),
            "mode": int(row["mode"]),
            "failure_strength": float(row["failure_strength"]),
            "position": [float(row["x"]), float(row["y"]), float(row["z"])],
            "normal": [float(row["nx"]), float(row["ny"]), float(row["nz"])],
            "diameter": float(row["diameter"]),
        }
        for value in (
            item["mechanical_time_total"],
            item["failure_strength"],
            item["diameter"],
            *item["position"],
            *item["normal"],
        ):
            if not math.isfinite(value):
                raise RuntimeError("Non-finite fracture event value")
        item["event_key"] = event_key(item)
        rows.append(item)
    unique = {}
    for row in rows:
        unique.setdefault(row["event_key"], row)
    return sorted(unique.values(), key=lambda row: (row["cycle"], row["event_id"]))


def match_fractures(
    run_dir: Path, events: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fractures = read_fractures(run_dir)
    matched = []
    errors = []
    used_ids = set()

    def close(left: float, right: float, tolerance: float) -> bool:
        return abs(float(left) - float(right)) <= tolerance * max(
            1.0, abs(float(left)), abs(float(right))
        )

    for event in events:
        label = "tension" if event["mode"] == 1 else "shear"
        preferred = [
            row for row in fractures if label in row["dfn_name"].lower()
        ]
        candidates = [
            row
            for row in (preferred or fractures)
            if int(row["id"]) not in used_ids
            and all(
                close(left, right, 1.0e-9)
                for left, right in zip(
                    event["position"], row["position"]
                )
            )
            and close(event["diameter"], row["diameter"], 1.0e-9)
            and close(
                event["mechanical_time_total"], row["age"], 1.0e-9
            )
            and close(
                event["failure_strength"],
                row["failure_strength"],
                1.0e-9,
            )
        ]
        if len(candidates) != 1:
            errors.append(
                {
                    "event_id": event["event_id"],
                    "event_key": event["event_key"],
                    "candidate_fracture_ids": [
                        row["id"] for row in candidates
                    ],
                    "reason": (
                        "ZERO_MATCH"
                        if not candidates
                        else "AMBIGUOUS_MATCH"
                    ),
                }
            )
            continue
        fracture = candidates[0]
        used_ids.add(int(fracture["id"]))
        matched.append(
            {
                **event,
                "fracture_id": int(fracture["id"]),
                "dfn_name": fracture["dfn_name"],
                "fracture_position": fracture["position"],
                "dip": fracture["dip"],
                "dipdir": fracture["dipdir"],
                "area": fracture["area"],
                "age": fracture["age"],
                "fracture_props": fracture["props"],
                "creation_cycle": event["cycle"],
                "creation_time": event["mechanical_time_total"],
                "creation_source": (
                    "FISH bond_break callback: mech.cycle(), mech.time.total()"
                ),
                "association": "EXACT_UNIQUE_DFN_MATCH",
            }
        )
    unmatched_dfns = [
        row for row in fractures if int(row["id"]) not in used_ids
    ]
    report = {
        "status": "PASS" if not errors and not unmatched_dfns else "FAIL",
        "raw_unique_event_count": len(events),
        "fracture_delta_count": len(fractures),
        "matched_event_count": len(matched),
        "errors": errors,
        "unmatched_dfn_ids": [row["id"] for row in unmatched_dfns],
        "rule": (
            "mode, position, diameter, creation mechanical time and failure "
            "strength must produce exactly one unused DFN fracture"
        ),
    }
    return matched, report


def write_events(
    run_dir: Path,
    events: list[dict[str, Any]],
    matched: list[dict[str, Any]],
    report: dict[str, Any],
) -> None:
    out = run_dir / "events"
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        ("fracture_events.jsonl", events),
        ("matched_fractures.jsonl", matched),
    ):
        path = out / name
        payload = b"".join(canonical_json(row) + b"\n" for row in rows)
        path.write_bytes(payload)
    atomic_write_json(out / "fracture_match_report.json", report)


def write_frame_metrics(
    run_dir: Path, parsed: dict[str, Any], static: dict[str, Any]
) -> str:
    walls = static["walls"]
    roles = choose_wall_roles(walls)
    if "top" not in roles or "bottom" not in roles:
        raise RuntimeError("Cannot determine top/bottom Wall roles")
    top_static = next(row for row in walls if row["id"] == roles["top"])
    bottom_static = next(row for row in walls if row["id"] == roles["bottom"])
    x = [row["position"][0] for row in top_static["vertices"]]
    y = [row["position"][1] for row in top_static["vertices"]]
    area = (max(x) - min(x)) * (max(y) - min(y))
    height0 = top_static["position"][2] - bottom_static["position"][2]
    if area <= 0.0 or height0 <= 0.0:
        raise RuntimeError("Invalid static sample area or height")
    rows = []
    for meta in parsed["frames"]:
        frame_id = meta["frame_id"]
        wall_by_id = {
            row["id"]: row for row in parsed["walls"][frame_id]
        }
        top = wall_by_id[roles["top"]]
        bottom = wall_by_id[roles["bottom"]]
        height = top["position"][2] - bottom["position"][2]
        displacement = height0 - height
        strain = displacement / height0
        top_force = math.sqrt(
            sum(value * value for value in top["force_contact"])
        )
        bottom_force = math.sqrt(
            sum(value * value for value in bottom["force_contact"])
        )
        load = 0.5 * (top_force + bottom_force)
        stress = load / area
        rows.append(
            [
                frame_id,
                meta["cycle"],
                meta["mechanical_time_total"],
                height,
                displacement,
                strain,
                top_force,
                bottom_force,
                load,
                stress,
                stress / 1.0e6,
                meta["capture_elapsed_ms"],
                meta["write_elapsed_ms"],
            ]
        )
    path = run_dir / "histories" / "frame_metrics.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "frame_id",
                "cycle",
                "mechanical_time_total",
                "height_m",
                "displacement_m_compression_positive",
                "strain_engineering_compression_positive",
                "top_force_contact_magnitude_n",
                "bottom_force_contact_magnitude_n",
                "load_n",
                "stress_pa_engineering",
                "stress_mpa_engineering",
                "capture_elapsed_ms",
                "write_elapsed_ms",
            ]
        )
        writer.writerows(rows)
    atomic_write_json(
        run_dir / "histories" / "derived_field_definitions.json",
        {
            "stress": {
                "kind": "DERIVED_ENGINEERING_AXIAL_STRESS",
                "formula": "0.5*(|F_top|+|F_bottom|)/A0",
                "raw_fields": [
                    "wall.force.contact(top)",
                    "wall.force.contact(bottom)",
                    "static top Wall initial xy extent",
                ],
                "unit": "Pa",
                "sign": "compression-positive",
                "area_m2": area,
            },
            "strain": {
                "kind": "DERIVED_ENGINEERING_AXIAL_STRAIN",
                "formula": "(H0-H)/H0",
                "raw_fields": [
                    "top Wall z position",
                    "bottom Wall z position",
                ],
                "sign": "compression-positive",
                "height0_m": height0,
            },
            "load": {
                "kind": "DERIVED_WALL_CONTACT_FORCE_MEAN",
                "formula": "0.5*(|F_top|+|F_bottom|)",
                "unit": "N",
            },
            "displacement": {
                "kind": "DERIVED_PLATEN_SHORTENING",
                "formula": "H0-H",
                "unit": "m",
            },
            "boundary": (
                "These are engineering quantities derived from measured Wall "
                "force and position; they are not claimed to be native PFC "
                "homogenized tensors."
            ),
        },
    )
    return path.relative_to(run_dir).as_posix()


def main() -> int:
    config = read_json(path_from_env())
    run_dir = Path(config["run_dir"]).resolve()
    status = str(config.get("status", "COMPLETE"))
    compact = compact_run(
        run_dir,
        chunk_frames=int(config.get("chunk_frames", 10)),
        float32_abs_tol=float(config.get("float32_abs_tol", 1.0e-6)),
        float32_rel_tol=float(config.get("float32_rel_tol", 1.0e-5)),
    )
    static = read_json(run_dir / "static" / "model.json")
    native = write_native_histories(
        run_dir, [str(value) for value in config.get("history_names", ["1", "2", "3"])]
    )
    raw_events = parse_raw_events(run_dir)
    matched, fracture_report = match_fractures(run_dir, raw_events)
    write_events(run_dir, raw_events, matched, fracture_report)
    legacy_analysis = bool(config.get("allow_legacy_analysis", False))
    metrics_path = (
        write_frame_metrics(run_dir, compact["parsed"], static)
        if legacy_analysis
        else None
    )
    additional = {
        "native_histories": native,
        "fracture_match": fracture_report,
        "frame_metrics": metrics_path,
        "legacy_analysis": legacy_analysis,
        "float32_precision": compact["float32_precision"],
        "ball_id_changes": compact["ball_id_changes"],
        "ball_radius_changes": compact["ball_radius_changes"],
        "raw_tail_rejections": compact["raw_tails"],
        "incomplete_frame_rows": compact["incomplete_frame_rows"],
    }
    final_status = (
        "COMPLETE" if status in {"COMPLETE", "INTERRUPTED"} else status
    )
    final_reason = str(config.get("reason", "solve_complete"))
    if fracture_report["status"] != "PASS":
        final_status = "INCOMPLETE"
        final_reason = "fracture relationship failed zero/ambiguous uniqueness"
    manifest = write_final_reports(
        run_dir,
        status=final_status,
        reason=final_reason,
        run_id=str(config["run_id"]),
        pid=int(config["pid"]),
        sample_mode=str(config.get("sample_mode", "cycle")),
        sample_value=float(config.get("sample_value", 1000)),
        additional_events=additional,
    )
    result = {
        "status": final_status,
        "run_dir": str(run_dir),
        "run_id": str(config["run_id"]),
        "pid": int(config["pid"]),
        "frames": compact["frames"],
        "blocks": compact["blocks"],
        "float32_precision": compact["float32_precision"],
        "fracture_report": fracture_report,
        "native_histories": native,
        "frame_metrics": metrics_path,
        "manifest": manifest,
    }
    atomic_write_json(run_dir / "metadata" / "finalize_result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if final_status != "INCOMPLETE" else 1


if __name__ == "__main__":
    _result = main()
    if _result:
        raise RuntimeError(f"finalize_run failed with status {_result}")

