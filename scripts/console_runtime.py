"""Console-only PFC process and Python API runtime.

This module never launches a GUI build. It verifies the product and Console
identity from executable contents, then starts the engine with the official
``--run`` script-file argument. Typical builds are ``pfc2d9_console.exe`` and
``pfc3d9_console.exe``; other verified Console filenames are accepted.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pfc_headless.common import append_audit
from pfc_headless.environment import classify_console_executable, find_console_engine


TERMINAL_STATES = {"completed", "failed", "error", "cancelled", "interrupted"}


class ConsoleRuntimeError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _port_has_listener(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


class BridgeClient:
    """Small loopback-only client for the itasca-mcp console bridge."""

    def __init__(self, base_url: str = "http://127.0.0.1:9001"):
        if not (
            base_url.startswith("http://127.0.0.1:")
            or base_url.startswith("http://localhost:")
        ):
            raise ValueError("The console bridge client accepts loopback URLs only")
        self.base_url = base_url.rstrip("/")

    def _request(
        self,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        data = None
        headers = {}
        method = "GET" if payload is None else "POST"
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}/{endpoint.lstrip('/')}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise ConsoleRuntimeError(
                f"Bridge HTTP {exc.code} at {endpoint}: {detail[:1000]}"
            ) from exc
        except OSError as exc:
            raise ConsoleRuntimeError(
                f"Bridge is unreachable at {self.base_url}: {exc}"
            ) from exc
        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ConsoleRuntimeError(
                f"Bridge returned non-JSON from {endpoint}: {body[:500]}"
            ) from exc
        if not isinstance(result, dict):
            raise ConsoleRuntimeError(f"Bridge returned non-object from {endpoint}")
        return result

    def health(self) -> dict[str, Any]:
        result = self._request("health", timeout=5.0)
        if result.get("status") != "success":
            raise ConsoleRuntimeError(f"Bridge health failed: {result}")
        if result.get("runtime_mode") != "console":
            raise ConsoleRuntimeError(
                f"Refusing non-console runtime: {result.get('runtime_mode')!r}"
            )
        return result

    def execute_code(self, code: str, *, timeout_seconds: int = 20) -> dict[str, Any]:
        timeouts = max(1, min(int(timeout_seconds), 600))
        return self._request(
            "execute_code",
            {
                "request_id": uuid.uuid4().hex,
                "code": code,
                "timeout_ms": timeouts * 1000,
            },
            timeout=timeouts + 30,
        )

    def submit_task(self, script_path: Path, description: str) -> str:
        task_id = uuid.uuid4().hex[:6]
        result = self._request(
            "execute_task",
            {
                "script_path": str(script_path.resolve()),
                "description": description,
                "task_id": task_id,
            },
            timeout=60.0,
        )
        if result.get("ok") is False:
            raise ConsoleRuntimeError(f"Task submission failed: {result}")
        return task_id

    def list_tasks(self, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        return self._request(
            "list_tasks",
            {"offset": int(offset), "limit": int(limit)},
            timeout=30.0,
        )

    def check_task(self, task_id: str, *, limit: int = 80) -> dict[str, Any]:
        return self._request(
            "check_task_status",
            {"task_id": task_id, "limit": int(limit)},
            timeout=30.0,
        )

    @staticmethod
    def task_state(response: dict[str, Any]) -> str:
        data = response.get("data")
        if isinstance(data, dict):
            task = data.get("task")
            if isinstance(task, dict) and task.get("status"):
                return str(task["status"]).lower()
            for key in ("task_status", "status"):
                if data.get(key):
                    return str(data[key]).lower()
        return str(response.get("status") or "").lower()

    def interrupt_task(self, task_id: str) -> dict[str, Any]:
        return self._request(
            "interrupt_task",
            {"task_id": task_id},
            timeout=30.0,
        )

    def wait_task(
        self,
        task_id: str,
        *,
        timeout_seconds: float = 3600.0,
        interval_seconds: float = 1.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + float(timeout_seconds)
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self.check_task(task_id)
            state = self.task_state(last)
            if state in TERMINAL_STATES:
                return last
            time.sleep(interval_seconds)
        raise TimeoutError(
            f"Task {task_id} did not finish within {timeout_seconds}s; last={last}"
        )


class ConsoleRuntime:
    """Own one PFC console process and its in-process bridge."""

    def __init__(
        self,
        workdir: str | Path,
        *,
        dimension: int,
        port: int = 9001,
        engine: str | Path | None = None,
        instance_id: str | None = None,
    ):
        self.workdir = Path(workdir).resolve()
        self.dimension = int(dimension)
        self.port = int(port)
        if not 1024 <= self.port <= 65535:
            raise ValueError("Console bridge port must be between 1024 and 65535")
        self.engine = find_console_engine(self.dimension, engine)
        self.engine_info = classify_console_executable(self.engine)
        if self.engine_info["dimension"] != self.dimension:
            raise ConsoleRuntimeError(
                f"Engine does not match PFC{self.dimension}D console: {self.engine}"
            )
        self.runtime_dir = self.workdir / ".pfc-console"
        self.state_path = self.runtime_dir / "runtime.json"
        self.stdout_path = self.runtime_dir / "console_stdout.log"
        self.stderr_path = self.runtime_dir / "console_stderr.log"
        self.bootstrap_path = self.runtime_dir / "bridge_bootstrap.py"
        self.audit_path = self.runtime_dir / "lifecycle_audit.jsonl"
        self.instance_id = instance_id or (
            f"pfc{self.dimension}d_{self.port}_{uuid.uuid4().hex[:8]}"
        )
        self.client = BridgeClient(f"http://127.0.0.1:{self.port}")

    def _bootstrap_source(self) -> str:
        return (
            "# -*- coding: utf-8 -*-\n"
            "import os\n"
            "import itasca_mcp_bridge\n"
            "port = int(os.environ['ITASCA_MCP_BRIDGE_PORT'])\n"
            "itasca_mcp_bridge.start(host='127.0.0.1', port=port, "
            "mode='console', auto_upgrade=False)\n"
        )

    def state(self) -> dict[str, Any] | None:
        if not self.state_path.is_file():
            return None
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def describe(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "engine": str(self.engine),
            "dimension": self.dimension,
            "engine_version": self.engine_info.get("engine_version"),
            "port": self.port,
            "workdir": str(self.workdir),
            "runtime_mode": "console",
            "state": self.state(),
        }

    def preflight(self) -> dict[str, Any]:
        health = self.client.health()
        probe = self.client.execute_code(
            "import json, os, sys, itasca\n"
            "print('PFC_HEADLESS_PROBE=' + json.dumps({"
            "'executable': sys.executable, 'pid': os.getpid(), "
            "'cwd': os.getcwd(), 'dimension': int(itasca.dim()), "
            "'cycle': int(itasca.cycle()), 'balls': int(itasca.ball.count())}))\n",
            timeout_seconds=20,
        )
        output = str((probe.get("data") or {}).get("output") or "")
        marker = "PFC_HEADLESS_PROBE="
        if marker not in output:
            raise ConsoleRuntimeError(
                f"Bridge PFC probe did not return JSON; output: {output[:500]}"
            )
        try:
            details = json.loads(output.split(marker, 1)[1].splitlines()[0])
        except (json.JSONDecodeError, IndexError) as exc:
            raise ConsoleRuntimeError(
                f"Bridge PFC probe is malformed; output: {output[:500]}"
            ) from exc
        executable = Path(str(details.get("executable", ""))).resolve()
        if executable != self.engine.resolve():
            raise ConsoleRuntimeError(
                f"Bridge engine identity mismatch: {executable} != {self.engine}"
            )
        if int(details.get("dimension", 0)) != self.dimension:
            raise ConsoleRuntimeError(
                f"Bridge dimension mismatch: {details.get('dimension')} != {self.dimension}"
            )
        if Path(str(details.get("cwd", ""))).resolve() != self.workdir:
            raise ConsoleRuntimeError(
                "Refusing to reuse a bridge from a different working directory: "
                f"{details.get('cwd')} != {self.workdir}"
            )
        return {"health": health, "probe_output": output, "probe": details}

    @staticmethod
    def _process_details(pid: int) -> dict[str, Any]:
        try:
            import psutil
        except ImportError as exc:
            raise ConsoleRuntimeError(
                "psutil is required to verify process identity before reuse or stop"
            ) from exc
        try:
            process = psutil.Process(pid)
            with process.oneshot():
                return {
                    "pid": int(process.pid),
                    "executable": str(Path(process.exe()).resolve()),
                    "command_line": list(process.cmdline()),
                    "create_time": float(process.create_time()),
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as exc:
            raise ConsoleRuntimeError(f"Cannot verify process {pid}: {exc}") from exc

    def process_identity(self, state: dict[str, Any] | None = None) -> dict[str, Any]:
        state = state or self.state()
        if not state or not state.get("pid"):
            raise ConsoleRuntimeError("No registered PID to verify")
        details = self._process_details(int(state["pid"]))
        expected_engine = Path(str(state.get("engine") or self.engine)).resolve()
        if Path(details["executable"]) != expected_engine:
            raise ConsoleRuntimeError(
                f"PID {details['pid']} executable mismatch: "
                f"{details['executable']} != {expected_engine}"
            )
        bootstrap_name = Path(str(state.get("bootstrap_path") or self.bootstrap_path)).name
        joined = " ".join(details["command_line"])
        if "--run" not in details["command_line"] or bootstrap_name not in joined:
            raise ConsoleRuntimeError(
                f"PID {details['pid']} command line does not match the registered bootstrap"
            )
        return details

    def attach(self) -> dict[str, Any]:
        preflight = self.preflight()
        pid = int(preflight["probe"]["pid"])
        process = self._process_details(pid)
        state = {
            "status": "ATTACHED",
            "instance_id": self.instance_id,
            "engine": str(self.engine),
            "dimension": self.dimension,
            "pid": pid,
            "port": self.port,
            "workdir": str(self.workdir),
            "bootstrap_path": str(self.bootstrap_path),
            "command_line": process["command_line"],
            "process_create_time": process["create_time"],
            "executable_sha256": self.engine_info["file"]["sha256"],
            "engine_version": self.engine_info.get("engine_version"),
            "attached_utc": utc_now(),
            "health": preflight["health"],
            "probe_output": preflight["probe_output"],
            "probe": preflight["probe"],
        }
        _atomic_json(self.state_path, state)
        append_audit(
            self.audit_path,
            "ATTACHED_VERIFIED_INSTANCE",
            instance_id=self.instance_id,
            pid=pid,
            engine=str(self.engine),
            port=self.port,
        )
        return state

    def start(
        self,
        *,
        timeout_seconds: float = 45.0,
        reuse: bool = True,
    ) -> dict[str, Any]:
        if _port_has_listener(self.port):
            if not reuse:
                raise ConsoleRuntimeError(f"Port {self.port} is already in use")
            return self.attach()
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.bootstrap_path.write_text(
            self._bootstrap_source(), encoding="utf-8", newline="\n"
        )
        environment = os.environ.copy()
        environment["ITASCA_MCP_BRIDGE_PORT"] = str(self.port)
        environment["ITASCA_MCP_BRIDGE_AUTO_UPGRADE"] = "0"
        # On Windows, a Console launched as a child of an agent/CI shell is
        # killed when that shell exits (process-group teardown).  A detached
        # process group keeps the Bridge alive across tool calls.  It is
        # opt-out via PFC_HEADLESS_NO_DETACH=1 for environments that manage
        # the process tree themselves.
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        if os.name == "nt" and os.environ.get("PFC_HEADLESS_NO_DETACH") != "1":
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
            flags |= 0x00000008  # DETACHED_PROCESS
        with self.stdout_path.open("w", encoding="utf-8") as stdout, self.stderr_path.open(
            "w", encoding="utf-8"
        ) as stderr:
            process = subprocess.Popen(
                [str(self.engine), "--run", str(self.bootstrap_path)],
                cwd=self.workdir,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                creationflags=flags,
            )
        deadline = time.monotonic() + float(timeout_seconds)
        last_error = ""
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                health = self.client.health()
                probe = self.preflight()
                state = {
                    "status": "READY_TO_VERIFY",
                    "instance_id": self.instance_id,
                    "engine": str(self.engine),
                    "dimension": self.dimension,
                    "pid": int(process.pid),
                    "port": self.port,
                    "workdir": str(self.workdir),
                    "started_utc": utc_now(),
                    "launch_arguments": ["--run", str(self.bootstrap_path)],
                    "bootstrap_path": str(self.bootstrap_path),
                    "command_line": [str(self.engine), "--run", str(self.bootstrap_path)],
                    "process_create_time": self._process_details(
                        int(process.pid)
                    )["create_time"],
                    "executable_sha256": self.engine_info["file"]["sha256"],
                    "engine_version": self.engine_info.get("engine_version"),
                    "health": health,
                    "probe_output": probe["probe_output"],
                    "probe": probe["probe"],
                }
                _atomic_json(self.state_path, state)
                append_audit(
                    self.audit_path,
                    "CONSOLE_STARTED",
                    instance_id=self.instance_id,
                    pid=int(process.pid),
                    engine=str(self.engine),
                    port=self.port,
                    launch_arguments=["--run", str(self.bootstrap_path)],
                )
                return state
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.5)
        stderr_text = (
            self.stderr_path.read_text(encoding="utf-8", errors="replace")
            if self.stderr_path.is_file()
            else ""
        )
        stdout_text = (
            self.stdout_path.read_text(encoding="utf-8", errors="replace")
            if self.stdout_path.is_file()
            else ""
        )
        if process.poll() is None:
            process.terminate()
        raise ConsoleRuntimeError(
            "Console bridge did not become ready. "
            f"last_error={last_error}; stderr={stderr_text[-1000:]}; "
            f"stdout={stdout_text[-2000:]}"
        )

    def _interrupt_active_tasks(self) -> list[dict[str, Any]]:
        results = []
        listing = self.client.list_tasks(offset=0, limit=100)
        data = listing.get("data")
        if isinstance(data, dict):
            tasks = data.get("tasks") or data.get("items") or []
        elif isinstance(data, list):
            tasks = data
        else:
            tasks = []
        for task in tasks:
            if str(task.get("status", "")).lower() not in {"pending", "running"}:
                continue
            task_id = str(task.get("task_id") or task.get("id") or "")
            if not task_id:
                continue
            response = self.client.interrupt_task(task_id)
            results.append({"task_id": task_id, "response": response})
            deadline = time.monotonic() + 20.0
            state = ""
            while time.monotonic() < deadline:
                state = self.client.task_state(
                    self.client.check_task(task_id)
                )
                if state in TERMINAL_STATES:
                    break
                time.sleep(0.5)
            if state not in TERMINAL_STATES:
                raise ConsoleRuntimeError(
                    f"Task {task_id} did not reach a terminal state after interrupt"
                )
        return results

    def stop(
        self,
        *,
        save_model: bool = True,
        save_name: str | None = None,
        allow_unsaved: bool = False,
        force_if_needed: bool = True,
    ) -> dict[str, Any]:
        state = self.state()
        if not state or not state.get("pid"):
            return {"status": "NOT_RUNNING", "reason": "No registered instance PID"}
        pid = int(state["pid"])
        identity = self.process_identity(state)
        state["status"] = "STOPPING"
        _atomic_json(self.state_path, state)
        append_audit(
            self.audit_path,
            "STOP_STARTED",
            instance_id=state.get("instance_id"),
            pid=pid,
        )
        interrupted = []
        try:
            interrupted = self._interrupt_active_tasks()
        except Exception as exc:
            state["status"] = "READY_TO_VERIFY"
            _atomic_json(self.state_path, state)
            append_audit(
                self.audit_path,
                "STOP_ABORTED_ACTIVE_TASK_CHECK",
                pid=pid,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise ConsoleRuntimeError(
                f"Refusing to stop PID {pid}: active task check failed: {exc}"
            ) from exc

        saved_model = None
        safe_name = save_name or f"pfc_headless_stop_{self.instance_id}"
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", safe_name):
            raise ConsoleRuntimeError(f"Unsafe model save name: {safe_name!r}")
        if save_model:
            try:
                response = self.client.execute_code(
                    "import itasca\n"
                    f"itasca.command(\"model save '{safe_name}'\")\n"
                    "print('MODEL_SAVE_OK')\n",
                    timeout_seconds=60,
                )
                output = str((response.get("data") or {}).get("output") or "")
                if "MODEL_SAVE_OK" not in output:
                    raise ConsoleRuntimeError(f"Model save did not confirm: {output[:500]}")
                saved_model = str(self.workdir / f"{safe_name}.sav")
            except Exception as exc:
                if not allow_unsaved:
                    state["status"] = "READY_TO_VERIFY"
                    _atomic_json(self.state_path, state)
                    append_audit(
                        self.audit_path,
                        "STOP_ABORTED_MODEL_SAVE",
                        pid=pid,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    raise ConsoleRuntimeError(
                        f"Refusing to terminate unsaved PID {pid}: {exc}"
                    ) from exc

        # Verify again immediately before requesting engine termination.
        identity = self.process_identity(state)
        termination_method = "PFC program stop via Bridge execute_code"
        graceful_requested = False
        try:
            self.client.execute_code(
                "import itasca\nitasca.command('program stop')\n",
                timeout_seconds=10,
            )
            graceful_requested = True
        except Exception:
            # The engine may close the HTTP response while shutting down.
            graceful_requested = True
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            try:
                self._process_details(pid)
            except ConsoleRuntimeError:
                break
            time.sleep(0.25)
        try:
            self._process_details(pid)
            process_alive = True
        except ConsoleRuntimeError:
            process_alive = False
        if process_alive:
            if not force_if_needed:
                result = {
                    "status": "STOP_PENDING",
                    "pid": pid,
                    "graceful_requested": graceful_requested,
                    "method": termination_method,
                    "saved_model": saved_model,
                }
                _atomic_json(self.state_path, {**state, "status": "READY_TO_VERIFY"})
                return result
            self.process_identity(state)
            try:
                import psutil

                psutil.Process(pid).terminate()
                psutil.Process(pid).wait(timeout=15)
            except Exception as exc:
                raise ConsoleRuntimeError(
                    f"Verified PID {pid} did not terminate: {exc}"
                ) from exc
            termination_method = "verified PID process termination after program stop"

        result = {
            "status": "STOPPED",
            "pid": pid,
            "identity": identity,
            "interrupted_tasks": interrupted,
            "saved_model": saved_model,
            "graceful_requested": graceful_requested,
            "method": termination_method,
            "native_graceful_exit_claimed": graceful_requested and not process_alive
            and termination_method.startswith("PFC program stop"),
        }
        result["port_released"] = not _port_has_listener(self.port)
        state["status"] = "STOPPED"
        state["stopped_utc"] = utc_now()
        state["port_released"] = result["port_released"]
        state["stop_result"] = result
        _atomic_json(self.state_path, state)
        append_audit(
            self.audit_path,
            "STOP_COMPLETED",
            instance_id=state.get("instance_id"),
            pid=pid,
            method=termination_method,
            saved_model=saved_model,
            port_released=result["port_released"],
        )
        return result


def engine_environment_report(engine: Path) -> dict[str, Any]:
    """Read the engine-local Python path used for dependency installation."""
    python = engine.parent / "python310" / "python.exe"
    return {
        "engine": str(engine),
        "engine_python": str(python),
        "engine_python_exists": python.is_file(),
        "dependency_install_command": (
            f'"{python}" -m pip install --user itasca-mcp-bridge'
        ),
    }
