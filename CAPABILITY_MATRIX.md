# Capability Matrix

The maintained matrix, including real PFC and downstream verification, is in
[reports/CAPABILITY_MATRIX.md](reports/CAPABILITY_MATRIX.md).

High-level result:

- PFC2D and PFC3D Console discovery: REAL VERIFIED.
- MCP-only Run orchestration and current-instance READY evidence: REAL VERIFIED.
- Simultaneous PFC2D/PFC3D instances on independent MCP connections: REAL
  VERIFIED.
- Project/Case/Run management: IMPLEMENTED AND CONTRACT TESTED.
- Long/short tasks, status and interruption: REAL VERIFIED.
- Particle, velocity/spin, Wall and optional contact capture: REAL VERIFIED
  (3D contacts not yet verified).
- Standardized package and Visualization read: REAL VERIFIED for 2D and 3D.
- Feedback state machine -> new Run -> validated delivery or retryable failure:
  REAL VERIFIED.
- Visualization Findings Producer -> Headless ingest: REAL VERIFIED.
- GUI execution: FORBIDDEN.

