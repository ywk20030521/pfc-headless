# Data Contract

## Configuration and state

Project, Case, Instance, Run and Feedback documents are validated against the
JSON Schemas in `schema/`. State changes use atomic JSON replacement. Run
history is append-only by Run ID; a retry is always a new Run.

## Run layout

```text
<project>/
|-- project.json
|-- cases/
|   `-- case_<id>/
|       |-- case.json
|       `-- case_config.json
|-- instances/
|-- runs/
|   `-- <run_id>/
|       |-- input/
|       |-- entry/
|       |-- data/raw/
|       |-- metadata/
|       `-- logs/
|-- deliveries/
|   `-- <run_id>/
|-- analysis/
|   `-- feedback/
`-- audit/
```

## Data layers

| Layer | Producer | Contract |
|---|---|---|
| Raw capture | PFC embedded script | Original values, units and source; no display formatting |
| Standardized data | Headless offline converter | Variable-length NPZ arrays, schemas and hashes |
| Analysis/display data | Visualization | Separate root, linked to this package read-only |

The Headless package records `run_id`, `case_id`, dimension, engine version,
model/script identity, parameters, sampling, units, coordinate system, Cycle and
mechanical-time ranges, file hashes and record counts. Missing channels are
declared as `NOT_CAPTURED`, `NOT_SUPPORTED` or `INVALID`; they are never filled
with zeros.

## Publication

`delivery_manifest.json` is the immutable consumer contract. The additional
`metadata.json` and `manifest.json` provide a convenient complete package index
without changing the downstream contract name or version. Any changed output
requires a new Run and a new delivery directory.

