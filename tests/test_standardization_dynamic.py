"""NPY/NPZ and dynamic entity tests.  NOT EXECUTED in the delivery task."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from standardize.legacy import load_legacy_case
from standardize import standardize_experiment


def write_case(root: Path, *, dimension: int = 3, with_ball_endpoints: bool = False) -> Path:
    case = root / "case_0"
    raw = case / "data" / "raw"
    raw.mkdir(parents=True)
    (case / "data" / "metadata").mkdir()
    z = [0.0, 1.0] if dimension == 2 else [0.0, 1.0, 2.0]
    static = {
        "dimension": dimension,
        "load_axis": "z",
        "wall_roles": {"top": 10, "bottom": 20},
        "balls": {
            "balls": [
                {"id": 1, "x": 0.0, "y": 0.0, "z": z[0], "radius": 0.5},
                {"id": 2, "x": 1.0, "y": 0.0, "z": z[0], "radius": 0.5},
            ]
        },
        "walls": {
            "walls": [
                {
                    "id": 10,
                    "name": "top",
                    "position": [0.0, 0.0, 10.0],
                    "vertices": [
                        {"id": 1, "position": [0.0, 0.0, 10.0]},
                        {"id": 2, "position": [1.0, 0.0, 10.0]},
                        {"id": 3, "position": [1.0, 1.0, 10.0]},
                        {"id": 4, "position": [0.0, 1.0, 10.0]},
                    ],
                },
                {
                    "id": 20,
                    "name": "bottom",
                    "position": [0.0, 0.0, 0.0],
                    "vertices": [
                        {"id": 1, "position": [0.0, 0.0, 0.0]},
                        {"id": 2, "position": [1.0, 0.0, 0.0]},
                        {"id": 3, "position": [1.0, 1.0, 0.0]},
                        {"id": 4, "position": [0.0, 1.0, 0.0]},
                    ],
                },
            ]
        },
    }
    (case / "data" / "static.json").write_text(json.dumps(static), encoding="utf-8")
    with (raw / "frame_index.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame_id", "cycle", "mechanical_time_total", "ball_count", "top_force_magnitude", "bottom_force_magnitude"])
        writer.writerow([1, 1, 0.0, 2, 2.0, 2.0])
        writer.writerow([2, 2, 0.01, 3, 3.0, 3.0])
        writer.writerow([3, 3, 0.02, 2, 4.0, 4.0])
    with (raw / "ball_frames.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame_id", "ball_id", "x", "y", "z", "radius"])
        writer.writerow([1, 1, 0.0, 0.0, 0.0, 0.5])
        writer.writerow([1, 2, 1.0, 0.0, 0.0, 0.5])
        writer.writerow([2, 1, 0.1, 0.0, 0.0, 0.5])
        writer.writerow([2, 2, 0.9, 0.0, 0.0, 0.5])
        writer.writerow([2, 3, 0.5, 0.2, 0.0, 0.3])
        writer.writerow([3, 1, 0.2, 0.0, 0.0, 0.5])
        writer.writerow([3, 3, 0.5, 0.2, 0.0, 0.3])
    with (raw / "wall_vertices.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame_id", "vertex_id", "x", "y", "z"])
        for frame in (1, 2, 3):
            for wall_z in (10.0 - frame * 0.1, 0.0):
                for vertex_id, x, y in ((1, 0, 0), (2, 1, 0), (3, 1, 1), (4, 0, 1)):
                    writer.writerow([frame, vertex_id, x, y, wall_z])
    with (raw / "fracture_events.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        header = ["event_id", "cycle", "mechanical_time_total", "contact_id"]
        if with_ball_endpoints:
            header.extend(["ball_id_a", "ball_id_b"])
        header.extend(["mode", "failure_strength", "x", "y", "z", "nx", "ny", "nz", "diameter"])
        writer.writerow(header)
        row = [1, 2, 0.01, 7]
        if with_ball_endpoints:
            row.extend([1, 2])
        row.extend([1, 3.0, 0.5, 0.2, 0.0, 0.0, 0.0, 1.0, 0.2])
        writer.writerow(row)
    (case / "data" / "metadata" / "result.json").write_text(
        json.dumps({"status": "COMPLETE", "case_id": 0, "run_id": "mock"}), encoding="utf-8"
    )
    (case / "data" / "metadata" / "validation.json").write_text(
        json.dumps({"status": "PASS"}), encoding="utf-8"
    )
    return case


class StandardizationTests(unittest.TestCase):
    def test_dynamic_ball_add_and_remove(self):
        with tempfile.TemporaryDirectory() as temp:
            case = load_legacy_case(write_case(Path(temp)))
            self.assertEqual([len(case["ball_frames"][i]) for i in (1, 2, 3)], [2, 3, 2])
            self.assertEqual(case["ball_frames"][2][-1]["id"], 3)
            self.assertNotIn(2, {row["id"] for row in case["ball_frames"][3]})

    def test_pfc2d_dimension_is_inferred(self):
        with tempfile.TemporaryDirectory() as temp:
            case = load_legacy_case(write_case(Path(temp), dimension=2))
            self.assertEqual(case["dimension"], 2)

    def test_radius_update_for_added_ball_is_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            case = load_legacy_case(write_case(Path(temp)))
            added = [row for row in case["ball_frames"][2] if row["id"] == 3][0]
            self.assertAlmostEqual(added["radius"], 0.3)

    def test_standardized_delivery_is_contract_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            case = write_case(root / "input")
            output = root / "standardized"
            experiment = standardize_experiment(
                case.parent,
                output,
                title="Contract Test",
                experiment_id="contract_test",
                execution_mode="OFFLINE",
                pfc_version="9.0",
            )
            manifest = json.loads(
                (output / "delivery_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["contract"]["name"], "pfc.standardized-experiment")
            self.assertEqual(manifest["contract"]["version"], "1.0.0")
            self.assertTrue(manifest["contract"]["immutable"])
            self.assertTrue(manifest["raw_input"]["read_only"])
            self.assertTrue(manifest["consumer_policy"]["analysis_output_must_be_separate"])
            self.assertEqual(manifest["producer"]["skill"], "pfc-headless")
            self.assertEqual(manifest["cases"][0]["case_id"], 0)
            self.assertEqual(
                experiment["experiment_id"],
                json.loads(
                    (output / "experiment.json").read_text(encoding="utf-8")
                )["experiment_id"],
            )

    def test_standardized_output_cannot_contain_raw_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            case = write_case(root / "input")
            with self.assertRaisesRegex(ValueError, "separate"):
                standardize_experiment(case.parent, root)

    def test_published_standardized_delivery_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            case = write_case(root / "input")
            output = root / "standardized"
            output.mkdir()
            (output / "existing.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "overwrite"):
                standardize_experiment(case.parent, output)

    def test_fracture_endpoint_ball_ids_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            case = write_case(
                root / "input", with_ball_endpoints=True
            )
            output = root / "standardized"
            standardize_experiment(
                case.parent,
                output,
                title="Endpoint Test",
                experiment_id="endpoint_test",
                execution_mode="OFFLINE",
                pfc_version="9.0",
            )
            with np.load(output / "cases" / "case_0" / "arrays.npz") as arrays:
                self.assertEqual(list(arrays["fracture_ball_id_a"]), [1])
                self.assertEqual(list(arrays["fracture_ball_id_b"]), [2])
            report = json.loads(
                (output / "cases" / "case_0" / "conversion_report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(report["fracture_endpoint_ids_status"], "REAL_PFC")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            case = write_case(root / "input")
            output = root / "standardized"
            standardize_experiment(
                case.parent,
                output,
                title="No Endpoint Test",
                experiment_id="no_endpoint_test",
                execution_mode="OFFLINE",
                pfc_version="9.0",
            )
            with np.load(output / "cases" / "case_0" / "arrays.npz") as arrays:
                self.assertNotIn("fracture_ball_id_a", arrays.files)
                self.assertNotIn("fracture_ball_id_b", arrays.files)
            report = json.loads(
                (output / "cases" / "case_0" / "conversion_report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                report["fracture_endpoint_ids_status"], "NOT_CAPTURED"
            )


if __name__ == "__main__":
    unittest.main()
