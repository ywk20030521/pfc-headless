"""PFC Console discovery and dependency diagnostics."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from .common import HeadlessError, file_record, utc_now


CONSOLE_MARKERS = (
    b"Console Terminal",
    b"GUI/PLOT command not supported in console interface",
)
PRODUCT_MARKERS = {
    2: b"PFC2D",
    3: b"PFC3D",
}


def _registry_roots() -> list[Path]:
    roots: list[Path] = []
    if os.name != "nt":
        return roots
    try:
        import winreg

        keys = (
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        )
        for hive, relative in keys:
            try:
                with winreg.OpenKey(hive, relative) as parent:
                    count = winreg.QueryInfoKey(parent)[0]
                    for index in range(count):
                        try:
                            name = winreg.EnumKey(parent, index)
                            with winreg.OpenKey(parent, name) as item:
                                values = {}
                                for value_name in ("DisplayName", "InstallLocation", "DisplayIcon"):
                                    try:
                                        values[value_name] = str(
                                            winreg.QueryValueEx(item, value_name)[0]
                                        )
                                    except OSError:
                                        pass
                                display = values.get("DisplayName", "")
                                if "itasca" not in display.lower() and "pfc" not in display.lower():
                                    continue
                                location = values.get("InstallLocation")
                                icon = values.get("DisplayIcon", "").strip('"')
                                if location:
                                    roots.append(Path(location))
                                if icon:
                                    roots.append(Path(icon).parent)
                        except OSError:
                            continue
            except OSError:
                continue
    except ImportError:
        pass
    return roots


def default_search_roots() -> list[Path]:
    candidates = [
        Path(r"D:\Itasca"),
        Path(r"C:\Itasca"),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Itasca",
        Path(os.environ.get("ProgramW6432", r"C:\Program Files")) / "Itasca",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Itasca",
    ]
    candidates.extend(_registry_roots())
    for env_name in ("PFC2D_CONSOLE", "PFC3D_CONSOLE"):
        value = os.environ.get(env_name)
        if value:
            candidates.append(Path(value).parent)
    result = []
    seen = set()
    for path in candidates:
        if not str(path):
            continue
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        result.append(resolved)
    return result


def infer_version(path: Path) -> tuple[str | None, str]:
    for part in (path.parent.name, *path.parts):
        match = re.search(r"PFC(\d{3,4})", part, re.IGNORECASE)
        if match:
            digits = match.group(1)
            if len(digits) == 3:
                return f"{digits[0]}.{digits[1]}.{digits[2]}", f"path segment {part}"
            return f"{digits[0]}.{digits[1:]}", f"path segment {part}"
    match = re.search(r"pfc([23])d(\d+)_console", path.name, re.IGNORECASE)
    if match:
        return f"{match.group(2)}.x", "executable filename"
    return None, "not_inferred"


def classify_console_executable(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise HeadlessError(f"Engine executable is missing: {path}")
    if "gui" in path.name.lower():
        raise HeadlessError(
            f"GUI PFC executable is forbidden; a Console build is required: {path}"
        )
    if path.suffix.lower() != ".exe":
        raise HeadlessError(f"Engine is not a Windows executable: {path}")
    payload = path.read_bytes()
    products = [
        dimension for dimension, marker in PRODUCT_MARKERS.items() if marker in payload
    ]
    if len(products) != 1:
        raise HeadlessError(
            f"Executable does not prove one PFC product identity: {path}"
        )
    marker_hits = [marker.decode("ascii") for marker in CONSOLE_MARKERS if marker in payload]
    if not marker_hits:
        raise HeadlessError(
            f"Executable lacks verified Console markers and is rejected: {path}"
        )
    dimension = products[0]
    version, version_source = infer_version(path)
    python = path.parent / "python310" / "python.exe"
    return {
        "engine_type": f"PFC{dimension}D_CONSOLE",
        "dimension": dimension,
        "executable_path": str(path),
        "install_root": str(path.parent.parent),
        "engine_version": version,
        "version_source": version_source,
        "console_marker_hits": marker_hits,
        "identity_basis": "product and console markers inside executable",
        "engine_python": str(python),
        "engine_python_exists": python.is_file(),
        "file": file_record(path),
    }


def _iter_executable_files(roots: Iterable[Path]) -> Iterable[Path]:
    seen = set()
    for root in roots:
        if root.is_file():
            candidates = [root]
        else:
            candidates = root.rglob("*.exe")
        for candidate in candidates:
            lower = candidate.name.lower()
            if "pfc" not in lower or "console" not in lower:
                continue
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            yield resolved


def discover_console_engines(
    *,
    dimension: int | None = None,
    roots: Iterable[str | Path] | None = None,
) -> list[dict[str, Any]]:
    if dimension not in {None, 2, 3}:
        raise ValueError("dimension must be 2, 3 or None")
    search_roots = [Path(value) for value in roots] if roots else default_search_roots()
    results: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    seen = set()
    for path in _iter_executable_files(search_roots):
        try:
            record = classify_console_executable(path)
        except (HeadlessError, OSError) as exc:
            rejected.append({"path": str(path), "reason": str(exc)})
            continue
        if dimension is not None and record["dimension"] != dimension:
            continue
        key = (record["dimension"], record["file"]["sha256"])
        if key in seen:
            continue
        seen.add(key)
        results.append(record)
    results.sort(
        key=lambda item: (
            item["dimension"],
            item.get("engine_version") or "",
            item["executable_path"].lower(),
        )
    )
    if not results:
        suffix = f" for PFC{dimension}D" if dimension else ""
        raise HeadlessError(
            f"No verified PFC Console executable found{suffix}. "
            "Set PFC2D_CONSOLE/PFC3D_CONSOLE or pass an explicit engine. "
            f"Rejected candidates: {json.dumps(rejected)}"
        )
    return results


def find_console_engine(
    dimension: int,
    explicit: str | Path | None = None,
) -> Path:
    """Compatibility wrapper returning one verified Console executable."""
    if explicit:
        try:
            record = classify_console_executable(Path(explicit))
        except HeadlessError as exc:
            raise ValueError(str(exc)) from exc
        if record["dimension"] != dimension:
            raise HeadlessError(
                f"Engine is {record['engine_type']}, not PFC{dimension}D Console"
            )
        return Path(record["executable_path"])
    env_name = "PFC2D_CONSOLE" if dimension == 2 else "PFC3D_CONSOLE"
    if os.environ.get(env_name):
        record = classify_console_executable(Path(os.environ[env_name]))
        if record["dimension"] == dimension:
            return Path(record["executable_path"])
    engines = discover_console_engines(dimension=dimension)
    return Path(engines[-1]["executable_path"])


def _run_engine_python(python: Path, code: str, timeout: float = 15.0) -> dict[str, Any]:
    if not python.is_file():
        return {
            "status": "FAIL",
            "error": f"Engine-local Python is missing: {python}",
        }
    completed = subprocess.run(
        [str(python), "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def bridge_dependency_report(engine: dict[str, Any]) -> dict[str, Any]:
    python = Path(engine["engine_python"])
    code = (
        "import importlib.metadata as m, json, site, psutil; "
        "from pathlib import Path; "
        "u=site.getusersitepackages(); "
        "print(json.dumps({'version':m.version('itasca-mcp-bridge'),"
        "'psutil_version':psutil.__version__,"
        "'user_site':u,'user_site_exists':Path(u).is_dir()}))"
    )
    result = _run_engine_python(python, code)
    if result["status"] == "PASS":
        try:
            details = json.loads(result["stdout"])
        except json.JSONDecodeError:
            details = {"raw": result["stdout"]}
        result["details"] = details
        result["install_command"] = f'"{python}" -m pip install --user itasca-mcp-bridge'
        result["note"] = (
            "If a sandbox hides the user site-packages directory, rerun the "
            "environment check outside that sandbox before changing dependencies."
        )
    return result


def mcp_configuration_report() -> dict[str, Any]:
    bridge_url = os.environ.get("ITASCA_MCP_BRIDGE_URL")
    paths = [
        Path.home() / ".codex" / "config.toml",
        Path.home() / ".codex" / "mcp.json",
    ]
    hits = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "itasca" in text.lower():
            hits.append(str(path))
    status = "PASS" if bridge_url or hits else "NOT_CONFIGURED"
    return {
        "status": status,
        "bridge_url_environment": bridge_url,
        "configuration_files_with_itasca": hits,
        "note": (
            "MCP process routing is one Bridge URL per MCP server. Multiple "
            "engines require separate configured MCP processes or a verified router."
        ),
    }


def environment_report(
    dimension: int | None = None,
    *,
    engine: str | Path | None = None,
    roots: Iterable[str | Path] | None = None,
) -> dict[str, Any]:
    if engine:
        if dimension is None:
            raise HeadlessError("dimension is required with an explicit engine")
        record = classify_console_executable(Path(engine))
        if record["dimension"] != dimension:
            raise HeadlessError(
                f"Explicit engine is {record['engine_type']}, expected PFC{dimension}D"
            )
        engines = [record]
    else:
        engines = discover_console_engines(dimension=dimension, roots=roots)
    reports = []
    for item in engines:
        bridge = bridge_dependency_report(item)
        reports.append(
            {
                **item,
                "bridge_dependency": bridge,
                "status": "PASS" if bridge["status"] == "PASS" else "DEPENDENCY_FAIL",
            }
        )
    return {
        "schema_version": "1.0.0",
        "generated_utc": utc_now(),
        "requested_dimension": dimension,
        "engines": reports,
        "mcp": mcp_configuration_report(),
        "console_only": True,
        "gui_accepted": False,
    }

