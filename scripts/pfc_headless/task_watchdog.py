"""Progress-aware task watchdog.

Decides whether a still-running capture task is making real progress or is
blocked, instead of relying on a fixed wall-clock timeout. The old rule of
thumb ("wait 30 minutes then give up") conflated a legitimately long solve
with a hung process. This module samples objective progress signals twice and
classifies the task from their change.

Signals (all read locally, no engine execution required):
  * process liveness (PID exists)
  * process CPU time (user+system) — a busy solver burns CPU
  * output bytes under data/raw — FISH writes incrementally during capture
  * newest output mtime — freshness of writes
  * captured row count in frame_index.csv — frames actually landed

Classification:
  COMPLETED      run record task_status is terminal
  PROCESS_DEAD   PID no longer exists (task not terminal)
  RUNNING        process alive and at least one progress signal advanced
  STALLED        process alive but no signal advanced -> likely blocked
  UNKNOWN        insufficient data to decide (caller should keep waiting)

The watchdog is advisory: it never kills or mutates a task. Its JSON result can
be attached as evidence to run record-status / interrupt decisions.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover - engine Python has psutil; tests may not
    psutil = None  # type: ignore[assignment]

from .common import utc_now

TERMINAL = {"COMPLETED", "FAILED", "TIMEOUT_UNKNOWN", "INTERRUPTED", "INVALID"}
ACTIVE = {"SUBMITTED", "RUNNING"}


def _run_record(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "metadata" / "run.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _raw_snapshot(run_dir: Path) -> dict[str, float]:
    """Snapshot objective output progress under data/raw."""
    raw = run_dir / "data" / "raw"
    total_bytes = 0
    newest_mtime = 0.0
    frame_rows = 0
    if raw.is_dir():
        for path in raw.iterdir():
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            total_bytes += stat.st_size
            newest_mtime = max(newest_mtime, stat.st_mtime)
            if path.name == "frame_index.csv":
                try:
                    with path.open("r", encoding="utf-8", errors="ignore") as fh:
                        frame_rows = max(0, sum(1 for _ in fh) - 1)
                except OSError:
                    frame_rows = 0
    return {
        "total_bytes": float(total_bytes),
        "newest_mtime": float(newest_mtime),
        "frame_rows": float(frame_rows),
    }


def _cpu_snapshot(pid: int | None) -> dict[str, float]:
    if not pid or psutil is None:
        return {}
    try:
        process = psutil.Process(pid)
        if not process.is_running():
            return {}
        times = process.cpu_times()
        return {"cpu": float(times.user + times.system)}
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return {}


def sample(run_dir: Path, pid: int | None = None) -> dict[str, Any]:
    """Take one progress sample of a run directory / console PID."""
    record = _run_record(run_dir)
    if pid is None:
        pid = record.get("pid") or record.get("console_pid")
    return {
        "sampled_utc": utc_now(),
        "task_status": str(record.get("task_status", "UNKNOWN")).upper(),
        "pid": pid,
        "process": _cpu_snapshot(pid),
        "raw": _raw_snapshot(run_dir),
    }


def _advanced(before: dict[str, Any], after: dict[str, Any]) -> dict[str, bool]:
    p0 = before.get("process", {}) or {}
    p1 = after.get("process", {}) or {}
    r0 = before.get("raw", {}) or {}
    r1 = after.get("raw", {}) or {}
    return {
        "cpu_advanced": float(p1.get("cpu", 0)) > float(p0.get("cpu", 0)) + 1e-3,
        "bytes_advanced": float(r1.get("total_bytes", 0)) > float(r0.get("total_bytes", 0)),
        "mtime_advanced": float(r1.get("newest_mtime", 0)) > float(r0.get("newest_mtime", 0)),
        "frames_advanced": float(r1.get("frame_rows", 0)) > float(r0.get("frame_rows", 0)),
    }


def diagnose(
    run_dir: Path,
    *,
    pid: int | None = None,
    interval_s: float = 8.0,
) -> dict[str, Any]:
    """Sample twice and classify RUNNING / STALLED / PROCESS_DEAD / COMPLETED.

    ``interval_s`` is the gap between the two samples; it is a sampling detail,
    NOT a timeout. No status is derived from total elapsed time.
    """
    before = sample(run_dir, pid=pid)
    status = before["task_status"]
    if status in TERMINAL:
        return {
            "status": "COMPLETED" if status == "COMPLETED" else status,
            "reason": f"run task_status={status}",
            "samples": [before],
            "signals": {},
            "observed_utc": utc_now(),
        }
    if status not in ACTIVE and status != "UNKNOWN":
        return {
            "status": "UNKNOWN",
            "reason": f"unrecognized task_status={status}",
            "samples": [before],
            "signals": {},
            "observed_utc": utc_now(),
        }
    if before.get("pid") and psutil is not None:
        try:
            alive = psutil.Process(int(before["pid"])).is_running()
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            alive = False
        if not alive:
            return {
                "status": "PROCESS_DEAD",
                "reason": f"console pid {before['pid']} not running",
                "samples": [before],
                "signals": {},
                "observed_utc": utc_now(),
            }
    time.sleep(max(0.0, interval_s))
    after = sample(run_dir, pid=before.get("pid"))
    signals = _advanced(before, after)
    progressing = any(signals.values())
    if not before.get("process"):
        # No process signal (psutil missing / no pid): rely on output only.
        progressing = any(
            signals[k] for k in ("bytes_advanced", "mtime_advanced", "frames_advanced")
        )
        if not progressing:
            return {
                "status": "UNKNOWN",
                "reason": "no process telemetry and no output change; cannot decide",
                "samples": [before, after],
                "signals": signals,
                "observed_utc": utc_now(),
            }
    status_out = "RUNNING" if progressing else "STALLED"
    reason = (
        "progress signals advanced"
        if progressing
        else "process alive but cpu/output/frames all unchanged over sample window"
    )
    return {
        "status": status_out,
        "reason": reason,
        "samples": [before, after],
        "signals": signals,
        "observed_utc": utc_now(),
    }


def diagnose_to_file(
    run_dir: Path,
    out_path: Path,
    *,
    pid: int | None = None,
    interval_s: float = 8.0,
) -> dict[str, Any]:
    result = diagnose(run_dir, pid=pid, interval_s=interval_s)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result
