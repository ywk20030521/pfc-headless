"""Project, Case and Run record management."""
from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

from .common import (
    HeadlessError,
    append_audit,
    atomic_write_json,
    atomic_write_text,
    copy_new_file,
    file_record,
    new_id,
    read_json,
    sha256_file,
    substitute_parameters,
    utc_now,
    validate_id,
)
from .contracts import make_case, make_project, make_run, validate_document
from .authorization import RunAuthorization
from .collection import apply_plan_to_config, normalize_collection_plan


PROJECT_FILE = "project.json"
RUNS_DIR = "runs"
CASES_DIR = "cases"
DELIVERIES_DIR = "deliveries"
FEEDBACK_DIR = "analysis/feedback"
INSTANCES_DIR = "instances"


class Project:
    def __init__(self, root: Path, document: dict[str, Any]):
        self.root = root.resolve()
        self.document = document

    @classmethod
    def open(cls, root: str | Path) -> "Project":
        project_root = Path(root).resolve()
        path = project_root / PROJECT_FILE
        if not path.is_file():
            raise HeadlessError(f"Not a Headless project (project.json missing): {project_root}")
        document = read_json(path)
        validate_document("project", document)
        return cls(project_root, document)

    @property
    def audit_path(self) -> Path:
        return self.root / "audit" / "project_audit.jsonl"

    def save(self) -> None:
        validate_document("project", self.document)
        atomic_write_json(self.root / PROJECT_FILE, self.document)

    def list_cases(self) -> list[dict[str, Any]]:
        records = []
        for reference in self.document["cases"]:
            path = self.root / reference["path"]
            record = read_json(path)
            validate_document("case", record)
            records.append(record)
        return sorted(records, key=lambda item: item["case_id"])

    def get_case(self, case_id: int) -> dict[str, Any]:
        for case in self.list_cases():
            if int(case["case_id"]) == int(case_id):
                return case
        raise HeadlessError(f"Case {case_id} does not exist")

    def add_case(
        self,
        config_path: str | Path,
        *,
        case_name: str | None = None,
        dimension: int | None = None,
        case_id: int | None = None,
        parameters: dict[str, Any] | None = None,
        model_path: str | Path | None = None,
        script_path: str | Path | None = None,
    ) -> dict[str, Any]:
        source = Path(config_path).resolve()
        config = read_json(source)
        if case_id is None:
            case_id = max(
                (int(item["case_id"]) for item in self.document["cases"]),
                default=-1,
            ) + 1
        case_id = int(case_id)
        if any(int(item["case_id"]) == case_id for item in self.document["cases"]):
            raise HeadlessError(f"Case {case_id} already exists")
        if dimension is None:
            dimension = self._infer_dimension(config)
        collection = {
            "mode": str(config.get("sample_mode", "cycle")),
            "interval": float(
                config.get(
                    "sample_interval",
                    config.get(
                        "sample_interval_time",
                        config.get("sample_stride_cycles", 1),
                    ),
                )
            ),
            "capture_contacts": bool(config.get("capture_contacts", False)),
            "fracture_observer": bool(config.get("fracture_observer", False)),
            "history_names": list(config.get("history_names") or []),
        }
        configured_plan = config.get("collection_plan")
        collection_plan = normalize_collection_plan(
            configured_plan if isinstance(configured_plan, dict) else None,
            dimension=int(dimension),
            sampling=collection,
            case_config=config,
            seed_from_case=True,
        )
        case_dir = self.root / CASES_DIR / f"case_{case_id}"
        if case_dir.exists():
            raise FileExistsError(f"Case directory already exists: {case_dir}")
        case_dir.mkdir(parents=True)
        stored_config = case_dir / "case_config.json"
        atomic_write_text(
            stored_config,
            json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        )
        record = make_case(
            case_id=case_id,
            case_name=case_name or source.stem,
            engine_dimension=int(dimension),
            config_path=f"{CASES_DIR}/case_{case_id}/case_config.json",
            parameters=parameters,
            data_collection_config=collection,
            collection_plan=collection_plan,
            model_path=str(Path(model_path).resolve()) if model_path else None,
            script_path=str(Path(script_path).resolve()) if script_path else None,
        )
        validate_document("case", record)
        atomic_write_json(case_dir / "case.json", record)
        self.document["cases"].append(
            {"case_id": case_id, "path": f"{CASES_DIR}/case_{case_id}/case.json"}
        )
        self.save()
        append_audit(
            self.audit_path,
            "CASE_ADDED",
            case_id=case_id,
            source_config=str(source),
            config_sha256=sha256_file(stored_config),
        )
        return record

    @staticmethod
    def _infer_dimension(config: dict[str, Any]) -> int:
        explicit = config.get("engine_dimension", config.get("dimension"))
        if explicit is not None:
            value = int(explicit)
            if value in {2, 3}:
                return value
        text = json.dumps(config, ensure_ascii=False).lower()
        if "pfc3d" in text:
            return 3
        if "pfc2d" in text:
            return 2
        raise HeadlessError(
            "Cannot infer engine dimension from Case; pass --dimension explicitly"
        )

    def new_run(
        self,
        case_id: int,
        *,
        run_id: str | None = None,
        parameters: dict[str, Any] | None = None,
        sampling: dict[str, Any] | None = None,
        instance_id: str | None = None,
        collection_plan: dict[str, Any] | None = None,
        feedback_id: str | None = None,
        authorization: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        case = self.get_case(case_id)
        run_id = validate_id(run_id or new_id("run"), "run_id")
        run_root = self.root / RUNS_DIR / run_id
        if run_root.exists():
            raise FileExistsError(f"Run already exists: {run_id}")
        run_root.mkdir(parents=True)
        committed = False
        try:
            input_root = run_root / "input"
            input_root.mkdir()
            raw_config = read_json(self.root / case["config_path"])
            effective_parameters = {
                **case.get("parameters", {}),
                **(parameters or {}),
            }
            rendered = substitute_parameters(
                copy.deepcopy(raw_config), effective_parameters
            )
            effective_sampling = {
                **case.get("data_collection_config", {}),
                **(sampling or {}),
            }
            explicit_plan = collection_plan or (sampling or {}).get("collection_plan")
            selected_plan = explicit_plan or case.get("collection_plan")
            effective_plan = normalize_collection_plan(
                selected_plan if isinstance(selected_plan, dict) else None,
                dimension=int(case["engine_dimension"]),
                sampling=effective_sampling,
                add_sampling_extras=explicit_plan is None,
                case_config=rendered,
                seed_from_case=explicit_plan is None,
            )
            rendered = apply_plan_to_config(rendered, effective_plan)
            effective_sampling["collection_plan"] = effective_plan
            rendered["run_id"] = run_id
            rendered["case_id"] = int(case_id)
            rendered["headless"] = {
                "project_id": self.document["project_id"],
                "case_id": int(case_id),
                "run_id": run_id,
                "parameters": effective_parameters,
                "source_case_config": case["config_path"],
            }
            config_snapshot = input_root / "config.json"
            atomic_write_text(
                config_snapshot,
                json.dumps(rendered, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            )
            snapshots = [
                {
                    "kind": "case_config",
                    "source": str(self.root / case["config_path"]),
                    "snapshot": "config.json",
                    "size_bytes": config_snapshot.stat().st_size,
                    "sha256": sha256_file(config_snapshot),
                }
            ]
            for kind, value in (
                ("model", case.get("model_path")),
                ("script", case.get("script_path")),
            ):
                if value:
                    source = Path(value)
                    if not source.is_absolute():
                        source = self.root / source
                    destination = input_root / f"{kind}_{source.name}"
                    record = copy_new_file(source, destination)
                    record["kind"] = kind
                    record["snapshot"] = destination.name
                    snapshots.append(record)
            project_dir = rendered.get("project_dir")
            source_files = rendered.get("source_files", {})
            if source_files and not project_dir:
                raise HeadlessError(
                    "Case declares source_files but has no project_dir"
                )
            missing_sources = []
            for name, expected_hash in source_files.items():
                if not project_dir:
                    break
                source = (Path(project_dir) / name).resolve()
                if not source.is_file():
                    missing_sources.append(name)
                    continue
                if expected_hash and len(str(expected_hash)) == 64:
                    actual_hash = sha256_file(source)
                    if actual_hash != str(expected_hash).lower():
                        raise HeadlessError(
                            f"Source file hash mismatch: {name}"
                        )
                destination = input_root / f"source_{source.name}"
                if not destination.exists():
                    record = copy_new_file(source, destination)
                    record["kind"] = "source_file"
                    record["snapshot"] = destination.name
                    snapshots.append(record)
            if missing_sources:
                raise HeadlessError(
                    f"Declared source_files are missing under project_dir={project_dir}: "
                f"{sorted(missing_sources)}. Resolved paths: "
                f"{[str((Path(str(project_dir)) / n).resolve()) for n in sorted(missing_sources)]}"
                )
            atomic_write_json(
                input_root / "snapshot_manifest.json",
                {
                    "run_id": run_id,
                    "case_id": int(case_id),
                    "parameters": effective_parameters,
                    "data_collection_config": effective_sampling,
                    "collection_plan": effective_plan,
                    "missing_inputs": [],
                    "files": snapshots,
                    "created_utc": utc_now(),
                },
            )
            output_path = f"{DELIVERIES_DIR}/{run_id}"
            record = make_run(
                run_id=run_id,
                case_id=case_id,
                instance_id=instance_id,
                input_snapshot="input",
                script_version=f"sha256:{snapshots[0]['sha256']}",
                output_path=output_path,
            )
            record.update(
                {
                    "execution_nonce": new_id("exec"),
                    "collection_plan": effective_plan,
                    "feedback_id": feedback_id,
                    "preflight": rendered.get("preflight") or {"status": "NOT_RUN"},
                }
            )
            if authorization is not None:
                auth = RunAuthorization.from_mapping(authorization)
                auth.validate()
                record["authorization"] = auth.to_record()
            validate_document("run", record)
            atomic_write_json(run_root / "metadata" / "run.json", record)
            append_audit(
                self.audit_path,
                "RUN_CREATED",
                run_id=run_id,
                case_id=int(case_id),
                input_snapshot="input",
            )
            committed = True
            return {
                "record": record,
                "run_root": run_root,
                "config": rendered,
                "config_path": config_snapshot,
            }
        except BaseException:
            if not committed:
                shutil.rmtree(run_root, ignore_errors=True)
            raise

    def run_root(self, run_id: str) -> Path:
        validate_id(run_id, "run_id")
        root = self.root / RUNS_DIR / run_id
        if not root.is_dir():
            raise HeadlessError(f"Run does not exist: {run_id}")
        return root

    def get_run(self, run_id: str) -> dict[str, Any]:
        record = read_json(self.run_root(run_id) / "metadata" / "run.json")
        validate_document("run", record)
        return record

    def update_run(self, run_id: str, **updates: Any) -> dict[str, Any]:
        root = self.run_root(run_id)
        path = root / "metadata" / "run.json"
        record = read_json(path)
        previous_status = record.get("task_status")
        record.update(updates)
        if record.get("task_status") in {
            "COMPLETED",
            "FAILED",
            "INTERRUPTED",
            "INVALID",
        }:
            record["end_time"] = record.get("end_time") or utc_now()
        validate_document("run", record)
        atomic_write_json(path, record)
        if record.get("task_status") != previous_status:
            append_audit(
                self.audit_path,
                "RUN_STATUS_CHANGED",
                run_id=run_id,
                from_status=previous_status,
                to_status=record.get("task_status"),
                task_id=record.get("mcp_task_id"),
            )
        return record

    def list_runs(self) -> list[dict[str, Any]]:
        records = []
        root = self.root / RUNS_DIR
        if not root.is_dir():
            return records
        for path in sorted(root.glob("*/metadata/run.json")):
            records.append(read_json(path))
        return records


def init_project(
    root: str | Path,
    *,
    name: str,
    project_id: str | None = None,
) -> Project:
    project_root = Path(root).resolve()
    project_path = project_root / PROJECT_FILE
    if project_path.exists():
        raise FileExistsError(f"Project already exists: {project_path}")
    project_root.mkdir(parents=True, exist_ok=True)
    for name_ in (
        CASES_DIR,
        RUNS_DIR,
        DELIVERIES_DIR,
        INSTANCES_DIR,
        FEEDBACK_DIR,
        "logs",
        "audit",
    ):
        (project_root / name_).mkdir(parents=True, exist_ok=True)
    document = make_project(
        project_id=validate_id(project_id or new_id("project"), "project_id"),
        project_name=name,
        project_root=str(project_root),
    )
    validate_document("project", document)
    atomic_write_json(project_path, document)
    project = Project(project_root, document)
    append_audit(project.audit_path, "PROJECT_CREATED", project_root=str(project_root))
    return project

