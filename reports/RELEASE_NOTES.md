# Release Notes

## 1.0.0 - 2026-11-16

### Added

- Eight-module Project/Case/Run/data/feedback management CLI.
- Verified Console discovery for PFC2D and PFC3D.
- Four-layer MCP-backed readiness.
- Isolated instance registry and audited safe stop.
- Ball velocity/spin and optional contact-network capture.
- Cycle, mechanical-time and event sampling modes.
- Package metadata, full file manifest and quality report.
- Structured Analysis Feedback approval and rerun workflow.
- Unit/contract tests and real PFC acceptance evidence.

### Preserved

- Existing `pfc.standardized-experiment@1.0.0` downstream interface.
- Variable-length entity arrays and dynamic Ball ID sets.
- Raw capture immutability and recovery.
- PFC2D planar semantics.

### Known issues

- PFC `program stop` may outlive the 20-second stop window and require verified
  PID termination after model save.
- Concurrent engines require separate MCP process configurations.
- Viewer/browser acceptance is not part of Headless.

