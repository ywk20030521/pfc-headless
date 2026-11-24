# Console Runtime

## Official boundary

The Skill only launches `pfc2d9_console.exe` or `pfc3d9_console.exe`. GUI
execution files and autostart hooks are not included. All computation happens
in an independent Console process; capture quality checks and standardization
happen offline after the Console process and do not require PFC. Scientific
analysis and Viewer generation belong to `pfc-scientific-visualization`.

Console runs are managed through Headless Run preparation and the official
MCP tools. The former `run_case.py` and `run start/execute` direct submission
entry points are preparation-only or disabled and do not submit tasks.

The Console engine accepts the prepared script path through `--run`; stdin is
not redirected.

## Dependency preflight

The bridge transport needs the `itasca-mcp-bridge` package in the Python
environment visible to the Console build. Locate the engine-local interpreter:

```powershell
& "<python310>\python.exe" "<skill>\scripts\console_cli.py" `
  environment --dimension 3
```

Install or verify the dependency with the command reported by that output:

```powershell
& "<engine>\python310\python.exe" -m pip install --user itasca-mcp-bridge
```

## Start and verify

```powershell
& "<python>" "<skill>\scripts\console_cli.py" start `
  --workdir "<project>" --dimension 3 --port 9001

& "<python>" "<skill>\scripts\console_cli.py" health `
  --workdir "<project>" --dimension 3 --port 9001
```

`start` refuses GUI builds and records the engine path, PID, port, launch
arguments, health response, and `/execute_code` probe in
`.pfc-console/runtime.json`. The probe must report the matching Console
executable and `runtime_mode=console`.

Runtime readiness is finalized by the Connection Manager. `/health` alone is
not `READY`; a real `itasca-mcp` execution probe must also be recorded.

## Prepare one Run

```powershell
& "<python>" "<skill>\scripts\headless.py" run prepare `
  --project "<project>" --case-id 0 --run-id run_001 `
  --instance-id pfc3d_9001
```

The Agent Host calls `itasca_execute_task` and binds evidence with
`run attach-task`. After the MCP task completes, `run finalize` performs local
validation and standardization without starting PFC or contacting the Bridge.

## Stop

```powershell
& "<python>" "<skill>\scripts\console_cli.py" stop `
  --workdir "<project>\runtime" --dimension 3 --port 9001
```

Stop records whether the port was released. A state file with no PID is not
used as permission to terminate an unrelated process.

Before termination it verifies PID, executable and command line, checks active
tasks, interrupts them when present, and requests `model save`. It then asks PFC
to execute `program stop`. Verified PID termination is used only as a disclosed
fallback and is not reported as a native graceful exit.

## Dynamic entities and dimensions

- The FISH writer samples every real frame using the configured Cycle stride.
- PFC2D z values are written as zero through `_pfc_live_capture_z`; they are not
  taken from `comp.z(Vec2)`.
- PFC3D keeps the real z component.
- Each frame owns an explicit Ball ID set. Added IDs include the measured
  radius in the frame where they first appear.
- PFC2D line load is reported as N/m. It is never labelled as a 3D stress in Pa.

## Failure handling

A task whose state is not `completed` is a failure even if a partial result
file exists. A failed integrity check blocks post-processing. Never bypass a
Console failure by starting a GUI process.
