from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from capture_store import (  # noqa: E402
    CaptureIntegrityError,
    compact_run,
    initialize_raw_spools,
    initialize_run_dirs,
    iter_committed_frames,
    recover_blocks,
)


class CaptureStoreTests(unittest.TestCase):
    def make_run(self, root: Path) -> Path:
        run = root / "run"
        initialize_run_dirs(run)
        initialize_raw_spools(run)
        static = {
            "schema_version": 1,
            "run_id": "unit-run",
            "pid": 100,
            "snapshot": {"cycle": 10, "mechanical_time_total": 1.0},
            "model_identity": {"sha256": "unit"},
            "balls": [
                {"id": 1, "x": 0.1, "y": 0.2, "z": 0.3, "radius": 0.25},
                {"id": 2, "x": 0.4, "y": 0.5, "z": 0.6, "radius": 0.3},
            ],
            "walls": [
                {
                    "id": 1,
                    "name": "top",
                    "position": [0.0, 0.0, 2.0],
                    "vertices": [
                        {"id": 1, "position": [-1.0, -1.0, 2.0]},
                        {"id": 2, "position": [1.0, -1.0, 2.0]},
                        {"id": 3, "position": [1.0, 1.0, 2.0]},
                        {"id": 4, "position": [-1.0, 1.0, 2.0]},
                    ],
                },
                {
                    "id": 2,
                    "name": "bottom",
                    "position": [0.0, 0.0, -2.0],
                    "vertices": [
                        {"id": 5, "position": [-1.0, -1.0, -2.0]},
                        {"id": 6, "position": [1.0, -1.0, -2.0]},
                        {"id": 7, "position": [1.0, 1.0, -2.0]},
                        {"id": 8, "position": [-1.0, 1.0, -2.0]},
                    ],
                },
            ],
            "baseline_fractures": [],
        }
        (run / "static" / "model.json").write_text(
            json.dumps(static), encoding="utf-8"
        )
        (run / "static" / "manifest.json").write_text(
            json.dumps({"bundle_sha256": "unit-bundle"}), encoding="utf-8"
        )
        frame_rows = [
            [1, 10, 1.0, 2, 2, 8, 1.0, 2.0, 0, 1, "OK", "START"],
            [2, 11, 1.1, 2, 2, 8, 1.1, 2.1, 1, 1, "OK", "INTERVAL"],
            [3, 12, 1.2, 1, 2, 8, 1.2, 2.2, 2, 1, "OK", "FINAL"],
        ]
        with (run / "recovery" / "raw" / "frame_spool.csv").open(
            "a", encoding="utf-8", newline=""
        ) as handle:
            csv.writer(handle, lineterminator="\n").writerows(frame_rows)
        ball_rows = [
            [1, 1, 0.1, 0.2, 0.3, 0.25],
            [1, 2, 0.4, 0.5, 0.6, 0.3],
            [2, 1, 0.11, 0.2, 0.3, 0.25],
            [2, 2, 0.4, 0.51, 0.6, 0.3],
            [3, 1, 0.12, 0.2, 0.3, 0.25],
        ]
        with (run / "recovery" / "raw" / "ball_spool.csv").open(
            "a", encoding="utf-8", newline=""
        ) as handle:
            csv.writer(handle, lineterminator="\n").writerows(ball_rows)
        for frame_id in (1, 2, 3):
            wall_rows = []
            vertex_rows = []
            for wall_id in (1, 2):
                z = 2.0 if wall_id == 1 else -2.0
                wall_rows.append(
                    [
                        frame_id,
                        wall_id,
                        0,
                        0,
                        z,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        100.0,
                        8,
                    ]
                )
            for vertex_id in range(1, 9):
                z = 2.0 if vertex_id <= 4 else -2.0
                vertex_rows.append(
                    [frame_id, vertex_id, 0.0, 0.0, z]
                )
            with (run / "recovery" / "raw" / "wall_spool.csv").open(
                "a", encoding="utf-8", newline=""
            ) as handle:
                csv.writer(handle, lineterminator="\n").writerows(wall_rows)
            with (
                run / "recovery" / "raw" / "wall_vertex_spool.csv"
            ).open("a", encoding="utf-8", newline="") as handle:
                csv.writer(handle, lineterminator="\n").writerows(
                    vertex_rows
                )
        return run

    def test_compact_and_independent_readback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = self.make_run(Path(temporary))
            result = compact_run(run, chunk_frames=2)
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["frames"], 3)
            self.assertEqual(result["blocks"]["valid_block_count"], 2)
            frames = list(iter_committed_frames(run))
            self.assertEqual([row["header"]["cycle"] for row in frames], [10, 11, 12])
            self.assertIsNotNone(frames[0]["radii"])
            self.assertIsNone(frames[1]["radii"])
            self.assertTrue(frames[-1]["header"]["flags"] & 2)
            self.assertLess(result["float32_precision"]["max_abs_error"], 1e-6)

    def test_incomplete_tail_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = self.make_run(Path(temporary))
            compact_run(run, chunk_frames=2)
            with (run / "recovery" / "raw" / "frame_spool.csv").open(
                "ab"
            ) as handle:
                handle.write(b"4,13,1.3")
            result = compact_run(run, chunk_frames=2)
            self.assertEqual(result["frames"], 3)
            self.assertEqual(
                result["raw_tails"][0]["rejected_tail_bytes"], 8
            )

    def test_corrupt_tail_block_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = self.make_run(Path(temporary))
            compact_run(run, chunk_frames=2)
            block = sorted((run / "frames" / "blocks").glob("block-*"))[-1]
            binary = block / "ball_frames.bin"
            payload = bytearray(binary.read_bytes())
            payload[-1] ^= 0xFF
            binary.write_bytes(payload)
            recovered = recover_blocks(run)
            self.assertEqual(recovered["status"], "INVALID_TAIL_REJECTED")
            self.assertEqual(recovered["valid_block_count"], 1)
            self.assertEqual(recovered["invalid_tail_count"], 1)

    def test_float32_tolerance_gate_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = self.make_run(Path(temporary))
            with self.assertRaises(CaptureIntegrityError):
                compact_run(
                    run,
                    chunk_frames=2,
                    float32_abs_tol=1.0e-20,
                    float32_rel_tol=1.0e-20,
                )

    def test_added_ball_radius_is_stored_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = self.make_run(Path(temporary))
            frames_path = run / "recovery" / "raw" / "frame_spool.csv"
            with frames_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
            rows[3][-1] = "INTERVAL"
            rows.append(
                [4, 13, 1.3, 2, 2, 8, 1.3, 2.3, 3, 1, "OK", "FINAL"]
            )
            with frames_path.open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle, lineterminator="\n").writerows(rows)
            with (
                run / "recovery" / "raw" / "ball_spool.csv"
            ).open("a", encoding="utf-8", newline="") as handle:
                csv.writer(handle, lineterminator="\n").writerows(
                    [
                        [4, 1, 0.13, 0.2, 0.3, 0.25],
                        [4, 3, 0.8, 0.9, 1.0, 0.27],
                    ]
                )
            for frame_id in (4,):
                with (
                    run / "recovery" / "raw" / "wall_spool.csv"
                ).open("a", encoding="utf-8", newline="") as handle:
                    csv.writer(handle, lineterminator="\n").writerows(
                        [
                            [frame_id, 1, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100, 8],
                            [frame_id, 2, 0, 0, -2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100, 8],
                        ]
                    )
                with (
                    run / "recovery" / "raw" / "wall_vertex_spool.csv"
                ).open("a", encoding="utf-8", newline="") as handle:
                    csv.writer(handle, lineterminator="\n").writerows(
                        [
                            [frame_id, vertex_id, 0, 0, 2 if vertex_id <= 4 else -2]
                            for vertex_id in range(1, 9)
                        ]
                    )
            result = compact_run(run, chunk_frames=4)
            frames = list(iter_committed_frames(run))
            self.assertIsNone(frames[1]["radii"])
            self.assertIsNotNone(frames[3]["radii"])
            radii = dict(zip(frames[3]["ids"], frames[3]["radii"]))
            self.assertAlmostEqual(radii[1], 0.25, places=7)
            self.assertAlmostEqual(radii[3], 0.27, places=7)
            self.assertEqual(
                result["ball_id_changes"][-1]["added_radius"], {"3": 0.27}
            )

    def test_orphan_frame_rows_are_rejected_together(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = self.make_run(Path(temporary))
            with (
                run / "recovery" / "raw" / "ball_spool.csv"
            ).open("a", encoding="utf-8", newline="") as handle:
                csv.writer(handle, lineterminator="\n").writerow(
                    [4, 1, 0.2, 0.2, 0.2, 0.25]
                )
            with (
                run / "recovery" / "raw" / "wall_spool.csv"
            ).open("a", encoding="utf-8", newline="") as handle:
                csv.writer(handle, lineterminator="\n").writerow(
                    [4, 1, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100, 8]
                )
            result = compact_run(run, chunk_frames=2)
            self.assertEqual(result["frames"], 3)
            self.assertEqual(
                result["incomplete_frame_rows"],
                {"balls": 1, "walls": 1},
            )


if __name__ == "__main__":
    unittest.main()

