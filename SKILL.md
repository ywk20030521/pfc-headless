---
name: pfc-headless
description: Manage PFC2D/PFC3D Console environments, instances, projects, simulation Runs, embedded data capture, immutable standardized delivery and analysis-feedback reruns through itasca-mcp. Use for PFC 无头运行、Console 环境发现、Bridge/MCP 连接验证、任务中断恢复、原始数据质检、标准数据包交付或反馈再仿真.
metadata:
  short-description: Traceable PFC Console simulation and data production
---

# PFC Headless

Own the workflow from verified PFC Console discovery to an immutable,
scientifically consumable experiment package. This Skill is the management
layer; `itasca-mcp` and `itasca-mcp-bridge` remain the execution layer, while
`pfc-scientific-visualization` owns analysis, charts, Viewer and publication.

## Non-negotiable rules

- Accept only validated PFC2D/PFC3D Console executables. Never launch or fall
  back to a GUI build.
- Discover Console identity from executable content and runtime probes, not
  only from a fixed filename.
- Use one MCP server process per configured Bridge URL. Do not assume a single
  MCP process automatically routes across multiple engines.
- Launch Console with the official `--run <script>` arguments. Never feed
  commands through redirected stdin.
- Give every simulation a unique Run ID. Historical input, raw data and
  deliveries are immutable.
- Prefer script-embedded capture. Do not reconstruct dynamic particle data from
  later model state or interpolate missing frames.
- Preserve PFC2D as planar data. Its numeric z is not physical thickness.
- Mark missing channels `NOT_CAPTURED`, unsupported channels `NOT_SUPPORTED`,
  and invalid checks `INVALID`; never zero-fill to make a package pass.
- In PFC2D, default `load_axis` to `y` (all 2D wall z positions are zero), and
  treat bond-break FISH events as the fracture record when `itasca.dfn` is
  unavailable (`fracture_catalog_status=NOT_SUPPORTED`).
- Never resubmit a timed-out non-idempotent task automatically. Query status
  first and record `TIMEOUT_UNKNOWN` when completion is unresolved.
- Stop only a registered instance whose PID, executable and command line still
  match the recorded state. Check tasks and save the model first.
- Separate implementation, static tests, unit tests, integration tests,
  simulated tests and real PFC acceptance in every report.

## Eight-module workflow

1. **Environment Manager**

   ```powershell
   & "<python>" "<skill>\scripts\headless.py" environment check `
     --dimension 3 --json-out "<report>.json"
   ```

   Stop if no verified Console or Bridge dependency is found.

2. **Engine Manager**

   Create or reuse an isolated registered instance:

   ```powershell
   & "<python>" "<skill>\scripts\headless.py" instance start `
     --project "<project>" --dimension 3 --port 9001 `
     --instance-id pfc3d_9001
   ```

   Never reuse a Bridge from a different working directory, product or
   dimension.

3. **Connection Manager**

   Require four evidence layers: current process identity, `/health`, PFC
   execution and an `itasca-mcp` round trip that echoes the instance nonce.
   Record current evidence with `connection record-mcp`, then run
   `connection verify`. Evidence from an older PID, command line, dimension or
   expired probe must never make a new instance `READY`.

4. **Project Manager**

   Create a Project and Case; preserve source configuration and model/script
   snapshots under each Run:

   ```powershell
   & "<python>" "<skill>\scripts\headless.py" project init ...
   & "<python>" "<skill>\scripts\headless.py" project add-case ...
   ```

5. **Simulation Manager**

   Use `run prepare` to create the immutable Run and obtain an official MCP
   operation request. The Agent Host calls `itasca_execute_task`, then records
   the returned task with `run attach-task`. Use `run status` and
   `run interrupt` to obtain the MCP query/interrupt operations, and
   `run record-status` / `run record-interrupt` to persist returned evidence.
   Finalize only completed Runs with `run finalize`; reconcile partial data
   with `run recover`.

6. **Data Collector**

   Generate capture from the versioned `collection_plan`. The plan uses an
   allow-list of channels and registered events, including Cycle/time/event
   scheduling, Ball fields, Wall data, optional contacts, explicit native
   Histories and optional fracture events. Required unsupported channels and
   missing source files fail before execution.

7. **Data Manager**

   Standardize to `pfc.standardized-experiment@1.0.0` and verify
   `metadata.json`, `manifest.json`, `validation_report.json`,
   `delivery_manifest.json`, hashes, offsets and record counts:

   ```powershell
   & "<python>" "<skill>\scripts\headless.py" data verify ...
   ```

   Publish by moving to a new Run directory; never patch a published package.

8. **Feedback Manager**

   Ingest structured Findings, validate referenced artifacts and data channels,
   require explicit approval, then create a proposed Run. Track
   `APPROVED -> PROPOSED -> RUNNING -> VALIDATED/FAILED`; only successful,
   validated delivery marks the feedback consumed. Failed feedback remains
   retryable. Feedback never edits the source model directly. Findings emitted
   by the Visualization Skill may reference artifacts in an external analysis
   root; those artifacts are copied into the project feedback directory and
   hashed so both skills' read-only boundaries hold.

   Use `run retry` to create a fresh immutable Run from a FAILED /
   TIMEOUT_UNKNOWN / INTERRUPTED attempt after fixing the case configuration;
   failed Runs themselves are never overwritten.

## Standard delivery

```text
<delivery>/
|-- delivery_manifest.json
|-- experiment.json
|-- metadata.json
|-- manifest.json
|-- validation_report.json
|-- conversion_report.json
|-- schema/
`-- cases/
```

Pass only the immutable delivery root to `pfc-scientific-visualization`.
Analysis output must be outside that root.

## References

- [references/architecture.md](references/architecture.md)
- [references/engine-lifecycle.md](references/engine-lifecycle.md)
- [references/task-management.md](references/task-management.md)
- [references/data-collection.md](references/data-collection.md)
- [references/data-contract.md](references/data-contract.md)
- [references/headless-bridge.md](references/headless-bridge.md)
- [references/standardized-delivery.md](references/standardized-delivery.md)
- [references/troubleshooting.md](references/troubleshooting.md)

## Completion rule

A generated package is not runtime success. Report real PFC2D/PFC3D,
Visualization, interruption and recovery evidence separately. Keep unrun gates
as `NOT_VERIFIED`.

