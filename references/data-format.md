# Capture Config and Output

> Scientific post-processing reads this format through a read-only adapter.
> The established `prepare_run.py`/`capture_case.py` path remains the default
> capture engine. The new result package is described in
> [output-contract.md](output-contract.md).

## Minimal config

```json
{
  "case_id": 0,
  "run_id": "case0_capture",
  "run_dir": "",
  "project_dir": "C:\\project",
  "restore_initial": false,
  "setup": [],
  "solve": "model solve time 50.0",
  "post_solve": [],
  "save": "model save 'final-case0'",
  "sample_stride_cycles": 500,
  "fracture_observer": false,
  "load_axis": "z",
  "top_wall_id": null,
  "bottom_wall_id": null,
  "history_names": ["1", "2", "3"],
  "expected_mechanical_time_run": null,
  "expected_initial": {},
  "source_files": {}
}
```

Optional keys: `load_axis` (`x`/`y`/`z`), `top_wall_id`/`bottom_wall_id`
(otherwise Walls named top/bottom, otherwise the extreme Walls along the axis),
`history_names`/`history_meanings`/`time_history_name`, and the guards
`expected_initial` (for example `{"balls": N, "walls": 2}`, compared with the
pre-solve snapshot), `expected_mechanical_time_run`, and `source_files`
(`name: sha256` of project files). Leave a guard empty or `null` to skip it.

`prepare_run.py` replaces `run_dir` with `<run-root>/data`. Put commands in the
same order as the source data file. `restore_initial` is a separate explicit
choice; do not set it merely to force a mismatch to pass.

## Output

```text
<run-root>/
|-- frames/
|   `-- blocks/
|       `-- block-000001/
|           |-- commit.json
|           |-- ball_frames.bin
|           `-- wall_frames.jsonl
|-- events/
|   |-- fracture_events.jsonl
|   `-- matched_fractures.jsonl
|-- histories/
|   |-- frame_metrics.csv
|   |-- native_1.csv
|   |-- native_2.csv
|   `-- native_3.csv
|-- recovery/
|   |-- raw/
|   |-- recovery_scan.json
|   `-- corrupt_tail_test.json    # only when explicitly tested
|-- manifest.json
|-- integrity_report.json
|-- entry/
|   |-- capture_case.py
|   `-- capture_config.json
`-- data/
    |-- static.json
    |-- native_histories.csv
    |-- fractures_final.json          # fracture cases only
    |-- raw/
    |   |-- ball_frames.csv
    |   |-- frame_index.csv
    |   |-- wall_vertices.csv
    |   `-- fracture_events.csv
    `-- metadata/
        |-- result.json
        `-- validation.json
```

`frame_index.csv` is the authoritative same-Cycle channel table. It stores
Cycle, Mechanical Time, Ball count, both Wall centers, both contact-force
magnitudes, and callback count. Every Ball and Wall row references
`frame_id`.

`fracture_events.csv` stores the break-time snapshot plus the endpoint Ball
IDs (`ball_id_a`, `ball_id_b`) taken from the contact at `bond_break`. These IDs
are the only link that lets downstream rendering follow the two particles as
they move; older captures without these columns remain valid and are reported
as `NOT_CAPTURED`.

The optional compact store writes committed blocks after capture. `commit.json`
records frame offsets, lengths, CRC32, SHA-256, Ball count, Wall count,
fracture count, and Cycle continuity. Frame IDs are monotonic across blocks.

`integrity_report.json` must contain:

- `status`, `frame_count`, and `last_complete_cycle`;
- `block_recovery` with valid blocks and any rejected tail;
- `additional_events.ball_id_changes`, where every change has `frame_id`,
  `cycle`, `added_ids`, `removed_ids`, and `added_radius`;
- `additional_events.native_histories` with row counts and SHA-256;
- `additional_events.float32_precision` and `fracture_match`.

For a Ball created during a run, encode its radius in the first frame where
the new ID appears. For a deletion, record the missing ID by the changed ID
set. Do not infer a deletion from count alone.

## Acceptance invariants

- `result.json.status == COMPLETE`
- data boundary is `REAL_PFC`
- Cycles and Mechanical Times strictly increase
- every indexed Ball row count matches its frame
- Ball IDs are unique inside each frame
- added/removed Ball IDs are reported per frame and round-trip correctly
- every Wall vertex listed in `static.json` exists in every frame
- all coordinates and forces are finite
- recorded file sizes and SHA-256 values match
- fracture event count equals unique DFN matches

When the final block is deliberately corrupted:

- `recover_blocks()` must return `INVALID_TAIL_REJECTED`;
- only blocks before the corrupt tail may be listed as valid;
- the valid frame count and last valid Cycle must match the last valid block;
- an independent frame reader must decode the valid frames without the
  corrupt block.

Any invalid non-tail block is fatal. Do not discard earlier blocks to hide it.

`validate_capture.py` writes `metadata/validation.json`. A failed invariant is a
stop condition; do not repair values by interpolation or copying.

## Wall facet topology (PFC3D)

Wall vertex positions alone (`wall_vertex_xyz`) describe a point cloud, not
faces. To let the downstream Viewer draw **real wall planes** instead of rods,
the standardized package carries static facet topology (PFC3D only; PFC2D and
old deliveries have empty arrays):

- `wall_facet_id`, `wall_facet_wall_id`, `wall_facet_active` — one row per facet.
- `wall_facet_normal` (N,3) — facet unit normal, static.
- `wall_facet_vertex_offsets` — flat-array offsets into the vertex-ID list.
- `wall_facet_vertex_ids` — the corner vertex IDs of every facet, flat.

The corner IDs are resolved against the per-frame `wall_vertex_id` /
`wall_vertex_xyz` arrays: topology is static, positions move with each frame.
A PFC3D `wall generate ... plane` wall is two triangular facets (e.g. corners
`[1,2,3]` and `[3,2,4]`). The capture layer obtains these IDs from
`facet.vertices()` in `read_wall_static()`; `standardize/legacy.py` preserves
them and `standardize/converter.py` exports the arrays. Before this addition,
the facet `id/active/position/normal` existed but the vertex topology was
dropped, so only vertex rods could be drawn.

## Handoff

The capture tree is converted by `run_standardization.py`. The downstream
contract is [standardized-delivery.md](standardized-delivery.md). No scientific
stress/strain derivation, chart or Viewer artifact is produced by this Skill.
