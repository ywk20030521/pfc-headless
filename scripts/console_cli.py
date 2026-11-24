"""CLI for Console-only runtime inspection and lifecycle control."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from console_runtime import ConsoleRuntime, engine_environment_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "health", "stop"):
        item = sub.add_parser(name)
        item.add_argument("--workdir", required=True)
        item.add_argument("--dimension", type=int, choices=[2, 3], default=2)
        item.add_argument("--port", type=int, default=9001)
        item.add_argument("--engine")
        if name == "stop":
            item.add_argument("--save-name")
            item.add_argument("--allow-unsaved", action="store_true")
    environment = sub.add_parser("environment")
    environment.add_argument("--dimension", type=int, choices=[2, 3], required=True)
    environment.add_argument("--engine")
    args = parser.parse_args()
    if args.command == "environment":
        from console_runtime import find_console_engine

        engine = find_console_engine(args.dimension, args.engine)
        result = engine_environment_report(engine)
    else:
        runtime = ConsoleRuntime(
            Path(args.workdir),
            dimension=args.dimension,
            port=args.port,
            engine=args.engine,
        )
        if args.command == "start":
            result = runtime.start()
        elif args.command == "health":
            result = {"describe": runtime.describe(), "preflight": runtime.preflight()}
        else:
            result = runtime.stop(
                save_name=args.save_name,
                allow_unsaved=args.allow_unsaved,
            )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
