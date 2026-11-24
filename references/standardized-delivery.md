# Standardized Experiment Delivery

## Contract identity

The only handoff to scientific post-processing is the versioned contract:

```text
pfc.standardized-experiment@1.0.0
```

The producer is `pfc-headless`. The consumer is
`pfc-scientific-visualization`.

## Ownership

`pfc-headless` owns:

- captured raw files;
- capture logs and quality evidence;
- Case/Frame/Cycle/time/entity metadata;
- conversion reports;
- the standardized arrays and schemas;
- `delivery_manifest.json`.

`pfc-scientific-visualization` owns:

- derived physical quantities;
- statistical analysis;
- chart decisions and chart specifications;
- Viewer payloads and interactive scenes;
- publication composition and analysis reports.

Neither Skill writes into the other's managed tree. Analysis output must use a
separate root.

## Required root

```text
<StandardizedExperiment>/
|-- delivery_manifest.json
|-- experiment.json
|-- metadata.json
|-- manifest.json
|-- validation_report.json
|-- conversion_report.json
|-- schema/
|   |-- experiment.schema.json
|   |-- case.schema.json
|   |-- channel.schema.json
|   `-- frame.schema.json
`-- cases/
    `-- case_N/
        |-- arrays.npz
        |-- case.json
        |-- channels.json
        |-- frames.json
        |-- events.json
        |-- entity_changes.json
        |-- frame_summary.csv
        `-- conversion_report.json
```

The canonical numerical representation is `arrays.npz`. Independent `.npy`
files are optional and must not replace the NPZ as the contract input.

`metadata.json` records model/script identity, parameters, sampling, units,
coordinate system, time/step ranges, hashes and record counts.
`manifest.json` indexes every package file. `validation_report.json` records
the independent package checks. All three are published before
`delivery_manifest.json`; the downstream contract remains
`pfc.standardized-experiment@1.0.0`.

## Manifest checks

The consumer must verify:

- `contract.name == "pfc.standardized-experiment"`;
- `contract.version == "1.0.0"`;
- `contract.immutable == true`;
- `consumer_policy.read_only == true`;
- `consumer_policy.may_write_inside_contract == false`;
- `experiment.json` hash matches;
- every listed artifact exists and matches its size and SHA-256;
- every Case has arrays and a matching `arrays_sha256`;
- core NPZ keys and frame-offset lengths are consistent.

Any mismatch is a stop condition. Do not patch or normalize the published
contract during analysis.

## Array contract

Required frame keys:

- `cycle`;
- `mechanical_time_total`;
- `frame_offsets`;
- `ball_id`;
- `ball_xyz`;
- `ball_radius`;
- `ball_frame_index`;
- `wall_offsets`;
- `wall_id`;
- `wall_vertex_id`;
- `wall_vertex_xyz`.

Required fracture keys exist as empty arrays when no fracture channel was
captured:

- `fracture_event_id`;
- `fracture_cycle`;
- `fracture_mechanical_time_total`;
- `fracture_mode`;
- `fracture_position`;
- `fracture_normal`;
- `fracture_diameter`.

Optional fracture endpoint keys are emitted only when the FISH `bond_break`
observer actually captured both Ball IDs:

- `fracture_ball_id_a`;
- `fracture_ball_id_b`.

They let the Viewer re-anchor a crack to the current positions of the two
Balls whose bond broke. Missing values use the explicit `-1` sentinel for a
non-Ball or uncaptured endpoint; no fabricated ID is invented. When neither
endpoint was captured, both keys are omitted and the channels are declared
`NOT_CAPTURED`.

Optional frame channels such as `top_force_n`, `bottom_force_n` and
`platen_distance_m` are omitted when unavailable. They are never represented
as fabricated zero arrays.

## Scientific ownership

The contract supplies captured evidence and declared physical metadata. It does
not contain scientific analysis conclusions. Derived displacement, speed,
acceleration, strain, nominal stress, correlation, chart decisions and Viewer
payloads must be produced by the scientific Skill and written to its own
analysis root.

## Republishing

A changed capture or conversion creates a new standardized root and manifest.
Never edit a published standardized tree in place. If a defect is found, record
the failed manifest and regenerate into a new directory.
