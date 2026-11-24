# Task Management

## Agent-orchestrated execution

Headless is responsible for Run preparation, task binding, evidence validation,
state reconciliation, recovery, validation and delivery. The Agent Host is
responsible for calling the official MCP tools:

```text
itasca_execute_task
itasca_check_task_status
itasca_interrupt_task
```

The normal sequence is:

```text
run prepare -> MCP execute -> run attach-task
-> MCP status -> run record-status
-> run finalize
```

`run status` and `run interrupt` return MCP operation descriptors after
resolving the Run's registered instance and MCP connection. They never accept an
arbitrary port.

## Short and long jobs

- `execute_code` is synchronous, cannot be interrupted, and is capped by the
  installed Bridge. Use it only for short probes.
- `execute_task` is tracked and supports status polling and interruption. Use
  it for solves and data-production scripts.

The stored mapping is `Run.mcp_task_id`. A task ID is not a Run ID.

## Timeout and progress-aware diagnosis

A fixed wall-clock timeout must NOT be used to decide whether a solve is hung.
A legitimate PFC solve can take far longer than a quick one; "it has been
running 30 minutes" says nothing about blocking. Use objective progress
signals instead:

```bash
python scripts/headless.py run diagnose \
  --project <project> --run-id <run> --interval 8 --json-out diag.json
```

`run diagnose` samples twice (the `--interval` is only the sampling gap, not a
timeout) and checks: process liveness, process CPU-time growth, output bytes /
newest mtime under `data/raw`, and captured frame-row growth. It classifies:

- `COMPLETED` — terminal run status (no sampling needed);
- `PROCESS_DEAD` — the Console PID is gone;
- `RUNNING` — CPU or output/frames advanced: the model is still solving, keep waiting;
- `STALLED` — process alive but **no** signal advanced: likely blocked, consider interrupt;
- `UNKNOWN` — insufficient telemetry: keep waiting or add evidence, never guess.

The watchdog is advisory: it never kills or mutates a task. Attach its JSON to
`record-status` / `interrupt` decisions. If no process telemetry is available
and output is unchanged, it returns `UNKNOWN` rather than declaring a stall —
a conservative rule that avoids killing slow but healthy solves.

On a genuine timeout:

1. query task history/status **and** run `diagnose`;
2. if completion is unresolved, set `TIMEOUT_UNKNOWN`;
3. preserve the Run and logs;
4. never auto-submit the same non-idempotent script.

## Interrupt

`run interrupt` emits the official MCP interrupt request. The Agent records the
returned evidence with `run record-interrupt`, then records the terminal state
with `run record-status`. Partial files remain available for explicit recovery;
they are not treated as complete.

## Recovery

`run recover` scans current capture rows, reports malformed tails, keeps partial
evidence separate and never generates scientific metrics. The result is only
`READY_FOR_EXPLICIT_CONSUMPTION`; it is not a completed standardized delivery.

