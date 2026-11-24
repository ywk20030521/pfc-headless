"""Run one prepared PFC case in an independent console process."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from console_runtime import (
    BridgeClient,
    ConsoleRuntime,
    ConsoleRuntimeError,
    find_console_engine,
    utc_now,
)
from standardize import standardize_experiment
from validate_capture import validate


SCRIPT_DIR = Path(__file__).resolve().parent


def _json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _progress(root: Path, stage: str, **details: Any) -> None:
    _json_dump(
        root / "console_progress.json",
        {"stage": stage, "updated_utc": utc_now(), **details},
    )


def prepare_run_directory_from_config(
    config: dict[str, Any],
    run_root: Path,
    *,
    allow_existing_managed_root: bool = False,
) -> dict[str, Any]:
    run_root = run_root.resolve()
    if run_root.exists() and not allow_existing_managed_root:
        raise FileExistsError(f"Refusing to overwrite run root: {run_root}")
    entry_dir = run_root / "entry"
    data_dir = run_root / "data"
    if entry_dir.exists() or data_dir.exists():
        raise FileExistsError(
            f"Refusing to overwrite prepared Run artifacts: {run_root}"
        )
    entry_dir.mkdir(parents=True)
    target_config = dict(config)
    target_config["run_dir"] = str(data_dir)
    target_config["execution_mode"] = "CONSOLE"
    config_out = entry_dir / "capture_config.json"
    _json_dump(config_out, target_config)
    shutil.copy2(SCRIPT_DIR / "capture_case.py", entry_dir / "capture_case.py")
    launch = {
        "transport": None,
        "entry_script": str(entry_dir / "capture_case.py"),
        "config": str(config_out),
        "data_dir": str(data_dir),
        "run_id": str(target_config["run_id"]),
        "case_id": int(target_config["case_id"]),
    }
    _json_dump(run_root / "launch.json", launch)
    return launch


def prepare_run_directory(config_path: Path, run_root: Path) -> dict[str, Any]:
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    launch = prepare_run_directory_from_config(config, run_root)
    launch["source_config"] = str(config_path)
    _json_dump(run_root / "launch.json", launch)
    return launch


def _write_direct_entry(launch: dict[str, Any]) -> Path:
    run_root = Path(launch["data_dir"]).resolve().parent
    entry = run_root / "entry" / "console_direct_entry.py"
    result_path = run_root / "direct_result.json"
    source = f"""# -*- coding: utf-8 -*-
import json
import os
import sys
import traceback

ENTRY_DIR = r'{Path(launch["entry_script"]).resolve().parent}'
CONFIG = r'{Path(launch["config"]).resolve()}'
RESULT = r'{result_path}'
sys.path.insert(0, ENTRY_DIR)
os.environ['PFC_LIVE_CAPTURE_CONFIG'] = CONFIG

import itasca
status = 'FAILED'
error = None
try:
    from capture_case import main as capture_main
    exit_code = int(capture_main())
    status = 'COMPLETE' if exit_code == 0 else 'FAILED'
except BaseException as exc:
    error = {{'type': type(exc).__name__, 'message': str(exc), 'traceback': traceback.format_exc()}}
finally:
    payload = {{'status': status, 'error': error, 'engine': sys.executable,
               'dimension': int(itasca.dim()), 'pid': int(os.getpid())}}
    with open(RESULT, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write('\\n')
    itasca.command('program exit')
"""
    entry.write_text(source, encoding="utf-8", newline="\n")
    return entry


def run_direct(
    launch: dict[str, Any],
    *,
    dimension: int,
    engine: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    run_root = Path(launch["data_dir"]).resolve().parent
    entry = _write_direct_entry(launch)
    stdout_path = run_root / "console_stdout.log"
    stderr_path = run_root / "console_stderr.log"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    started = time.perf_counter()
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr:
        process = subprocess.Popen(
            [str(engine), "--run", str(entry)],
            cwd=run_root,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            creationflags=flags,
        )
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.terminate()
            return_code = process.wait(timeout=10)
    result_path = run_root / "direct_result.json"
    direct_result = (
        json.loads(result_path.read_text(encoding="utf-8"))
        if result_path.is_file()
        else {"status": "FAILED", "error": "direct_result.json missing"}
    )
    return {
        "transport": "direct",
        "dimension": dimension,
        "engine": str(engine),
        "pid": process.pid,
        "return_code": return_code,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "result": direct_result,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
    }


def run_bridge(
    launch: dict[str, Any],
    *,
    runtime_workdir: Path,
    dimension: int,
    port: int,
    engine: Path | None,
    manage_process: bool,
    timeout_seconds: float,
    task_kind: str = "task",
    on_event: Any = None,
) -> dict[str, Any]:
    runtime = ConsoleRuntime(
        runtime_workdir,
        dimension=dimension,
        port=port,
        engine=engine,
    )
    started = time.perf_counter()
    state = runtime.start() if manage_process else runtime.attach()
    _progress(runtime_workdir.parent, "runtime_ready")
    client = BridgeClient(f"http://127.0.0.1:{port}")
    if task_kind == "code":
        if timeout_seconds > 600:
            raise ConsoleRuntimeError(
                "execute_code is limited to 600 seconds; use task_kind=task"
            )
        source = (
            "import os, sys\n"
            f"sys.path.insert(0, {str(Path(launch['entry_script']).parent)!r})\n"
            f"os.environ['PFC_LIVE_CAPTURE_CONFIG'] = {str(launch['config'])!r}\n"
            "from capture_case import main as _pfc_capture_main\n"
            "_pfc_capture_status = int(_pfc_capture_main())\n"
            "print('PFC_HEADLESS_CODE_STATUS', _pfc_capture_status)\n"
        )
        if on_event:
            on_event("SUBMITTED", {"task_kind": "code"})
        response = client.execute_code(
            source,
            timeout_seconds=max(1, min(600, int(timeout_seconds))),
        )
        output = str((response.get("data") or {}).get("output") or "")
        completed = (
            response.get("status") == "success"
            and "PFC_HEADLESS_CODE_STATUS 0" in output
        )
        if on_event:
            on_event("COMPLETED" if completed else "FAILED", {"task_kind": "code"})
        return {
            "transport": "bridge",
            "task_kind": "code",
            "dimension": dimension,
            "engine": str(runtime.engine),
            "runtime": state,
            "task_id": None,
            "response": response,
            "task_status": "completed" if completed else "failed",
            "output": output,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    task_id = client.submit_task(
        Path(launch["entry_script"]),
        f"PFC{int(dimension)}D Console case {int(launch['case_id'])} embedded capture {launch['run_id']}",
    )
    if on_event:
        on_event("SUBMITTED", {"task_id": task_id, "task_kind": "task"})
    _progress(runtime_workdir.parent, "task_submitted", task_id=task_id)
    try:
        task = client.wait_task(task_id, timeout_seconds=timeout_seconds)
    except TimeoutError as exc:
        history = client.check_task(task_id)
        if on_event:
            on_event(
                "TIMEOUT_UNKNOWN",
                {"task_id": task_id, "last_status": history},
            )
        raise ConsoleRuntimeError(
            f"Task {task_id} timed out; automatic resubmission is forbidden. "
            f"Last status: {history}"
        ) from exc
    _progress(runtime_workdir.parent, "task_finished", task_id=task_id)
    data = task.get("data") or task
    status = client.task_state(task)
    if on_event:
        on_event(status.upper(), {"task_id": task_id, "task_kind": "task"})
    return {
        "transport": "bridge",
        "task_kind": "task",
        "dimension": dimension,
        "engine": str(runtime.engine),
        "runtime": state,
        "task_id": task_id,
        "task": task,
        "task_status": status,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def finalize_prepared_run(
    launch: dict[str, Any],
    *,
    run_root: Path,
    execution: dict[str, Any],
    standardized_output: Path | None = None,
    title: str | None = None,
    pfc_version: str | None = None,
    export_npy: bool = False,
) -> dict[str, Any]:
    """Validate and standardize an MCP-completed Run without executing PFC."""
    run_root = run_root.resolve()
    data_dir = Path(launch["data_dir"])
    execution_complete = (
        str(execution.get("task_status") or execution.get("status") or "").lower()
        == "completed"
    )
    if execution_complete:
        _progress(run_root, "validation_started")
        validation = validate(data_dir)
    else:
        validation = {
            "schema_version": 1,
            "status": "FAIL",
            "errors": ["MCP execution did not report completion"],
            "warnings": [],
            "execution_status": execution.get("task_status"),
        }
    _json_dump(data_dir / "metadata" / "validation.json", validation)
    _progress(run_root, "validation_finished", status=validation.get("status"))
    result = dict(execution)
    result["validation"] = validation
    result["status"] = (
        "COMPLETE"
        if execution_complete and validation.get("status") == "PASS"
        else "FAILED"
    )
    result["generated_utc"] = utc_now()
    _json_dump(run_root / "console_run_result.json", result)
    if standardized_output is not None and result["status"] == "COMPLETE":
        _progress(
            run_root,
            "standardization_started",
            output=str(standardized_output),
        )
        result["standardization"] = standardize_experiment(
            run_root,
            standardized_output,
            title=title or str(launch["run_id"]),
            experiment_id=standardized_output.name,
            execution_mode="CONSOLE",
            pfc_version=pfc_version,
            export_npy=export_npy,
        )
        _progress(run_root, "standardization_finished")
        _json_dump(run_root / "console_run_result.json", result)
    if result["status"] != "COMPLETE":
        raise ConsoleRuntimeError(
            f"Capture failed; refusing standardization: {run_root}"
        )
    return result


def execute_prepared_run(
    launch: dict[str, Any],
    *,
    run_root: Path,
    dimension: int,
    transport: str = "bridge",
    port: int = 9001,
    engine: Path | None = None,
    manage_process: bool = True,
    timeout_seconds: float = 3600.0,
    standardized_output: Path | None = None,
    title: str | None = None,
    pfc_version: str | None = None,
    export_npy: bool = False,
    task_kind: str = "task",
    on_event: Any = None,
    runtime_workdir: Path | None = None,
) -> dict[str, Any]:
    run_root = run_root.resolve()
    engine_path = find_console_engine(dimension, engine)
    _progress(run_root, "engine_found", engine=str(engine_path))
    if transport == "direct":
        execution = run_direct(
            launch,
            dimension=dimension,
            engine=engine_path,
            timeout_seconds=timeout_seconds,
        )
    else:
        execution = run_bridge(
            launch,
            runtime_workdir=runtime_workdir or (run_root / "runtime"),
            dimension=dimension,
            port=port,
            engine=engine_path,
            manage_process=manage_process,
            timeout_seconds=timeout_seconds,
            task_kind=task_kind,
            on_event=on_event,
        )
    _progress(run_root, "execution_returned")
    return finalize_prepared_run(
        launch,
        run_root=run_root,
        execution=execution,
        standardized_output=standardized_output,
        title=title,
        pfc_version=pfc_version,
        export_npy=export_npy,
    )


def run_case(
    *,
    config: Path,
    run_root: Path,
    dimension: int,
    transport: str = "bridge",
    port: int = 9001,
    engine: Path | None = None,
    manage_process: bool = True,
    timeout_seconds: float = 3600.0,
    standardized_output: Path | None = None,
    title: str | None = None,
    pfc_version: str | None = None,
    export_npy: bool = False,
    task_kind: str = "task",
    on_event: Any = None,
) -> dict[str, Any]:
    launch = prepare_run_directory(config, run_root)
    _progress(run_root.resolve(), "prepared")
    return execute_prepared_run(
        launch,
        run_root=run_root,
        dimension=dimension,
        transport=transport,
        port=port,
        engine=engine,
        manage_process=manage_process,
        timeout_seconds=timeout_seconds,
        standardized_output=standardized_output,
        title=title,
        pfc_version=pfc_version,
        export_npy=export_npy,
        task_kind=task_kind,
        on_event=on_event,
    )


def main() -> int:
    raise SystemExit(
        "Direct run_case execution is disabled. Use headless.py run prepare, "
        "call itasca_execute_task through the Agent Host, bind the returned task "
        "with run attach-task, then finalize with run finalize."
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--dimension", type=int, choices=[2, 3], required=True)
    parser.add_argument("--transport", choices=["bridge", "direct"], default="bridge")
    parser.add_argument("--port", type=int, default=9001)
    parser.add_argument("--engine")
    parser.add_argument("--attach", action="store_true")
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument(
        "--standardized-output",
        help="New pfc-headless standardized-delivery directory.",
    )
    parser.add_argument("--title")
    parser.add_argument("--pfc-version")
    parser.add_argument("--export-npy", action="store_true")
    parser.add_argument(
        "--task-kind",
        choices=["task", "code"],
        default="task",
        help="Use execute_task for long runs or execute_code for short runs.",
    )
    args = parser.parse_args()
    result = run_case(
        config=Path(args.config),
        run_root=Path(args.run_root),
        dimension=args.dimension,
        transport=args.transport,
        port=args.port,
        engine=Path(args.engine) if args.engine else None,
        manage_process=not args.attach,
        timeout_seconds=args.timeout,
        standardized_output=(
            Path(args.standardized_output) if args.standardized_output else None
        ),
        title=args.title,
        pfc_version=args.pfc_version,
        export_npy=args.export_npy,
        task_kind=args.task_kind,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
