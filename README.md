# PFC Headless

PFC Headless is the management layer between an agent-facing request, the
ITASCA MCP/Bridge execution path, and a scientific visualization consumer.

It owns:

- verified PFC2D/PFC3D Console discovery;
- isolated Console instance lifecycle;
- process, Bridge and MCP execution verification;
- Project, Case and unique Run management;
- script-embedded PFC data capture;
- immutable raw evidence, standardization and data-quality checks;
- metadata, manifests, hashes and downstream delivery;
- Analysis Feedback review and new-Run planning.

It does not replace `itasca-mcp`, `itasca-mcp-bridge`, or
`pfc-scientific-visualization`. It never launches a GUI PFC build and never
creates Viewer, ECharts, Three.js or publication artifacts.

## Repository layout

```text
pfc-headless/
|-- SKILL.md
|-- README.md
|-- scripts/
|   |-- headless.py
|   |-- console_runtime.py
|   |-- run_case.py
|   |-- capture_case.py
|   `-- pfc_headless/
|       |-- environment.py
|       |-- instance.py
|       |-- connection.py
|       |-- project.py
|       |-- simulation.py
|       |-- data.py
|       `-- feedback.py
|-- schema/
|-- references/
|-- tests/
|-- reports/
`-- acceptance/
```

## Prerequisites

- Windows with a licensed Itasca PFC 9.x installation.
- A verified `pfc*d*_console.exe`, not a GUI executable.
- `itasca-mcp-bridge` installed in the Python environment visible to PFC.
- `psutil` installed in the same environment for safe process identity checks.
- An `itasca-mcp` configuration that points to the target Bridge URL.

Check both dimensions:

```powershell
& "<engine-python>" "<skill>\scripts\headless.py" environment check `
  --dimension 2 --json-out "<skill>\reports\environment_pfc2d.json"

& "<engine-python>" "<skill>\scripts\headless.py" environment check `
  --dimension 3 --json-out "<skill>\reports\environment_pfc3d.json"
```

Use an unsandboxed terminal if the sandbox hides the user site-packages
directory.

## Project workflow

```powershell
& "<python>" "<skill>\scripts\headless.py" project init `
  --root "<project>" --name "My PFC project"

& "<python>" "<skill>\scripts\headless.py" project add-case `
  --project "<project>" --config "<case>.json" --dimension 3
```

Start an isolated instance:

```powershell
& "<python>" "<skill>\scripts\headless.py" instance start `
  --project "<project>" --dimension 3 --port 9001 `
  --instance-id pfc3d_9001
```

Connection readiness has four evidence layers:

1. registered PID, executable and command-line identity;
2. Bridge `/health` with `runtime_mode=console`;
3. Bridge execution of a PFC probe;
4. an actual `itasca-mcp` probe that echoes the current instance nonce.

The evidence validator also compares the current identity fingerprint and
rejects expired probes or evidence from a previous instance.

Prepare a Run and bind its official MCP task:

```powershell
& "<python>" "<skill>\scripts\headless.py" run prepare `
  --project "<project>" --case-id 0 --run-id run_001 `
  --instance-id pfc3d_9001

# Agent Host: call itasca_execute_task with the returned arguments.
& "<python>" "<skill>\scripts\headless.py" run attach-task `
  --project "<project>" --run-id run_001 --evidence "<execute-evidence>.json"

& "<python>" "<skill>\scripts\headless.py" run status `
  --project "<project>" --run-id run_001

# Agent Host: call itasca_check_task_status, save the response evidence.
& "<python>" "<skill>\scripts\headless.py" run record-status `
  --project "<project>" --run-id run_001 --evidence "<status-evidence>.json"

& "<python>" "<skill>\scripts\headless.py" run interrupt `
  --project "<project>" --run-id run_001

& "<python>" "<skill>\scripts\headless.py" run record-interrupt `
  --project "<project>" --run-id run_001 --evidence "<interrupt-evidence>.json"

& "<python>" "<skill>\scripts\headless.py" run finalize `
  --project "<project>" --run-id run_001

& "<python>" "<skill>\scripts\headless.py" run recover `
  --project "<project>" --run-id run_001 --reason "interrupted task"
```

Headless emits MCP operation descriptors but never submits Run tasks itself.
`run status` and `run interrupt` resolve the Run's instance and MCP connection
automatically; no user-supplied port is accepted. A timeout is recorded as
`TIMEOUT_UNKNOWN` and is never automatically resubmitted.

## Data collection

The embedded collector supports:

- a versioned allow-listed `collection_plan`;
- Cycle-stride sampling;
- mechanical-time interval sampling;
- solve/fracture event sampling;
- Ball position, radius, velocity and angular velocity;
- Wall vertices and platen data;
- optional contact ID, endpoints, model and global force;
- native Histories without inferred physical meaning;
- optional fracture/DFN event capture.

Unavailable fields remain `NOT_CAPTURED`; PFC2D z remains a numeric embedding,
not a fabricated physical thickness.

## Delivery and verification

Each Run produces:

```text
deliveries/<run_id>/
|-- delivery_manifest.json      # Visualization contract
|-- experiment.json
|-- metadata.json               # Complete package metadata
|-- manifest.json               # File index and hashes
|-- validation_report.json      # Independent quality checks
|-- conversion_report.json
|-- schema/
`-- cases/
```

Verify outside the immutable package:

```powershell
& "<python>" "<skill>\scripts\headless.py" data verify `
  --package "<project>\deliveries\run_001" `
  --json-out "<project>\analysis\run_001_verification.json"
```

The downstream interface remains:

```text
pfc.standardized-experiment@1.0.0
```

The scientific Skill consumes this tree read-only and writes analysis elsewhere.

## Feedback loop

```powershell
& "<python>" "<skill>\scripts\headless.py" feedback ingest `
  --project "<project>" --file "<findings>.json"

& "<python>" "<skill>\scripts\headless.py" feedback approve `
  --project "<project>" --feedback-id "<id>" `
  --approved-by "<reviewer>" --rationale "<reason>"

& "<python>" "<skill>\scripts\headless.py" feedback prepare-run `
  --project "<project>" --feedback-id "<id>" --run-id run_002

& "<python>" "<skill>\scripts\headless.py" run execute `
  --project "<project>" --run-id run_002
```

Feedback never modifies the source Run. Arbitrary feedback code is forbidden;
model overrides must be scalar parameters declared by the Case.
`run execute` now prepares the MCP operation; it does not start a task.

## Safe stop

```powershell
& "<python>" "<skill>\scripts\headless.py" instance stop `
  --project "<project>" --instance-id pfc3d_9001 `
  --save-name "safe_stop"
```

The stop path checks active tasks, requests `model save`, re-verifies the
registered PID/executable/command line, and requests PFC `program stop`. If the
verified PID remains alive, the audit records that a fallback process
termination was used; it is not reported as a native graceful exit.

## Tests

```powershell
& "<engine-python>" "<skill>\scripts\run_tests.py"
```

See `reports/VALIDATION_REPORT.md`, `reports/CAPABILITY_MATRIX.md`,
`CONSOLE_ACCEPTANCE.md` and `DATA_INTEGRITY_REPORT.md` for the distinction
between unit tests, simulated tests and real PFC acceptance.

