from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from capture_store import (
    atomic_write_json,
    choose_wall_roles,
    compact_run,
    read_json,
    utc_now,
    write_final_reports,
)


def write_metrics(
    run_dir: Path,
    parsed: dict[str, Any],
    static: dict[str, Any],
) -> Path:
    walls = static["walls"]
    roles = choose_wall_roles(walls)
    top_static = next(row for row in walls if row["id"] == roles["top"])
    bottom_static = next(row for row in walls if row["id"] == roles["bottom"])
    xs = [row["position"][0] for row in top_static["vertices"]]
    ys = [row["position"][1] for row in top_static["vertices"]]
    area = (max(xs) - min(xs)) * (max(ys) - min(ys))
    h0 = top_static["position"][2] - bottom_static["position"][2]
    path = run_dir / "histories" / "frame_metrics.csv"
    rows = []
    for meta in parsed["frames"]:
        by_id = {
            row["id"]: row for row in parsed["walls"][meta["frame_id"]]
        }
        height = by_id[roles["top"]]["position"][2] - by_id[roles["bottom"]][
            "position"
        ][2]
        displacement = h0 - height
        top_force = math.sqrt(
            sum(
                value * value
                for value in by_id[roles["top"]]["force_contact"]
            )
        )
        bottom_force = math.sqrt(
            sum(
                value * value
                for value in by_id[roles["bottom"]]["force_contact"]
            )
        )
        load = 0.5 * (top_force + bottom_force)
        stress = load / area
        rows.append(
            [
                meta["frame_id"],
                meta["cycle"],
                meta["mechanical_time_total"],
                height,
                displacement,
                displacement / h0,
                top_force,
                bottom_force,
                load,
                stress,
                stress / 1.0e6,
                meta["capture_elapsed_ms"],
                meta["write_elapsed_ms"],
            ]
        )
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
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--chunk-frames", type=int, default=10)
    parser.add_argument("--reason", default="external complete-block recovery")
    parser.add_argument("--allow-legacy-analysis", action="store_true")
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    static = read_json(run_dir / "static" / "model.json")
    state_path = run_dir / "metadata" / "recovery_state.json"
    transitions = []

    def transition(state: str, reason: str) -> None:
        transitions.append(
            {
                "time_utc": utc_now(),
                "state": state,
                "reason": reason,
                "run_id": static.get("run_id"),
                "pid": static.get("pid"),
                "cycle": None,
                "mechanical_time_total": None,
                "bridge": {"reachable": False},
                "task_id": None,
            }
        )
        atomic_write_json(
            state_path,
            {
                "run_id": static.get("run_id"),
                "pid": static.get("pid"),
                "state": state,
                "transitions": transitions,
            },
        )

    transition("INTERRUPTED", args.reason)
    transition("RECOVERING", "scan complete raw rows and committed blocks")
    try:
        compact = compact_run(
            run_dir,
            chunk_frames=int(args.chunk_frames),
        )
        metrics = (
            write_metrics(run_dir, compact["parsed"], static)
            if args.allow_legacy_analysis
            else None
        )
        bond_path = run_dir / "recovery" / "raw" / "bond_spool.csv"
        bond_rows = 0
        if bond_path.is_file():
            payload = bond_path.read_bytes()
            if payload and not payload.endswith(b"\n"):
                payload = payload[: payload.rfind(b"\n") + 1]
            bond_rows = max(0, len(payload.decode("utf-8").splitlines()) - 1)
        matched = run_dir / "events" / "matched_fractures.jsonl"
        matched_rows = 0
        if matched.is_file():
            matched_rows = sum(
                1
                for line in matched.read_text(encoding="utf-8").splitlines()
                if line
            )
        complete = compact["frames"] >= 2 and (
            bond_rows == 0 or matched_rows == bond_rows
        )
        status = (
            "READY_FOR_VISUALIZATION" if complete else "INCOMPLETE"
        )
        write_final_reports(
            run_dir,
            status=status,
            reason=args.reason,
            run_id=str(static["run_id"]),
            pid=int(static["pid"]),
            sample_mode=str(
                static.get("capture_config", {}).get("sample_mode", "cycle")
            ),
            sample_value=float(
                static.get("capture_config", {}).get("sample_value", 1000)
            ),
            additional_events={
                "external_recovery": True,
                "frames": compact["frames"],
                "blocks": compact["blocks"],
                "fracture_events": bond_rows,
                "matched_fracture_events": matched_rows,
                "frame_metrics": (
                    metrics.relative_to(run_dir).as_posix()
                    if metrics is not None
                    else None
                ),
                "legacy_analysis": bool(args.allow_legacy_analysis),
                "float32_precision": compact["float32_precision"],
                "ball_id_changes": compact["ball_id_changes"],
                "ball_radius_changes": compact["ball_radius_changes"],
                "raw_tail_rejections": compact["raw_tails"],
                "incomplete_frame_rows": compact["incomplete_frame_rows"],
            },
        )
        transition(status, "recovery scan completed")
        result = {
            "status": status,
            "run_dir": str(run_dir),
            "frames": compact["frames"],
            "blocks": compact["blocks"],
            "fracture_events": bond_rows,
            "matched_fracture_events": matched_rows,
            "raw_tail_rejections": compact["raw_tails"],
            "float32_precision": compact["float32_precision"],
            "viewer_generated": False,
        }
    except BaseException as exc:
        transition("INCOMPLETE", f"{type(exc).__name__}: {exc}")
        result = {
            "status": "INCOMPLETE",
            "run_dir": str(run_dir),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "viewer_generated": False,
        }
    atomic_write_json(run_dir / "metadata" / "recovery_result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "READY_FOR_VISUALIZATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())

