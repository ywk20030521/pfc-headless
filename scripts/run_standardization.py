"""Create the immutable standardized-data contract from captured PFC data.

This entrypoint performs offline conversion only. It never starts PFC and never
modifies the captured input tree.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from standardize import standardize_experiment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Captured experiment root")
    parser.add_argument("--output", required=True, help="New standardized-delivery root")
    parser.add_argument("--title", default="PFC Standardized Experiment")
    parser.add_argument("--experiment-id")
    parser.add_argument(
        "--execution-mode",
        choices=["CONSOLE", "OFFLINE", "UNKNOWN"],
        default="CONSOLE",
    )
    parser.add_argument("--pfc-version")
    parser.add_argument(
        "--export-npy",
        action="store_true",
        help="Also write independent NPY arrays beside canonical NPZ arrays.",
    )
    parser.add_argument(
        "--fast-reader",
        action="store_true",
        help=(
            "Stream CSV rows through generators to lower peak memory. "
            "Output-identical to the default reader; off by default."
        ),
    )
    parser.add_argument(
        "--columnar",
        action="store_true",
        help=(
            "Read ball CSV straight into columnar arrays, skipping the "
            "ball_frames dict-of-dicts intermediate. Output-identical; off by default."
        ),
    )
    parser.add_argument(
        "--contact-memmap",
        action="store_true",
        help=(
            "Back contact arrays with disk memmaps so large contact sets "
            "do not occupy RAM during conversion. Output-identical; off by default."
        ),
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help=(
            "Choose reader strategy automatically from data scale and the "
            "memory budget. Overrides the individual reader flags."
        ),
    )
    parser.add_argument(
        "--memory-budget-mb",
        type=float,
        default=None,
        help="Memory budget in MB used by --auto (default: 512).",
    )
    args = parser.parse_args()
    input_root = Path(args.input).resolve()
    output_root = Path(args.output).resolve()
    experiment = standardize_experiment(
        input_root,
        output_root,
        title=args.title,
        experiment_id=args.experiment_id or output_root.name,
        execution_mode=args.execution_mode,
        pfc_version=args.pfc_version,
        export_npy=args.export_npy,
        fast_reader=args.fast_reader,
        columnar=args.columnar,
        contact_memmap=args.contact_memmap,
        auto=args.auto,
        memory_budget_mb=args.memory_budget_mb,
    )
    print(
        json.dumps(
            {
                "status": "GENERATED",
                "contract": "pfc.standardized-experiment@1.0.0",
                "output": str(output_root),
                "experiment_id": experiment["experiment_id"],
                "case_count": len(experiment["cases"]),
                "delivery_manifest": str(output_root / "delivery_manifest.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
