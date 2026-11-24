from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from pfc_headless.collection import (  # noqa: E402
    apply_plan_to_config,
    normalize_collection_plan,
)
from pfc_headless.common import HeadlessError  # noqa: E402
from pfc_headless.project import init_project  # noqa: E402


class CollectionPlanTests(unittest.TestCase):
    def test_plan_controls_contacts_history_and_events(self) -> None:
        plan = normalize_collection_plan(
            {
                "mode": "event",
                "interval": 1,
                "channels": [
                    {"id": "contact.id", "required": True},
                    {"id": "contact.endpoints"},
                    {"id": "history.load"},
                    {"id": "fracture.event"},
                ],
                "events": ["fracture"],
            },
            dimension=2,
        )
        config = apply_plan_to_config({}, plan)
        self.assertTrue(config["capture_contacts"])
        self.assertTrue(config["fracture_observer"])
        self.assertEqual(config["history_names"], ["load"])
        self.assertEqual(config["collection_plan"]["mode"], "event")

    def test_case_config_switches_seed_the_default_plan(self) -> None:
        plan = normalize_collection_plan(
            None,
            dimension=2,
            sampling={"mode": "cycle", "interval": 1},
            case_config={
                "capture_contacts": True,
                "fracture_observer": True,
                "history_names": ["load"],
            },
            seed_from_case=True,
        )
        config = apply_plan_to_config({}, plan)
        self.assertTrue(config["capture_contacts"])
        self.assertTrue(config["fracture_observer"])
        self.assertEqual(config["history_names"], ["load"])
        self.assertIn("fracture", plan["events"])
        self.assertIn("fracture.event", [item["id"] for item in plan["channels"]])

    def test_explicit_plan_still_wins_over_case_switches(self) -> None:
        plan = normalize_collection_plan(
            {
                "mode": "cycle",
                "interval": 1,
                "channels": [{"id": "ball.position"}],
                "events": [],
            },
            dimension=3,
            sampling={"mode": "cycle", "interval": 1},
            case_config={"capture_contacts": True, "fracture_observer": True},
            add_sampling_extras=False,
            seed_from_case=False,
        )
        config = apply_plan_to_config({}, plan)
        self.assertFalse(config["capture_contacts"])
        self.assertFalse(config["fracture_observer"])

    def test_required_unknown_channel_fails_closed(self) -> None:
        with self.assertRaises(HeadlessError):
            normalize_collection_plan(
                {
                    "mode": "cycle",
                    "interval": 1,
                    "channels": [{"id": "clump.membership", "required": True}],
                    "events": [],
                },
                dimension=3,
            )

    def test_missing_declared_source_file_stops_run_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "case.json"
            config.write_text(
                json.dumps(
                    {
                        "project_dir": str(root),
                        "source_files": {"missing.dat": "a" * 64},
                        "setup": [],
                        "solve": "model solve time 0.01",
                    }
                ),
                encoding="utf-8",
            )
            project = init_project(root / "project", name="Source project")
            case = project.add_case(config, dimension=2)
            with self.assertRaises(HeadlessError):
                project.new_run(case["case_id"], run_id="missing_source")


if __name__ == "__main__":
    unittest.main()
