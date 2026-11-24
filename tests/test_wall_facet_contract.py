"""Wall facet topology contract: PFC3D real faces need facet->vertex IDs."""
from __future__ import annotations

import unittest

from standardize.converter import _wall_facet_arrays
from standardize.legacy import _static_walls


class WallFacetContractTest(unittest.TestCase):
    def test_facet_arrays_export_vertex_topology(self):
        walls = [{
            "id": 101,
            "name": "bottom",
            "position": [0, 0, -0.5],
            "vertices": [
                {"id": 1, "position": [-1, -1, -0.5]},
                {"id": 2, "position": [1, -1, -0.5]},
                {"id": 3, "position": [-1, 1, -0.5]},
                {"id": 4, "position": [1, 1, -0.5]},
            ],
            "facets": [
                {"id": 1, "active": 1, "position": [-0.33, -0.33, -0.5],
                 "normal": [0, 0, 1], "vertex_ids": [1, 2, 3]},
                {"id": 2, "active": 1, "position": [0.33, 0.33, -0.5],
                 "normal": [0, 0, 1], "vertex_ids": [3, 2, 4]},
            ],
        }]
        arrays = _wall_facet_arrays(walls)
        self.assertEqual(list(arrays["wall_facet_id"]), [1, 2])
        self.assertEqual(list(arrays["wall_facet_wall_id"]), [101, 101])
        self.assertEqual(list(arrays["wall_facet_vertex_offsets"]), [0, 3, 6])
        self.assertEqual(list(arrays["wall_facet_vertex_ids"]), [1, 2, 3, 3, 2, 4])
        self.assertEqual(arrays["wall_facet_normal"].shape, (2, 3))

    def test_facet_arrays_empty_for_2d_or_old_delivery(self):
        arrays = _wall_facet_arrays([{"id": 1, "name": "w", "position": [0, 0, 0],
                                      "vertices": [], "facets": []}])
        self.assertEqual(len(arrays["wall_facet_id"]), 0)
        self.assertEqual(list(arrays["wall_facet_vertex_offsets"]), [0])

    def test_legacy_static_walls_preserve_facet_vertex_ids(self):
        static = {"walls": {"walls": [{
            "id": 101, "name": "bottom", "position": [0, 0, -0.5],
            "vertices": [{"id": 1, "position": [0, 0, -0.5]}],
            "facets": [
                {"id": 1, "active": 1, "position": [0, 0, -0.5],
                 "normal": [0, 0, 1], "vertex_ids": [1, 2, 3]},
            ],
        }]}}
        walls = _static_walls(static)
        self.assertEqual(walls[0]["facets"][0]["vertex_ids"], [1, 2, 3])
        self.assertEqual(walls[0]["facets"][0]["normal"], [0.0, 0.0, 1.0])


if __name__ == "__main__":
    unittest.main()
