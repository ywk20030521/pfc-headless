# Implementation Report

## PR1: architecture and contracts

- Added the eight-module package under `scripts/pfc_headless/`.
- Added Project, Case, Instance, Run, Manifest, Metadata and Feedback schemas.
- Froze entity ownership and the `pfc.standardized-experiment@1.0.0` boundary.
- Documented raw/standardized/analysis ownership.

## PR2: environment manager

- Added content-based PFC2D/PFC3D Console discovery.
- Added multiple-root and registry discovery.
- Added GUI rejection, engine Python checks, Bridge dependency checks and MCP
  configuration diagnostics.
- Preserved inferred version evidence without treating the path as runtime proof.

## PR3: Engine and Connection managers

- Isolated state/directories per registered instance.
- Added four-layer readiness with external MCP evidence.
- Added working-directory identity checks to prevent cross-instance reuse.
- Added task inspection, model save, identity re-check and audited stop.
- Added safe PowerShell start/stop/discovery wrappers.

## PR4: Project and Simulation managers

- Added Project initialization, Case registration and immutable Run snapshots.
- Added scalar parameter substitution and sampling configuration.
- Added short `execute_code` and long `execute_task` branches.
- Added Task ID mapping, status queries, interrupt requests and timeout state.
- Refactored prepared-Run execution so feedback-created Runs can be executed.

## PR5: Data Collector

- Added Ball velocity and angular velocity.
- Added optional contact ID, endpoint types/IDs, position, global force and
  contact model.
- Added Cycle, mechanical-time and event scheduling.
- Added field-status declarations and raw canonical tables.
- Preserved dynamic Ball IDs and real dimensional differences.

## PR6: Data Manager

- Added `metadata.json`, `manifest.json` and `validation_report.json`.
- Added model/script identity, units, coordinate system, time/step ranges,
  file hashes and record counts.
- Added independent package verification and tamper detection.
- Continued emitting the existing immutable downstream manifest.

## PR7: Feedback Manager

- Added schema validation, artifact/channel/time checks and approval.
- Added scalar-only model overrides.
- Added new Run creation and execution without source Run mutation.
- Recorded feedback source, reviewer and decision audit.

## PR8: integration

- Ran 34 unit/contract tests.
- Ran real PFC2D and PFC3D Console, Bridge and MCP gates.
- Ran tracked and synchronous tasks.
- Verified contact capture, time sampling, interruption and timeout state.
- Delivered four real packages to Visualization.
- Closed one real feedback-to-new-Run-to-redelivery loop.
- Added final reports and a preserved acceptance workspace.

## PR9-PR14: strict architecture rectification

- Replaced Headless Run submission/status/interrupt HTTP calls with official
  MCP operation descriptors and Agent-recorded evidence.
- Bound READY evidence to current PID, executable, command line, dimension,
  port, instance ID, MCP connection, nonce and expiry.
- Resolved status/interrupt routes automatically from Run Registry and verified
  two simultaneous Console instances through independent MCP connections.
- Reworked Feedback attempts into a retryable state machine and delayed
  consumption until successful delivery validation.
- Added versioned collection plans with channel/event allow-lists, explicit
  History selection and fail-closed source snapshots.
- Integrated current-capture recovery into the Run Registry and disabled
  derived stress/strain generation from the default Headless path.
- Added `pfc.analysis-findings@1.0.0` production in Visualization and contract
  validation/ingestion in Headless.

