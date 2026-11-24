"""Command-line interface for the PFC Headless Skill."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pfc_headless.common import HeadlessError, atomic_write_json, read_json
from pfc_headless.connection import make_mcp_evidence, verify_connection
from pfc_headless.data import write_verification_report
from pfc_headless.environment import environment_report
from pfc_headless.feedback import (
    approve_feedback,
    ingest_feedback,
    prepare_feedback_run,
)
from pfc_headless.instance import (
    list_instances,
    load_instance,
    runtime_for,
    start_instance,
    stop_instance,
    update_instance,
)
from pfc_headless.project import Project, init_project
from pfc_headless.task_watchdog import diagnose as diagnose_task
from pfc_headless.task_watchdog import diagnose_to_file as diagnose_task_to_file
from pfc_headless.simulation import (
    attach_task,
    execute_planned_run,
    finalize_run,
    interrupt_operation,
    prepare_project_case,
    record_interrupt,
    record_status,
    rebind_run,
    recover_run,
    retry_failed_run,
    run_project_case,
    status_operation,
)


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _project(value: str) -> Project:
    return Project.open(Path(value))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    domains = parser.add_subparsers(dest="domain", required=True)

    environment = domains.add_parser("environment")
    environment_sub = environment.add_subparsers(dest="command", required=True)
    discover = environment_sub.add_parser("discover")
    discover.add_argument("--dimension", type=int, choices=[2, 3])
    discover.add_argument("--root", action="append")
    discover.add_argument("--engine")
    discover.add_argument("--json-out")
    check = environment_sub.add_parser("check")
    check.add_argument("--dimension", type=int, choices=[2, 3])
    check.add_argument("--engine")
    check.add_argument("--root", action="append")
    check.add_argument("--json-out")

    project = domains.add_parser("project")
    project_sub = project.add_subparsers(dest="command", required=True)
    project_init = project_sub.add_parser("init")
    project_init.add_argument("--root", required=True)
    project_init.add_argument("--name", required=True)
    project_init.add_argument("--project-id")
    project_add = project_sub.add_parser("add-case")
    project_add.add_argument("--project", required=True)
    project_add.add_argument("--config", required=True)
    project_add.add_argument("--name")
    project_add.add_argument("--dimension", type=int, choices=[2, 3])
    project_add.add_argument("--case-id", type=int)
    project_add.add_argument("--parameter", action="append", default=[])
    project_add.add_argument("--model")
    project_add.add_argument("--script")
    project_show = project_sub.add_parser("show")
    project_show.add_argument("--project", required=True)

    instance = domains.add_parser("instance")
    instance_sub = instance.add_subparsers(dest="command", required=True)
    instance_start = instance_sub.add_parser("start")
    instance_start.add_argument("--project", required=True)
    instance_start.add_argument("--dimension", type=int, choices=[2, 3], required=True)
    instance_start.add_argument("--port", type=int, default=9001)
    instance_start.add_argument("--engine")
    instance_start.add_argument("--instance-id")
    instance_start.add_argument("--mcp-connection-id")
    instance_list = instance_sub.add_parser("list")
    instance_list.add_argument("--project", required=True)
    instance_health = instance_sub.add_parser("health")
    instance_health.add_argument("--project", required=True)
    instance_health.add_argument("--instance-id", required=True)
    instance_stop = instance_sub.add_parser("stop")
    instance_stop.add_argument("--project", required=True)
    instance_stop.add_argument("--instance-id", required=True)
    instance_stop.add_argument("--save-name")
    instance_stop.add_argument("--no-save", action="store_true")
    instance_stop.add_argument("--allow-unsaved", action="store_true")

    connection = domains.add_parser("connection")
    connection_sub = connection.add_subparsers(dest="command", required=True)
    verify = connection_sub.add_parser("verify")
    verify.add_argument("--project", required=True)
    verify.add_argument("--instance-id", required=True)
    verify.add_argument("--mcp-evidence")
    record = connection_sub.add_parser("record-mcp")
    record.add_argument("--project", required=True)
    record.add_argument("--instance-id", required=True)
    record.add_argument("--tool", required=True)
    record.add_argument("--output-file", required=True)
    record.add_argument("--task-id")
    record.add_argument("--ttl-seconds", type=int, default=600)
    record.add_argument("--json-out", required=True)

    run = domains.add_parser("run")
    run_sub = run.add_subparsers(dest="command", required=True)
    run_start = run_sub.add_parser("start")
    run_start.add_argument("--project", required=True)
    run_start.add_argument("--case-id", type=int, required=True)
    run_start.add_argument("--run-id")
    run_start.add_argument("--parameter", action="append", default=[])
    run_start.add_argument("--sampling-mode", choices=["cycle", "time", "event"])
    run_start.add_argument("--sampling-interval", type=float)
    run_start.add_argument("--capture-contacts", action="store_true")
    run_start.add_argument("--instance-id")
    run_start.add_argument("--pfc-version")
    run_prepare = run_sub.add_parser("prepare")
    run_prepare.add_argument("--project", required=True)
    run_prepare.add_argument("--case-id", type=int, required=True)
    run_prepare.add_argument("--run-id")
    run_prepare.add_argument("--parameter", action="append", default=[])
    run_prepare.add_argument("--sampling-mode", choices=["cycle", "time", "event"])
    run_prepare.add_argument("--sampling-interval", type=float)
    run_prepare.add_argument("--capture-contacts", action="store_true")
    run_prepare.add_argument("--collection-plan")
    run_prepare.add_argument("--instance-id", required=True)
    run_list = run_sub.add_parser("list")
    run_list.add_argument("--project", required=True)
    run_execute = run_sub.add_parser("execute")
    run_execute.add_argument("--project", required=True)
    run_execute.add_argument("--run-id", required=True)
    run_attach = run_sub.add_parser("attach-task")
    run_attach.add_argument("--project", required=True)
    run_attach.add_argument("--run-id", required=True)
    run_attach.add_argument("--evidence", required=True)
    run_state = run_sub.add_parser("status")
    run_state.add_argument("--project", required=True)
    run_state.add_argument("--run-id", required=True)
    run_diagnose = run_sub.add_parser("diagnose")
    run_diagnose.add_argument("--project", required=True)
    run_diagnose.add_argument("--run-id", required=True)
    run_diagnose.add_argument("--pid", type=int, default=None,
                              help="Console PID (default: from run metadata)")
    run_diagnose.add_argument("--interval", type=float, default=8.0,
                              help="seconds between the two progress samples (not a timeout)")
    run_diagnose.add_argument("--json-out", default=None)
    run_record_status = run_sub.add_parser("record-status")
    run_record_status.add_argument("--project", required=True)
    run_record_status.add_argument("--run-id", required=True)
    run_record_status.add_argument("--evidence", required=True)
    run_interrupt = run_sub.add_parser("interrupt")
    run_interrupt.add_argument("--project", required=True)
    run_interrupt.add_argument("--run-id", required=True)
    run_record_interrupt = run_sub.add_parser("record-interrupt")
    run_record_interrupt.add_argument("--project", required=True)
    run_record_interrupt.add_argument("--run-id", required=True)
    run_record_interrupt.add_argument("--evidence", required=True)
    run_finalize = run_sub.add_parser("finalize")
    run_finalize.add_argument("--project", required=True)
    run_finalize.add_argument("--run-id", required=True)
    run_finalize.add_argument("--export-npy", action="store_true")
    run_rebind = run_sub.add_parser("rebind")
    run_rebind.add_argument("--project", required=True)
    run_rebind.add_argument("--run-id", required=True)
    run_rebind.add_argument("--instance-id", required=True)
    run_rebind.add_argument("--approved-by", required=True)
    run_rebind.add_argument("--reason", required=True)
    run_retry = run_sub.add_parser("retry")
    run_retry.add_argument("--project", required=True)
    run_retry.add_argument("--run-id", required=True)
    run_retry.add_argument("--new-run-id")
    run_retry.add_argument("--instance-id")
    run_retry.add_argument("--approved-by", default="agent")
    run_retry.add_argument("--reason", default="Retry after fixing the failed attempt")
    run_recover = run_sub.add_parser("recover")
    run_recover.add_argument("--project", required=True)
    run_recover.add_argument("--run-id", required=True)
    run_recover.add_argument("--reason", required=True)
    run_recover.add_argument("--chunk-frames", type=int, default=10)

    data = domains.add_parser("data")
    data_sub = data.add_subparsers(dest="command", required=True)
    data_verify = data_sub.add_parser("verify")
    data_verify.add_argument("--package", required=True)
    data_verify.add_argument("--json-out", required=True)

    feedback = domains.add_parser("feedback")
    feedback_sub = feedback.add_subparsers(dest="command", required=True)
    feedback_ingest = feedback_sub.add_parser("ingest")
    feedback_ingest.add_argument("--project", required=True)
    feedback_ingest.add_argument("--file", required=True)
    feedback_approve = feedback_sub.add_parser("approve")
    feedback_approve.add_argument("--project", required=True)
    feedback_approve.add_argument("--feedback-id", required=True)
    feedback_approve.add_argument("--approved-by", required=True)
    feedback_approve.add_argument("--rationale", required=True)
    feedback_prepare = feedback_sub.add_parser("prepare-run")
    feedback_prepare.add_argument("--project", required=True)
    feedback_prepare.add_argument("--feedback-id", required=True)
    feedback_prepare.add_argument("--run-id")
    feedback_prepare.add_argument("--instance-id")
    return parser


def _parse_parameters(values: list[str]) -> dict[str, Any]:
    result = {}
    for value in values:
        if "=" not in value:
            raise HeadlessError(f"Parameter must be name=value: {value!r}")
        name, raw = value.split("=", 1)
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        result[name] = parsed
    return result


def main() -> int:
    args = build_parser().parse_args()
    if args.domain == "environment":
        report = environment_report(
            args.dimension,
            engine=args.engine,
            roots=args.root,
        )
        if args.json_out:
            atomic_write_json(Path(args.json_out), report)
        _print(report)
        return 0 if all(item["status"] == "PASS" for item in report["engines"]) else 1
    if args.domain == "project":
        if args.command == "init":
            project = init_project(
                args.root,
                name=args.name,
                project_id=args.project_id,
            )
            _print(project.document)
            return 0
        if args.command == "show":
            project = _project(args.project)
            _print(
                {
                    "project": project.document,
                    "cases": project.list_cases(),
                    "runs": project.list_runs(),
                }
            )
            return 0
        if args.command == "add-case":
            project = _project(args.project)
            record = project.add_case(
                args.config,
                case_name=args.name,
                dimension=args.dimension,
                case_id=args.case_id,
                parameters=_parse_parameters(args.parameter),
                model_path=args.model,
                script_path=args.script,
            )
            _print(record)
            return 0
    if args.domain == "instance":
        project = _project(args.project)
        if args.command == "start":
            _print(
                start_instance(
                    project,
                    dimension=args.dimension,
                    port=args.port,
                    engine=args.engine,
                    instance_id=args.instance_id,
                    mcp_connection_id=args.mcp_connection_id,
                )
            )
            return 0
        if args.command == "list":
            _print(list_instances(project))
            return 0
        if args.command == "health":
            runtime, record = runtime_for(project, args.instance_id)
            _print(
                {
                    "instance": record,
                    "identity": runtime.process_identity(),
                    "preflight": runtime.preflight(),
                }
            )
            return 0
        if args.command == "stop":
            _print(
                stop_instance(
                    project,
                    args.instance_id,
                    save_model=not args.no_save,
                    save_name=args.save_name,
                    allow_unsaved=args.allow_unsaved,
                )
            )
            return 0
    if args.domain == "connection":
        project = _project(args.project)
        instance = load_instance(project, args.instance_id)
        runtime, _record = runtime_for(project, args.instance_id)
        if args.command == "verify":
            result = verify_connection(
                runtime,
                instance,
                mcp_evidence_path=(
                    Path(args.mcp_evidence) if args.mcp_evidence else None
                ),
            )
            update_instance(
                project,
                args.instance_id,
                state=result["state"],
                identity_verified=True,
                health_verified=True,
                execution_verified=True,
                mcp_verified=result["ready"],
                verification=result,
                evidence_status="READY" if result["ready"] else "NOT_VERIFIED",
                mcp_verified_utc=result.get("verified_utc") if result["ready"] else None,
                mcp_evidence_expires_utc=result.get("evidence_expires_utc"),
                identity_fingerprint=result.get("identity_fingerprint")
                or instance.get("identity_fingerprint"),
            )
            _print(result)
            return 0 if result["ready"] else 2
        if args.command == "record-mcp":
            evidence = make_mcp_evidence(
                runtime,
                instance,
                tool=args.tool,
                output=Path(args.output_file).read_text(
                    encoding="utf-8", errors="replace"
                ),
                task_id=args.task_id,
                ttl_seconds=args.ttl_seconds,
            )
            atomic_write_json(Path(args.json_out), evidence)
            _print(evidence)
            return 0
    if args.domain == "run":
        project = _project(args.project)
        if args.command in {"start", "prepare"}:
            sampling = {}
            if args.sampling_mode:
                sampling["mode"] = args.sampling_mode
            if args.sampling_interval is not None:
                sampling["interval"] = args.sampling_interval
            if args.capture_contacts:
                sampling["capture_contacts"] = True
            collection_plan = None
            if getattr(args, "collection_plan", None):
                collection_plan = read_json(Path(args.collection_plan))
            if not args.instance_id:
                raise HeadlessError(
                    "run prepare requires --instance-id; Headless no longer "
                    "starts an unregistered execution process"
                )
            _print(
                prepare_project_case(
                    project,
                    case_id=args.case_id,
                    run_id=args.run_id,
                    parameters=_parse_parameters(args.parameter),
                    sampling=sampling,
                    instance_id=args.instance_id,
                    collection_plan=collection_plan,
                )
            )
            return 0
        if args.command == "list":
            _print(project.list_runs())
            return 0
        if args.command == "execute":
            _print(
                execute_planned_run(
                    project,
                    args.run_id,
                )
            )
            return 0
        if args.command == "attach-task":
            _print(
                attach_task(
                    project,
                    args.run_id,
                    evidence_path=args.evidence,
                )
            )
            return 0
        if args.command == "status":
            _print(status_operation(project, args.run_id))
            return 0
        if args.command == "diagnose":
            run_dir = project.run_root(args.run_id)
            if args.json_out:
                result = diagnose_task_to_file(
                    run_dir,
                    Path(args.json_out),
                    pid=args.pid,
                    interval_s=args.interval,
                )
            else:
                result = diagnose_task(
                    run_dir, pid=args.pid, interval_s=args.interval
                )
            _print(result)
            return 0
        if args.command == "record-status":
            _print(
                record_status(
                    project,
                    args.run_id,
                    evidence_path=args.evidence,
                )
            )
            return 0
        if args.command == "interrupt":
            _print(interrupt_operation(project, args.run_id))
            return 0
        if args.command == "record-interrupt":
            _print(
                record_interrupt(
                    project,
                    args.run_id,
                    evidence_path=args.evidence,
                )
            )
            return 0
        if args.command == "finalize":
            _print(
                finalize_run(
                    project,
                    args.run_id,
                    export_npy=args.export_npy,
                )
            )
            return 0
        if args.command == "retry":
            _print(
                retry_failed_run(
                    project,
                    args.run_id,
                    instance_id=args.instance_id,
                    new_run_id=args.new_run_id,
                    approved_by=args.approved_by,
                    reason=args.reason,
                )
            )
            return 0
        if args.command == "rebind":
            _print(
                rebind_run(
                    project,
                    args.run_id,
                    instance_id=args.instance_id,
                    approved_by=args.approved_by,
                    reason=args.reason,
                )
            )
            return 0
        if args.command == "recover":
            _print(
                recover_run(
                    project,
                    args.run_id,
                    reason=args.reason,
                    chunk_frames=args.chunk_frames,
                )
            )
            return 0
    if args.domain == "data":
        report = write_verification_report(args.package, args.json_out)
        _print(report)
        return 0 if report["status"] == "PASS" else 1
    if args.domain == "feedback":
        project = _project(args.project)
        if args.command == "ingest":
            _print(ingest_feedback(project, args.file))
            return 0
        if args.command == "approve":
            _print(
                approve_feedback(
                    project,
                    args.feedback_id,
                    approved_by=args.approved_by,
                    rationale=args.rationale,
                )
            )
            return 0
        if args.command == "prepare-run":
            _print(
                prepare_feedback_run(
                    project,
                    args.feedback_id,
                    run_id=args.run_id,
                    instance_id=args.instance_id,
                )
            )
            return 0
    raise HeadlessError("Unhandled command")


if __name__ == "__main__":
    raise SystemExit(main())

