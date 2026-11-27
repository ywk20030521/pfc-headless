#!/usr/bin/env python3
"""Reproducible performance benchmark for the pfc-headless execution gate.

Covers the key usage paths introduced by the authorization gate:
formal authorization resolution, missing-field rejection, persisted gate
re-check, pilot acceptance, legacy Run rejection, Run persistence and the
CLI prepare boundary.

Metrics: per-call latency (mean/p50/p95/p99/min/max), CPU time, process RSS,
Python allocation peak (tracemalloc), and stability (expected exception rate,
output determinism, RSS growth across repeated rounds).

The benchmark is dependency-light: psutil is used when available, otherwise
process RSS is reported as unavailable. It never calls itasca-mcp or PFC.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - optional
    psutil = None  # type: ignore

from pfc_headless.authorization import (  # noqa: E402
    FORMAL,
    PILOT,
    gate_run_record,
    resolve_authorization,
)
from pfc_headless.common import HeadlessError  # noqa: E402
from pfc_headless.project import init_project  # noqa: E402

FORMAL_INPUT = {
    "authorization_id": "auth-bench123",
    "research_task_id": "task-bench",
    "decision_id": "dec-bench",
    "model_version": "model-v1",
    "parameter_version": "param-v1",
    "matrix_version": "matrix-v1",
}
PILOT_INPUT = {"pilot": True, "pilot_reason": "benchmark smoke test"}
FORMAL_RECORD = resolve_authorization(FORMAL_INPUT).to_record()
PILOT_RECORD = resolve_authorization(PILOT_INPUT).to_record()


def _expected_error(fn: Callable[[], Any], needle: str) -> dict[str, Any]:
    try:
        fn()
    except HeadlessError as exc:
        text = str(exc)
        if needle not in text:
            raise AssertionError(f"unexpected error: {text}")
        return {"error": text.split(".")[0]}
    raise AssertionError("expected HeadlessError was not raised")


def scenario_authorize_formal() -> dict[str, Any]:
    return resolve_authorization(dict(FORMAL_INPUT)).to_record()


def scenario_authorize_missing() -> dict[str, Any]:
    partial = {k: v for k, v in FORMAL_INPUT.items() if k != "matrix_version"}
    return _expected_error(lambda: resolve_authorization(partial), "matrix_version")


def scenario_gate_formal() -> dict[str, Any]:
    record = {"run_id": "run_bench_formal", "authorization": dict(FORMAL_RECORD)}
    return gate_run_record(record)


def scenario_gate_pilot() -> dict[str, Any]:
    record = {"run_id": "run_bench_pilot", "authorization": dict(PILOT_RECORD)}
    return gate_run_record(record)


def scenario_gate_legacy() -> dict[str, Any]:
    return _expected_error(lambda: gate_run_record({"run_id": "run_legacy"}), "no execution authorization")


class RunPersistenceScenario:
    """Create and re-check an authorized Run on disk (includes JSON write)."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="headless-bench-")
        root = Path(self._tmp.name)
        self.project = init_project(root / "project", name="authorization benchmark")
        config = root / "case.json"
        config.write_text(
            json.dumps({
                "run_id": "source",
                "project_dir": str(root),
                "setup": ["model new"],
                "solve": "model solve time 0.01",
            }),
            encoding="utf-8",
        )
        self.project.add_case(config, dimension=2)
        self.counter = 0

    def __call__(self) -> dict[str, Any]:
        self.counter += 1
        created = self.project.new_run(
            0,
            run_id=f"bench_{self.counter}",
            authorization=dict(FORMAL_RECORD),
        )
        return {"status": gate_run_record(created["record"])["status"]}

    def close(self) -> None:
        self._tmp.cleanup()


def scenario_cli_prepare_without_auth() -> dict[str, Any]:
    import headless

    with tempfile.TemporaryDirectory(prefix="headless-cli-bench-") as temp:
        root = Path(temp)
        project = init_project(root / "project", name="CLI gate benchmark")
        config = root / "case.json"
        config.write_text(
            json.dumps({
                "run_id": "source",
                "project_dir": str(root),
                "setup": ["model new"],
                "solve": "model solve time 0.01",
            }),
            encoding="utf-8",
        )
        project.add_case(config, dimension=2)
        argv = [
            "headless.py", "run", "prepare", "--project", str(root / "project"),
            "--case-id", "0", "--instance-id", "pfc2d_bench",
        ]
        with patch.object(sys, "argv", argv):
            return _expected_error(headless.main, "Formal Run requires user authorization")


SCENARIOS: list[tuple[str, Callable[[], dict[str, Any]], int, int]] = [
    ("resolve_formal_authorization", scenario_authorize_formal, 400, 40),
    ("reject_missing_binding", scenario_authorize_missing, 400, 40),
    ("gate_formal_record", scenario_gate_formal, 400, 40),
    ("gate_pilot_record", scenario_gate_pilot, 400, 40),
    ("reject_legacy_run", scenario_gate_legacy, 400, 40),
    ("run_prepare_persist_and_gate", RunPersistenceScenario, 40, 5),
    ("cli_prepare_without_auth", scenario_cli_prepare_without_auth, 20, 2),
]


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def measure(name: str, factory: Callable[[], Any], iterations: int,
            warmup: int, rounds: int) -> dict[str, Any]:
    scenario = factory() if isinstance(factory, type) else factory
    for _ in range(warmup):
        scenario()

    proc = psutil.Process() if psutil else None
    round_stats: list[dict[str, Any]] = []
    signatures: set[str] = set()
    total_calls = 0

    for _ in range(rounds):
        samples: list[float] = []
        rss_before = proc.memory_info().rss if proc else 0
        cpu_before = time.process_time()
        wall_before = time.perf_counter()
        for _ in range(iterations):
            start = time.perf_counter()
            result = scenario()
            samples.append((time.perf_counter() - start) * 1000.0)
            signatures.add(json.dumps(result, sort_keys=True, default=str))
            total_calls += 1
        wall_ms = (time.perf_counter() - wall_before) * 1000.0
        cpu_ms = (time.process_time() - cpu_before) * 1000.0
        rss_after = proc.memory_info().rss if proc else 0
        round_stats.append({
            "samples_ms": samples,
            "wall_ms": wall_ms,
            "cpu_ms": cpu_ms,
            "rss_before_bytes": rss_before,
            "rss_after_bytes": rss_after,
        })

    # Separate allocation measurement: tracemalloc perturbs latency.
    tracemalloc.start()
    for _ in range(iterations):
        scenario()
    _, allocation_peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    if hasattr(scenario, "close"):
        scenario.close()

    all_samples = [s for r in round_stats for s in r["samples_ms"]]
    rss_growth = round_stats[-1]["rss_after_bytes"] - round_stats[0]["rss_before_bytes"]
    return {
        "name": name,
        "iterations_per_round": iterations,
        "rounds": rounds,
        "total_calls": total_calls,
        "latency_ms": {
            "mean": round(statistics.fmean(all_samples), 6),
            "median": round(_percentile(all_samples, 0.5), 6),
            "p95": round(_percentile(all_samples, 0.95), 6),
            "p99": round(_percentile(all_samples, 0.99), 6),
            "min": round(min(all_samples), 6),
            "max": round(max(all_samples), 6),
            "stdev": round(statistics.pstdev(all_samples), 6),
        },
        "resource": {
            "cpu_ms_per_round_mean": round(
                statistics.fmean(r["cpu_ms"] for r in round_stats), 3),
            "wall_ms_per_round_mean": round(
                statistics.fmean(r["wall_ms"] for r in round_stats), 3),
            "rss_start_bytes": round_stats[0]["rss_before_bytes"],
            "rss_end_bytes": round_stats[-1]["rss_after_bytes"],
            "rss_growth_bytes": rss_growth,
            "tracemalloc_peak_bytes": allocation_peak_bytes,
            "psutil_available": psutil is not None,
        },
        "stability": {
            "unexpected_exceptions": 0,
            "distinct_outputs": len(signatures),
            "deterministic": len(signatures) == 1,
            "rss_growth_bytes": rss_growth,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "benchmarks" / "results.json")
    args = parser.parse_args()

    results = {
        "benchmark": "pfc-headless-execution-authorization-gate",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "psutil": getattr(psutil, "__version__", None),
            "real_pfc_execution": False,
        },
        "scenarios": [
            measure(name, fn, iterations, 40 if iterations >= 400 else iterations // 8,
                    args.rounds)
            for name, fn, iterations, _ in SCENARIOS
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    for scenario in results["scenarios"]:
        latency = scenario["latency_ms"]
        print(f"{scenario['name']:34s} mean={latency['mean']:.4f}ms "
              f"p95={latency['p95']:.4f}ms p99={latency['p99']:.4f}ms "
              f"deterministic={scenario['stability']['deterministic']}")
    print(f"Results written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
