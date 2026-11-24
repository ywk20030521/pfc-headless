# Data Collection

## Sampling

- `cycle`: write when Cycle advances by the configured stride.
- `time`: write when PFC mechanical time advances by the configured interval.
- `event`: write initial/final frames and fracture events when enabled.

Runs record the requested mode/value and the actual sampled Cycle/time.

Each Case and Run also stores a versioned `collection_plan`. Channels are an
allow-list of supported sources; events are registered names such as `cycle`,
`time`, `solve` and `fracture`. Required unsupported channels fail before
execution.

## Fields

Ball capture includes ID, position, radius, velocity and angular velocity.
Wall capture includes vertex positions and platen aggregate forces. Optional
contact capture includes contact ID, endpoint type/ID, global position, global
force and model. Native Histories remain uninterpreted until metadata declares
their meaning and unit.

The `bond_break` observer also records the two endpoint Ball IDs from
`contact.end1` / `contact.end2` as `ball_id_a` and `ball_id_b` in
`fracture_events.csv`. Non-Ball endpoints (for example a Wall) are written as
`-1`. The converter exports them as `fracture_ball_id_a` and
`fracture_ball_id_b`, allowing the Viewer to re-anchor cracks to the current
per-frame particle positions instead of keeping the break-time snapshot fixed.
Datasets captured before this field was added remain valid: the endpoint
channels are `NOT_CAPTURED` and the Viewer falls back to static crack geometry.

Contact capture is opt-in because it can dominate output size and runtime.
Absence of contacts in a model is not an integrity error. When contact capture
is disabled, the delivery declares contact channels `NOT_CAPTURED`.

Clump membership is not silently generalized. It is added only after the target
version API and real model are verified.

## PFC2D

The z coordinate is written as numeric zero for PFC2D vector APIs. The dataset
remains two-dimensional. A line load is not converted to a fictitious 3D stress.

Platen roles default to the `y` axis in 2D when `load_axis` is not configured;
sorting by `z` would select side walls because every wall has z=0. Bond-break
FISH events are the authoritative fracture record in 2D: PFC2D has no
`itasca.dfn` catalog, so `fractures_final.json` is published as `[]` with
`fracture_catalog_status=NOT_SUPPORTED` and validation does not require a DFN
cross-match.

When no explicit collection plan is supplied, case-level `capture_contacts`,
`fracture_observer` and `history_names` seed the default plan so
`apply_plan_to_config` cannot silently discard them. An explicit run-level
plan still wins.

## Integration

The capture block is installed before solve, uses PFC callbacks, records
same-Cycle identity checks and writes raw files during execution. Final metadata
and hashes are written only after the script leaves the solve path.


## FISH CSV writing pitfalls (2026-11-23 incident)

Two FISH-side mistakes produced invalid raw CSV while the Python converter was
correct. Both were found in real PFC runs and are now fixed in
`scripts/capture_case.py`:

1. **Multi-digit `string.build` placeholders are unsafe.** FISH resolves
   `%10`/`%11` as `%1` followed by a digit, which silently shifted fracture
   coordinates (y became `event_id*10`, z became `event_id*10+1`). Use
   `%1`–`%9` only, or build rows with `string(value)` concatenation for any
   field beyond the ninth.
2. **Endpoint IDs must be stable Ball IDs, not pointer IDs.**
   `contact.end1/end2` returns a piece pointer; `type.pointer.id(piece)` is a
   process-local address (e.g. `1284443565`) that never matches `ball_id`.
   Resolve with `ball.id(piece)` through the shared
   `_pfc_live_capture_endpoint_ball_id()` helper, writing `-1` for non-Ball
   endpoints (walls). The same helper must be installed before the contact
   capture block; it lives in the common FISH block, not only in the fracture
   observer.

Both failures are silent: row counts and hashes stay valid, and only the
downstream Viewer reveals that endpoints or coordinates are unusable. Always
spot-check raw CSV endpoint ranges against `ball_id` and plot coordinate
magnitudes after a real capture.
