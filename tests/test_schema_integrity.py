"""Schema and data-contract tests.  NOT EXECUTED in the delivery task."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from schema import (
    CHANNEL_SOURCES,
    make_case,
    make_channel,
    make_experiment,
    make_provenance,
    validate_experiment,
)


class SchemaTests(unittest.TestCase):
    def test_schema_required_dimensions_and_sources(self):
        channel = make_channel(
            "ball_position",
            entity_type="ball",
            variable="position",
            unit="m",
            source="REAL_PFC",
        )
        case = make_case(
            0,
            label="Case 0",
            run_id="mock_case",
            dimension=2,
            source_format="mock",
            frame_count=3,
            arrays_path="case_0/arrays.npz",
            channels=[channel],
        )
        experiment = make_experiment(
            experiment_id="mock",
            title="Mock schema",
            pfc_version="9.0",
            execution_mode="OFFLINE",
            dimensions=[2],
            cases=[case],
            data_boundary="MOCK",
        )
        validate_experiment(experiment)
        self.assertTrue({"REAL_PFC", "DERIVED"} <= CHANNEL_SOURCES)

    def test_missing_data_is_not_zero_source(self):
        channel = make_channel(
            "contact_force",
            entity_type="contact",
            variable="force",
            unit="N",
            source="NOT_CAPTURED",
            status="NOT_CAPTURED",
        )
        self.assertEqual(channel["source"], "NOT_CAPTURED")
        self.assertEqual(channel["status"], "NOT_CAPTURED")

    def test_pfc2d_and_pfc3d_cases_coexist(self):
        common = dict(
            label="mock",
            run_id="mock",
            source_format="mock",
            frame_count=2,
            channels=[],
        )
        case2 = make_case(0, dimension=2, arrays_path="a.npz", **common)
        case3 = make_case(1, dimension=3, arrays_path="b.npz", **common)
        experiment = make_experiment(
            experiment_id="mixed",
            title="Mixed dimensions",
            pfc_version=None,
            execution_mode="OFFLINE",
            dimensions=[2, 3],
            cases=[case2, case3],
            data_boundary="MOCK",
        )
        self.assertEqual(experiment["dimensions"], [2, 3])

    def test_npz_offsets_are_variable_length(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "case_0" / "arrays.npz"
            path.parent.mkdir()
            np.savez_compressed(
                path,
                cycle=np.asarray([1, 2]),
                mechanical_time_total=np.asarray([0.1, 0.2]),
                frame_offsets=np.asarray([0, 2, 3]),
                ball_id=np.asarray([1, 2, 1]),
            )
            case = make_case(
                0,
                label="Case 0",
                run_id="mock",
                dimension=2,
                source_format="mock",
                frame_count=2,
                arrays_path=str(path),
                channels=[],
            )
            experiment = make_experiment(
                experiment_id="mock",
                title="Mock",
                pfc_version=None,
                execution_mode="OFFLINE",
                dimensions=[2],
                cases=[case],
                data_boundary="MOCK",
            )
            validate_experiment(experiment, arrays_loader=lambda _: np.load(path))

    def test_provenance_keeps_hash_unknown_as_not_invented(self):
        provenance = make_provenance(
            source="REAL_PFC",
            input_files=[{"path": "mock.csv"}],
            formula=None,
        )
        self.assertIsNone(provenance["input_files"][0]["sha256"])


if __name__ == "__main__":
    unittest.main()
