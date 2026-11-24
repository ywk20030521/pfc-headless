from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a PFC-live-capture tracked-task entry directory."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-root", required=True)
    args = parser.parse_args()

    source_config = Path(args.config).resolve()
    run_root = Path(args.run_root).resolve()
    if run_root.exists():
        raise FileExistsError(f"Refusing to overwrite run root: {run_root}")

    config = json.loads(source_config.read_text(encoding="utf-8"))
    entry_dir = run_root / "entry"
    data_dir = run_root / "data"
    entry_dir.mkdir(parents=True)

    target_config = dict(config)
    target_config["run_dir"] = str(data_dir)
    (entry_dir / "capture_config.json").write_text(
        json.dumps(target_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(SCRIPT_DIR / "capture_case.py", entry_dir / "capture_case.py")

    launch = {
        "entry_script": str(entry_dir / "capture_case.py"),
        "config": str(entry_dir / "capture_config.json"),
        "data_dir": str(data_dir),
        "tracked_task_submit": {
            "entry_script": str(entry_dir / "capture_case.py"),
            "description": (
                f"PFC live capture case {target_config.get('case_id')} "
                f"{target_config.get('run_id')}"
            ),
        },
    }
    (run_root / "launch.json").write_text(
        json.dumps(launch, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(launch, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
